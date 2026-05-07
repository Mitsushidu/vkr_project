from django.db import models
from django.utils.text import Truncator


class LegalDocument(models.Model):
    source_uid = models.CharField("Идентификатор источника", max_length=255, blank=True, db_index=True)
    title = models.CharField("Название", max_length=500)
    document_type = models.CharField("Тип документа", max_length=255, blank=True)
    issuer = models.CharField("Издатель", max_length=255, blank=True)
    document_number = models.CharField("Номер документа", max_length=100, blank=True)
    doc_date = models.DateField("Дата документа", null=True, blank=True)
    status = models.CharField("Статус", max_length=255, blank=True)
    keywords = models.TextField("Ключевые слова", blank=True)
    classifier = models.TextField("Классификатор", blank=True)
    raw_text = models.TextField("Исходный текст", blank=True)
    source_name = models.CharField("Источник", max_length=100, default="RusLawOD")
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Нормативный документ"
        verbose_name_plural = "Нормативные документы"
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class LegalFragment(models.Model):
    document = models.ForeignKey(
        LegalDocument,
        related_name="fragments",
        on_delete=models.CASCADE,
        verbose_name="Документ",
    )
    fragment_type = models.CharField("Тип фрагмента", max_length=50, default="plain_text")
    fragment_order = models.PositiveIntegerField("Порядок фрагмента", default=0)
    article_number = models.CharField("Номер статьи", max_length=100, blank=True)
    heading = models.CharField("Заголовок", max_length=500, blank=True)
    text = models.TextField("Текст")
    category_hint = models.CharField("Подсказка категории", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Фрагмент нормативного документа"
        verbose_name_plural = "Фрагменты нормативных документов"
        ordering = ("document_id", "fragment_order", "id")

    def __str__(self) -> str:
        label = self.heading or self.article_number or Truncator(self.text).chars(80)
        return f"{self.document}: {label}"


class ConsultationSource(models.Model):
    session = models.ForeignKey(
        "consultation.ConsultationSession",
        related_name="legal_sources",
        on_delete=models.CASCADE,
        verbose_name="Сеанс консультации",
    )
    request_message = models.ForeignKey(
        "consultation.ChatMessage",
        related_name="legal_sources_as_request",
        on_delete=models.CASCADE,
        verbose_name="Сообщение-запрос",
    )
    response_message = models.ForeignKey(
        "consultation.ChatMessage",
        related_name="legal_sources_as_response",
        on_delete=models.CASCADE,
        verbose_name="Сообщение-ответ",
    )
    fragment = models.ForeignKey(
        LegalFragment,
        related_name="consultation_sources",
        on_delete=models.CASCADE,
        verbose_name="Фрагмент",
    )
    rank = models.PositiveIntegerField("Ранг", default=1)
    score = models.FloatField("Оценка", default=0)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Источник консультации"
        verbose_name_plural = "Источники консультаций"
        ordering = ("session_id", "rank", "id")

    def __str__(self) -> str:
        return f"{self.session} — источник #{self.rank}"
