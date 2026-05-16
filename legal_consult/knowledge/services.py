from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import Q

from .models import ConsultationSource, LegalFragment


STOP_WORDS = {
    "если",
    "или",
    "для",
    "при",
    "что",
    "это",
    "как",
    "где",
    "когда",
    "какой",
    "какая",
    "какие",
    "можно",
    "нужно",
    "надо",
    "будет",
    "после",
    "меня",
    "мне",
    "мой",
    "моя",
    "моё",
    "уже",
    "есть",
    "без",
    "под",
    "над",
}

SOURCE_TEXT_LIMIT = 800
CANDIDATE_LIMIT = 300


@dataclass
class SearchResult:
    fragment: LegalFragment
    score: float


class LegalRetrievalService:
    FIELD_WEIGHTS = (
        ("article_number", 5),
        ("heading", 4),
        ("document_title", 3),
        ("document_keywords", 3),
        ("category_hint", 2),
        ("text", 1),
    )

    @classmethod
    def search(cls, query_text, category=None, limit=5) -> list[SearchResult]:
        tokens = cls._extract_tokens(f"{query_text or ''} {category or ''}")
        if not tokens:
            return []

        queryset = (
            LegalFragment.objects.select_related("document")
            .filter(is_active=True, document__is_active=True)
            .order_by("document_id", "fragment_order", "id")
        )
        prefilter = Q()
        for token in tokens:
            prefilter |= Q(text__icontains=token)
            prefilter |= Q(heading__icontains=token)
            prefilter |= Q(article_number__icontains=token)
            prefilter |= Q(category_hint__icontains=token)
            prefilter |= Q(document__title__icontains=token)
            prefilter |= Q(document__keywords__icontains=token)

        queryset = queryset.filter(prefilter)[:CANDIDATE_LIMIT]
        results: list[SearchResult] = []
        for fragment in queryset:
            score = cls._score_fragment(fragment, tokens)
            if score > 0:
                results.append(SearchResult(fragment=fragment, score=float(score)))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    @classmethod
    def format_sources_for_prompt(cls, results: list[SearchResult]) -> str:
        if not results:
            return ""

        blocks = ["Релевантные нормативные источники из базы:"]
        for index, result in enumerate(results, start=1):
            fragment = result.fragment
            document = fragment.document
            article = fragment.article_number or "не указана"
            heading = fragment.heading or "без заголовка"
            text = cls._trim_text(fragment.text)
            blocks.append(
                "\n".join(
                    [
                        f"{index}. Документ: {document.title}",
                        f"Статья: {article}",
                        f"Заголовок: {heading}",
                        f"Фрагмент: {text}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    @classmethod
    def _score_fragment(cls, fragment: LegalFragment, tokens: set[str]) -> int:
        document = fragment.document
        fields = {
            "article_number": cls._normalize(fragment.article_number),
            "heading": cls._normalize(fragment.heading),
            "document_title": cls._normalize(document.title),
            "document_keywords": cls._normalize(document.keywords),
            "category_hint": cls._normalize(fragment.category_hint),
            "text": cls._normalize(fragment.text),
        }
        score = 0
        for field_name, weight in cls.FIELD_WEIGHTS:
            field_text = fields[field_name]
            for token in tokens:
                if token in field_text:
                    score += weight
        return score

    @classmethod
    def _extract_tokens(cls, text: str) -> set[str]:
        normalized = cls._normalize(text)
        return {
            token
            for token in re.findall(r"[a-zа-яё0-9]+", normalized)
            if (token.isdigit() or len(token) > 3) and token not in STOP_WORDS
        }

    @staticmethod
    def _normalize(text) -> str:
        return " ".join(str(text or "").lower().replace("ё", "е").split())

    @staticmethod
    def _trim_text(text: str) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= SOURCE_TEXT_LIMIT:
            return normalized
        return f"{normalized[:SOURCE_TEXT_LIMIT]}..."

    @staticmethod
    def make_preview(text: str, limit: int = 300) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."


class ConsultationSourceService:
    @staticmethod
    def save_sources(session, request_message, response_message, legal_results):
        if not legal_results or response_message.is_error:
            return []

        sources = []
        for rank, result in enumerate(legal_results, start=1):
            sources.append(
                ConsultationSource.objects.create(
                    session=session,
                    request_message=request_message,
                    response_message=response_message,
                    fragment=result.fragment,
                    rank=rank,
                    score=result.score,
                )
            )
        return sources

    @staticmethod
    def serialize_source(source: ConsultationSource) -> dict:
        fragment = source.fragment
        document = fragment.document
        return {
            "rank": source.rank,
            "score": source.score,
            "document_title": document.title,
            "article_number": fragment.article_number,
            "heading": fragment.heading,
            "text": LegalRetrievalService._trim_text(fragment.text),
            "preview": LegalRetrievalService.make_preview(fragment.text),
        }
