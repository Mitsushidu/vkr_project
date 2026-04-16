from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .models import ChatMessage, ConsultationSession


@dataclass
class LLMResponse:
    text: str
    status: str
    model_name: str
    total_duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_text: str = ""


class OllamaService:
    @staticmethod
    def _recent_session_messages(session: ConsultationSession) -> list[dict[str, str]]:
        queryset = session.messages.filter(
            is_error=False,
            role__in=(ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT),
        )
        limit = settings.OLLAMA_SESSION_MEMORY_LIMIT

        if limit > 0:
            history = list(
                queryset.order_by("-created_at", "-pk").values("role", "content")[:limit]
            )
            history.reverse()
            return history

        return list(queryset.order_by("created_at", "pk").values("role", "content"))

    @classmethod
    def _build_messages(cls, session: ConsultationSession) -> list[dict[str, str]]:
        history = cls._recent_session_messages(session)
        return [
            {"role": "system", "content": settings.CONSULTATION_SYSTEM_PROMPT},
            *history,
        ]

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

        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": cls._build_messages(session),
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
        total_duration_ms = int(total_duration / 1_000_000) if isinstance(total_duration, int) else None

        return LLMResponse(
            text=text,
            status="success",
            model_name=data.get("model", settings.OLLAMA_MODEL),
            total_duration_ms=total_duration_ms,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
