from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .models import ChatMessage, ConsultationCategory, ConsultationSession
from .prompts import BASE_SYSTEM_PROMPT, PROMPTS


AUTO_ESCALATION_CONFIDENCE_THRESHOLD = 0.85
MAX_CLARIFYING_QUESTIONS = 3
TRACE_PREVIEW_LENGTH = 400

logger = logging.getLogger(__name__)

CATEGORY_LOOKUPS = {
    ConsultationSession.AnalysisCategory.FAMILY: (
        {"slug": "family-law"},
        {"slug": "семейное-право"},
        {"name__iexact": "Семейное право"},
    ),
    ConsultationSession.AnalysisCategory.LABOR: (
        {"slug": "labor-law"},
        {"slug": "трудовое-право"},
        {"name__iexact": "Трудовое право"},
    ),
    ConsultationSession.AnalysisCategory.HOUSING: (
        {"slug": "housing-law"},
        {"slug": "жилищное-право"},
        {"name__iexact": "Жилищное право"},
    ),
    ConsultationSession.AnalysisCategory.CONSUMER: (
        {"slug": "consumer-law"},
        {"slug": "защита-прав-потребителей"},
        {"name__iexact": "Защита прав потребителей"},
    ),
    ConsultationSession.AnalysisCategory.INHERITANCE: (
        {"slug": "inheritance-law"},
        {"slug": "наследственное-право"},
        {"name__iexact": "Наследственное право"},
    ),
    ConsultationSession.AnalysisCategory.ADMINISTRATIVE: (
        {"slug": "administrative-law"},
        {"slug": "административные-вопросы"},
        {"name__iexact": "Административные вопросы"},
    ),
    ConsultationSession.AnalysisCategory.CIVIL: (
        {"slug": "civil-law"},
        {"slug": "гражданское-право"},
        {"name__icontains": "Граждан"},
    ),
}

CATEGORY_LABELS = {
    ConsultationSession.AnalysisCategory.FAMILY: "Семейное право",
    ConsultationSession.AnalysisCategory.LABOR: "Трудовое право",
    ConsultationSession.AnalysisCategory.HOUSING: "Жилищное право",
    ConsultationSession.AnalysisCategory.CONSUMER: "Защита прав потребителей",
    ConsultationSession.AnalysisCategory.INHERITANCE: "Наследственное право",
    ConsultationSession.AnalysisCategory.ADMINISTRATIVE: "Административные вопросы",
    ConsultationSession.AnalysisCategory.CIVIL: "Гражданские вопросы",
    ConsultationSession.AnalysisCategory.OTHER: "Иные правовые вопросы",
}

DEFAULT_CLARIFYING_QUESTIONS = [
    "Какие ключевые обстоятельства произошли и кто является другой стороной ситуации?",
    "На каком этапе находится вопрос сейчас: только возник спор, уже подано заявление или есть официальный ответ?",
    "Есть ли документы, даты, суммы или иные конкретные данные, которые могут повлиять на первичный вывод?",
]

RESPONSE_PROMPT_KEYS = {
    ConsultationSession.AnalysisScenario.TYPICAL_ANSWER: "typical_answer",
    ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION: "clarification",
    ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST: "needs_specialist",
    ConsultationSession.AnalysisScenario.OUT_OF_SCOPE: "out_of_scope",
    ConsultationSession.AnalysisScenario.INSUFFICIENT_CONFIDENCE: "insufficient_confidence",
}


@dataclass
class LLMResponse:
    text: str
    status: str
    model_name: str
    total_duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_text: str = ""


@dataclass
class ConsultationAnalysis:
    scenario: str
    category: str
    is_typical: bool
    has_enough_information: bool
    needs_clarification: bool
    needs_specialist: bool
    confidence: float
    missing_information: list[str]
    clarifying_questions: list[str]
    short_reason: str

    @classmethod
    def fallback(cls, reason: str) -> "ConsultationAnalysis":
        return cls(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.OTHER,
            is_typical=True,
            has_enough_information=False,
            needs_clarification=True,
            needs_specialist=False,
            confidence=0.0,
            missing_information=["Недостаточно корректно структурированных данных для автоматического анализа."],
            clarifying_questions=DEFAULT_CLARIFYING_QUESTIONS[:2],
            short_reason=reason,
        )

    @classmethod
    def from_response_text(cls, text: str) -> "ConsultationAnalysis":
        cleaned_text = cls._extract_json_block(text)
        try:
            payload = json.loads(cleaned_text)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM не вернул корректный JSON анализа.") from exc
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ConsultationAnalysis":
        if not isinstance(payload, dict):
            raise ValueError("JSON анализа должен быть объектом.")

        scenario = payload.get("scenario")
        if scenario not in ConsultationSession.AnalysisScenario.values:
            raise ValueError("Недопустимое значение scenario в JSON анализа.")

        category = payload.get("category") or ConsultationSession.AnalysisCategory.OTHER
        if category not in ConsultationSession.AnalysisCategory.values:
            category = ConsultationSession.AnalysisCategory.OTHER

        analysis = cls(
            scenario=scenario,
            category=category,
            is_typical=bool(payload.get("is_typical", scenario in {
                ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
                ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            })),
            has_enough_information=bool(
                payload.get(
                    "has_enough_information",
                    scenario == ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
                )
            ),
            needs_clarification=bool(
                payload.get(
                    "needs_clarification",
                    scenario == ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
                )
            ),
            needs_specialist=bool(
                payload.get(
                    "needs_specialist",
                    scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST,
                )
            ),
            confidence=cls._coerce_confidence(payload.get("confidence")),
            missing_information=cls._normalize_string_list(payload.get("missing_information")),
            clarifying_questions=cls._normalize_string_list(payload.get("clarifying_questions")),
            short_reason=str(payload.get("short_reason") or "").strip(),
        )
        return analysis.normalized()

    @staticmethod
    def _extract_json_block(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
            stripped = "\n".join(lines).strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end >= start:
            return stripped[start : end + 1]
        return stripped

    @staticmethod
    def _coerce_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(confidence, 1.0))

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def normalized(self) -> "ConsultationAnalysis":
        scenario = self.scenario
        category = (
            self.category
            if self.category in ConsultationSession.AnalysisCategory.values
            else ConsultationSession.AnalysisCategory.OTHER
        )
        missing_information = self.missing_information[:MAX_CLARIFYING_QUESTIONS]
        clarifying_questions = self.clarifying_questions[:MAX_CLARIFYING_QUESTIONS]
        confidence = max(0.0, min(self.confidence, 1.0))
        short_reason = self.short_reason or "Автоматический анализ не вернул достаточно надёжное обоснование."

        if scenario == ConsultationSession.AnalysisScenario.INSUFFICIENT_CONFIDENCE:
            if self.needs_specialist and confidence >= AUTO_ESCALATION_CONFIDENCE_THRESHOLD:
                scenario = ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST
            else:
                scenario = ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION

        if (
            scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST
            and confidence < AUTO_ESCALATION_CONFIDENCE_THRESHOLD
        ):
            scenario = ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION

        if scenario == ConsultationSession.AnalysisScenario.TYPICAL_ANSWER and (
            not self.has_enough_information or self.needs_clarification
        ):
            scenario = ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION

        if scenario == ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION:
            clarifying_questions = self._ensure_clarifying_questions(
                clarifying_questions,
                missing_information,
            )
            return ConsultationAnalysis(
                scenario=scenario,
                category=category,
                is_typical=True,
                has_enough_information=False,
                needs_clarification=True,
                needs_specialist=False,
                confidence=confidence,
                missing_information=missing_information,
                clarifying_questions=clarifying_questions,
                short_reason=short_reason,
            )

        if scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST:
            return ConsultationAnalysis(
                scenario=scenario,
                category=category,
                is_typical=False,
                has_enough_information=False,
                needs_clarification=False,
                needs_specialist=True,
                confidence=confidence,
                missing_information=missing_information,
                clarifying_questions=[],
                short_reason=short_reason,
            )

        if scenario == ConsultationSession.AnalysisScenario.OUT_OF_SCOPE:
            return ConsultationAnalysis(
                scenario=scenario,
                category=ConsultationSession.AnalysisCategory.OTHER,
                is_typical=False,
                has_enough_information=False,
                needs_clarification=False,
                needs_specialist=False,
                confidence=confidence,
                missing_information=[],
                clarifying_questions=[],
                short_reason=short_reason,
            )

        return ConsultationAnalysis(
            scenario=ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
            category=category,
            is_typical=True,
            has_enough_information=True,
            needs_clarification=False,
            needs_specialist=False,
            confidence=confidence,
            missing_information=missing_information,
            clarifying_questions=[],
            short_reason=short_reason,
        )

    @staticmethod
    def _ensure_clarifying_questions(
        questions: list[str],
        missing_information: list[str],
    ) -> list[str]:
        if questions:
            return questions[:MAX_CLARIFYING_QUESTIONS]
        if missing_information:
            return [
                f"Уточните, пожалуйста: {item[0].lower() + item[1:] if len(item) > 1 else item.lower()}?"
                for item in missing_information[:MAX_CLARIFYING_QUESTIONS]
            ]
        return DEFAULT_CLARIFYING_QUESTIONS[:MAX_CLARIFYING_QUESTIONS]


@dataclass
class ProcessedConsultationReply:
    analysis: ConsultationAnalysis
    llm_response: LLMResponse
    analysis_llm_response: LLMResponse | None = None


class OllamaService:
    @staticmethod
    def _preview_text(text: str, limit: int = TRACE_PREVIEW_LENGTH) -> str:
        normalized = " ".join(str(text).split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}..."

    @classmethod
    def _trace(cls, event: str, **payload: Any) -> None:
        serialized_payload = json.dumps(payload, ensure_ascii=False, default=str)
        logger.warning("consultation.llm.%s %s", event, serialized_payload)

    @staticmethod
    def _recent_session_messages(
        session: ConsultationSession,
        exclude_message_ids: set[int] | None = None,
    ) -> list[dict[str, str]]:
        queryset = session.messages.filter(
            is_error=False,
            role__in=(ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT),
        )
        if exclude_message_ids:
            queryset = queryset.exclude(pk__in=exclude_message_ids)

        limit = settings.OLLAMA_SESSION_MEMORY_LIMIT

        if limit > 0:
            history = list(
                queryset.order_by("-created_at", "-pk").values("role", "content")[:limit]
            )
            history.reverse()
            return history

        return list(queryset.order_by("created_at", "pk").values("role", "content"))

    @classmethod
    def _build_messages(
        cls,
        session: ConsultationSession,
        system_prompt: str | None = None,
        exclude_message_ids: set[int] | None = None,
    ) -> list[dict[str, str]]:
        history = cls._recent_session_messages(session, exclude_message_ids=exclude_message_ids)
        return [
            {"role": "system", "content": system_prompt or BASE_SYSTEM_PROMPT},
            *history,
        ]

    @staticmethod
    def _format_conversation_history(
        messages: list[dict[str, str]],
    ) -> str:
        if not messages:
            return "История диалога пока отсутствует."

        lines = []
        for item in messages:
            role = item["role"]
            if role == ChatMessage.Role.USER:
                speaker = "Пользователь"
            elif role == ChatMessage.Role.ASSISTANT:
                speaker = "Ассистент"
            else:
                speaker = "Система"
            lines.append(f"{speaker}: {item['content']}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_prompt_list(items: list[str], *, numbered: bool = False) -> str:
        if not items:
            return "Нет дополнительных данных."
        if numbered:
            return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _render_prompt(template: str, **context: str) -> str:
        rendered = template
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered

    @classmethod
    def _build_single_prompt_messages(cls, prompt_text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": BASE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ]

    @classmethod
    def _perform_ollama_chat(cls, messages: list[dict[str, str]]) -> LLMResponse:
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{settings.OLLAMA_URL.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.OLLAMA_TIMEOUT) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return LLMResponse(
                text="Не удалось получить ответ от Ollama. Проверьте доступность сервиса и параметры подключения.",
                status="error",
                model_name=settings.OLLAMA_MODEL,
                error_text=str(exc),
            )

        message = data.get("message", {})
        text = message.get("content") or "Модель не вернула текст ответа."
        total_duration = data.get("total_duration")
        total_duration_ms = (
            int(total_duration / 1_000_000) if isinstance(total_duration, int) else None
        )

        return LLMResponse(
            text=text,
            status="success",
            model_name=data.get("model", settings.OLLAMA_MODEL),
            total_duration_ms=total_duration_ms,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    @classmethod
    def _detect_category_from_text(cls, text: str) -> str:
        lowered = text.lower()
        keyword_mapping = {
            ConsultationSession.AnalysisCategory.FAMILY: ("развод", "алим", "брак", "ребен", "семь"),
            ConsultationSession.AnalysisCategory.LABOR: ("увольн", "зарплат", "работод", "труд"),
            ConsultationSession.AnalysisCategory.HOUSING: ("квартир", "жиль", "аренд", "коммун"),
            ConsultationSession.AnalysisCategory.CONSUMER: ("товар", "магазин", "продав", "потребител", "услуг"),
            ConsultationSession.AnalysisCategory.INHERITANCE: ("наслед", "завещан"),
            ConsultationSession.AnalysisCategory.ADMINISTRATIVE: ("штраф", "жалоб", "госорган", "административ"),
            ConsultationSession.AnalysisCategory.CIVIL: ("договор", "долг", "расписк", "обязательств"),
        }
        for category, keywords in keyword_mapping.items():
            if any(keyword in lowered for keyword in keywords):
                return category
        return ConsultationSession.AnalysisCategory.OTHER

    @classmethod
    def _demo_analysis(
        cls,
        session: ConsultationSession,
        user_message: ChatMessage,
    ) -> ConsultationAnalysis:
        text = user_message.content.strip()
        lowered = text.lower()
        category = cls._detect_category_from_text(text)

        if any(keyword in lowered for keyword in ("погода", "рецепт", "фильм", "музыка")):
            return ConsultationAnalysis(
                scenario=ConsultationSession.AnalysisScenario.OUT_OF_SCOPE,
                category=ConsultationSession.AnalysisCategory.OTHER,
                is_typical=False,
                has_enough_information=False,
                needs_clarification=False,
                needs_specialist=False,
                confidence=0.9,
                missing_information=[],
                clarifying_questions=[],
                short_reason="Запрос не относится к юридической консультации.",
            )

        if any(keyword in lowered for keyword in ("суд", "иск", "обжал", "уголов", "арест", "срок")):
            return ConsultationAnalysis(
                scenario=ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST,
                category=category,
                is_typical=False,
                has_enough_information=False,
                needs_clarification=False,
                needs_specialist=True,
                confidence=0.9,
                missing_information=[],
                clarifying_questions=[],
                short_reason="Ситуация выглядит сложной или процессуально значимой.",
            )

        if len(text) < 60:
            return ConsultationAnalysis(
                scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
                category=category,
                is_typical=True,
                has_enough_information=False,
                needs_clarification=True,
                needs_specialist=False,
                confidence=0.55,
                missing_information=["Недостаточно фактических обстоятельств обращения."],
                clarifying_questions=DEFAULT_CLARIFYING_QUESTIONS[:2],
                short_reason="Для первичного ответа не хватает исходных данных.",
            )

        return ConsultationAnalysis(
            scenario=ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
            category=category,
            is_typical=True,
            has_enough_information=True,
            needs_clarification=False,
            needs_specialist=False,
            confidence=0.72,
            missing_information=[],
            clarifying_questions=[],
            short_reason="В демонстрационном режиме вопрос классифицирован как типовой.",
        )

    @classmethod
    def _serialize_analysis(cls, analysis: ConsultationAnalysis) -> str:
        return json.dumps(
            {
                "scenario": analysis.scenario,
                "category": analysis.category,
                "is_typical": analysis.is_typical,
                "has_enough_information": analysis.has_enough_information,
                "needs_clarification": analysis.needs_clarification,
                "needs_specialist": analysis.needs_specialist,
                "confidence": analysis.confidence,
                "missing_information": analysis.missing_information,
                "clarifying_questions": analysis.clarifying_questions,
                "short_reason": analysis.short_reason,
            },
            ensure_ascii=False,
        )

    @classmethod
    def _analyze_user_message_with_trace(
        cls,
        session: ConsultationSession,
        user_message: ChatMessage,
    ) -> tuple[ConsultationAnalysis, LLMResponse]:
        if not settings.OLLAMA_ENABLED:
            analysis = cls._demo_analysis(session, user_message)
            cls._trace(
                "analysis.demo",
                session_id=session.pk,
                message_id=user_message.pk,
                scenario=analysis.scenario,
                category=analysis.category,
                confidence=analysis.confidence,
                user_message=cls._preview_text(user_message.content),
            )
            return analysis, LLMResponse(
                text=cls._serialize_analysis(analysis),
                status="demo",
                model_name=settings.OLLAMA_MODEL,
            )

        history = cls._format_conversation_history(
            cls._recent_session_messages(session, exclude_message_ids={user_message.pk})
        )
        prompt = cls._render_prompt(
            PROMPTS["scenario_analyzer"],
            conversation_history=history,
            user_message=user_message.content,
        )
        cls._trace(
            "analysis.request",
            session_id=session.pk,
            message_id=user_message.pk,
            user_message=cls._preview_text(user_message.content),
        )
        response = cls._perform_ollama_chat(cls._build_single_prompt_messages(prompt))
        cls._trace(
            "analysis.response",
            session_id=session.pk,
            message_id=user_message.pk,
            status=response.status,
            model=response.model_name,
            response_text=cls._preview_text(response.text),
            error_text=response.error_text,
        )
        if response.status != "success":
            return ConsultationAnalysis.fallback(
                "Анализ обращения не выполнен из-за ошибки обращения к Ollama."
            ), response

        try:
            analysis = ConsultationAnalysis.from_response_text(response.text)
        except ValueError as exc:
            cls._trace(
                "analysis.invalid_json",
                session_id=session.pk,
                message_id=user_message.pk,
                error=str(exc),
                response_text=cls._preview_text(response.text),
            )
            return ConsultationAnalysis.fallback(
                "Ответ анализатора не удалось корректно распознать, поэтому требуется уточнение."
            ), LLMResponse(
                text=response.text,
                status="error",
                model_name=response.model_name,
                total_duration_ms=response.total_duration_ms,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                error_text=str(exc),
            )
        cls._trace(
            "analysis.normalized",
            session_id=session.pk,
            message_id=user_message.pk,
            scenario=analysis.scenario,
            category=analysis.category,
            confidence=analysis.confidence,
            needs_clarification=analysis.needs_clarification,
            needs_specialist=analysis.needs_specialist,
        )
        return analysis, response

    @classmethod
    def analyze_user_message(
        cls,
        session: ConsultationSession,
        user_message: ChatMessage,
    ) -> ConsultationAnalysis:
        analysis, _ = cls._analyze_user_message_with_trace(session, user_message)
        return analysis

    @classmethod
    def _category_label(cls, category_code: str) -> str:
        return CATEGORY_LABELS.get(category_code, CATEGORY_LABELS[ConsultationSession.AnalysisCategory.OTHER])

    @classmethod
    def _resolve_category(cls, category_code: str) -> ConsultationCategory | None:
        for lookup in CATEGORY_LOOKUPS.get(category_code, ()):
            category = ConsultationCategory.objects.filter(**lookup).first()
            if category:
                return category
        return None

    @classmethod
    def apply_analysis_to_session(
        cls,
        session: ConsultationSession,
        analysis: ConsultationAnalysis,
    ) -> None:
        updated_fields: list[str] = []
        preserve_specialist_mode = (
            session.requires_specialist or session.status == ConsultationSession.Status.NEEDS_SPECIALIST
        )

        if session.last_analysis_scenario != analysis.scenario:
            session.last_analysis_scenario = analysis.scenario
            updated_fields.append("last_analysis_scenario")

        if session.last_analysis_category != analysis.category:
            session.last_analysis_category = analysis.category
            updated_fields.append("last_analysis_category")

        resolved_category = cls._resolve_category(analysis.category)
        if resolved_category and session.category_id != resolved_category.pk:
            session.category = resolved_category
            updated_fields.append("category")

        awaiting_clarification = (
            analysis.scenario == ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION
            and not preserve_specialist_mode
        )
        if session.awaiting_clarification != awaiting_clarification:
            session.awaiting_clarification = awaiting_clarification
            updated_fields.append("awaiting_clarification")

        requires_specialist = preserve_specialist_mode or (
            analysis.scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST
        )
        if session.requires_specialist != requires_specialist:
            session.requires_specialist = requires_specialist
            updated_fields.append("requires_specialist")

        if session.status != ConsultationSession.Status.CLOSED:
            target_status = session.status
            if session.status == ConsultationSession.Status.NEEDS_SPECIALIST:
                target_status = ConsultationSession.Status.NEEDS_SPECIALIST
            elif analysis.scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST:
                target_status = ConsultationSession.Status.NEEDS_SPECIALIST
            elif session.status == ConsultationSession.Status.NEW:
                target_status = ConsultationSession.Status.IN_PROGRESS

            if session.status != target_status:
                session.status = target_status
                updated_fields.append("status")

        if updated_fields:
            session.save(update_fields=[*updated_fields, "updated_at"])

    @classmethod
    def _demo_generate_response(
        cls,
        analysis: ConsultationAnalysis,
        user_message: ChatMessage,
        *,
        after_clarification: bool = False,
    ) -> LLMResponse:
        category_label = cls._category_label(analysis.category)
        if analysis.scenario == ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION:
            questions = "\n".join(
                f"{index}. {question}"
                for index, question in enumerate(analysis.clarifying_questions, start=1)
            )
            text = (
                "Для первичной консультации нужно уточнить несколько обстоятельств.\n\n"
                f"{questions}\n\n"
                "После уточнения можно будет дать более точный справочный ответ."
            )
        elif analysis.scenario == ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST:
            text = (
                "Ситуация требует участия специалиста.\n\n"
                f"Причина: {analysis.short_reason}\n"
                "Подготовьте основные документы и краткую хронологию событий для дальнейшей работы."
            )
        elif analysis.scenario == ConsultationSession.AnalysisScenario.OUT_OF_SCOPE:
            text = (
                "Запрос выходит за рамки первичной юридической консультации.\n"
                "Модуль предназначен именно для первичных правовых вопросов.\n"
                "Если вопрос можно переформулировать в юридическом контексте, направьте его повторно."
            )
        else:
            text = (
                "Краткий вывод:\n"
                f"В демонстрационном режиме обращение по категории «{category_label}» обработано как типовое.\n\n"
                "Что важно учесть:\n"
                "- Для окончательных выводов важны фактические детали ситуации.\n"
                "- Автоматизированная консультация носит только первичный характер.\n\n"
                "Рекомендуемые действия:\n"
                "1. Сохраните документы и переписку по ситуации.\n"
                "2. Уточните даты, суммы и участников конфликта.\n"
                "3. При изменении обстоятельств задайте уточняющий вопрос.\n\n"
                "Что желательно уточнить дополнительно:\n"
                f"{'Уточнения уже были учтены в демонстрационном режиме.' if after_clarification else 'Дополнительные уточнения на текущем этапе не требуются.'}\n\n"
                "Ограничение консультации:\n"
                "Данный ответ носит справочный характер и не заменяет полноценную юридическую консультацию специалиста."
            )

        return LLMResponse(
            text=text,
            status="demo",
            model_name=settings.OLLAMA_MODEL,
        )

    @classmethod
    def generate_response_for_analysis(
        cls,
        session: ConsultationSession,
        analysis: ConsultationAnalysis,
        user_message: ChatMessage,
        *,
        after_clarification: bool = False,
    ) -> LLMResponse:
        if not settings.OLLAMA_ENABLED:
            return cls._demo_generate_response(
                analysis,
                user_message,
                after_clarification=after_clarification,
            )

        history = cls._format_conversation_history(
            cls._recent_session_messages(session, exclude_message_ids={user_message.pk})
        )
        prompt_key = RESPONSE_PROMPT_KEYS.get(
            analysis.scenario,
            "clarification",
        )
        if (
            analysis.scenario == ConsultationSession.AnalysisScenario.TYPICAL_ANSWER
            and after_clarification
        ):
            prompt_key = "after_clarification"

        cls._trace(
            "generation.request",
            session_id=session.pk,
            message_id=user_message.pk,
            scenario=analysis.scenario,
            prompt_key=prompt_key,
            category=analysis.category,
            after_clarification=after_clarification,
        )
        prompt = cls._render_prompt(
            PROMPTS[prompt_key],
            category=cls._category_label(analysis.category),
            missing_information=cls._format_prompt_list(analysis.missing_information),
            clarifying_questions=cls._format_prompt_list(
                analysis.clarifying_questions,
                numbered=True,
            ),
            short_reason=analysis.short_reason,
            conversation_history=history,
            user_message=user_message.content,
            clarification_answers=user_message.content,
        )
        response = cls._perform_ollama_chat(cls._build_single_prompt_messages(prompt))
        cls._trace(
            "generation.response",
            session_id=session.pk,
            message_id=user_message.pk,
            scenario=analysis.scenario,
            prompt_key=prompt_key,
            status=response.status,
            model=response.model_name,
            response_text=cls._preview_text(response.text),
            error_text=response.error_text,
        )
        return response

    @classmethod
    def process_user_message(
        cls,
        session: ConsultationSession,
        user_message: ChatMessage,
    ) -> ProcessedConsultationReply:
        was_awaiting_clarification = session.awaiting_clarification
        analysis, analysis_llm_response = cls._analyze_user_message_with_trace(
            session,
            user_message,
        )
        cls.apply_analysis_to_session(session, analysis)
        llm_response = cls.generate_response_for_analysis(
            session,
            analysis,
            user_message,
            after_clarification=was_awaiting_clarification
            and analysis.scenario == ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
        )
        return ProcessedConsultationReply(
            analysis=analysis,
            llm_response=llm_response,
            analysis_llm_response=analysis_llm_response,
        )

    @classmethod
    def generate_reply(cls, session: ConsultationSession) -> LLMResponse:
        if not settings.OLLAMA_ENABLED:
            latest = session.messages.order_by("-created_at").first()
            preview = latest.content[:250] if latest else ""
            demo_text = (
                "Демонстрационный ответ подсистемы.\n\n"
                "1. Запрос принят и сохранён в системе.\n"
                "2. Для получения реального ответа необходимо подключить Ollama.\n"
                "3. В текущем каркасе отрабатывается полный цикл: форма → сервер → БД → ответ.\n\n"
                f"Фрагмент последнего обращения: {preview}"
            )
            return LLMResponse(
                text=demo_text,
                status="demo",
                model_name=settings.OLLAMA_MODEL,
            )

        return cls._perform_ollama_chat(cls._build_messages(session))
