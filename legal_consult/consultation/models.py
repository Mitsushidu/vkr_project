from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import Truncator


class ConsultationCategory(models.Model):
    name = models.CharField("Название", max_length=150, unique=True)
    slug = models.SlugField("Код", max_length=160, unique=True)
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Категория обращения"
        verbose_name_plural = "Категории обращений"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ConsultationSession(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новое"
        IN_PROGRESS = "in_progress", "В обработке"
        NEEDS_SPECIALIST = "needs_specialist", "Требует специалиста"
        COMPLETED = "completed", "Завершено"
        CLOSED = "closed", "Закрыто"

    class AnalysisScenario(models.TextChoices):
        TYPICAL_ANSWER = "typical_answer", "Типовой ответ"
        NEEDS_CLARIFICATION = "needs_clarification", "Требуется уточнение"
        NEEDS_SPECIALIST = "needs_specialist", "Передача специалисту"
        OUT_OF_SCOPE = "out_of_scope", "Вне рамок консультации"
        INSUFFICIENT_CONFIDENCE = "insufficient_confidence", "Недостаточная уверенность"

    class AnalysisCategory(models.TextChoices):
        FAMILY = "family", "Семейное право"
        LABOR = "labor", "Трудовое право"
        HOUSING = "housing", "Жилищное право"
        CONSUMER = "consumer", "Защита прав потребителей"
        INHERITANCE = "inheritance", "Наследственное право"
        ADMINISTRATIVE = "administrative", "Административные вопросы"
        CIVIL = "civil", "Гражданские вопросы"
        OTHER = "other", "Иное"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="consultation_sessions",
        verbose_name="Пользователь",
    )
    category = models.ForeignKey(
        ConsultationCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
        verbose_name="Категория",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_consultation_sessions",
        verbose_name="Назначенный специалист",
    )
    title = models.CharField("Заголовок", max_length=255, blank=True)
    status = models.CharField(
        "Статус",
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
    )
    requires_specialist = models.BooleanField("Требуется специалист", default=False)
    last_analysis_scenario = models.CharField(
        "Последний сценарий анализа",
        max_length=32,
        choices=AnalysisScenario.choices,
        blank=True,
    )
    last_analysis_category = models.CharField(
        "Последняя определённая категория",
        max_length=32,
        choices=AnalysisCategory.choices,
        blank=True,
    )
    awaiting_clarification = models.BooleanField("Ожидается уточнение", default=False)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Сеанс консультации"
        verbose_name_plural = "Сеансы консультаций"
        ordering = ("-updated_at",)
        permissions = [
            ("can_view_all_consultations", "Может просматривать все обращения"),
            ("can_assign_consultation", "Может назначать обращения исполнителю"),
            ("can_change_consultation_status", "Может изменять статус обращения"),
            ("can_mark_needs_specialist", "Может помечать обращение как требующее специалиста"),
            ("can_close_consultation", "Может закрывать обращения"),
            ("can_review_llm_logs", "Может просматривать журналы взаимодействий с LLM"),
        ]

    def __str__(self) -> str:
        return self.title or f"Консультация #{self.pk}"

    def get_absolute_url(self):
        return reverse("consultation:session_detail", kwargs={"pk": self.pk})

    def update_title_from_message(self, message_text: str) -> None:
        if not self.title:
            self.title = Truncator(message_text).chars(80)
            self.save(update_fields=["title", "updated_at"])


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        SYSTEM = "system", "Система"
        USER = "user", "Пользователь"
        ASSISTANT = "assistant", "Ассистент"

    session = models.ForeignKey(
        ConsultationSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Сеанс",
    )
    role = models.CharField("Роль", max_length=16, choices=Role.choices)
    content = models.TextField("Содержание")
    is_error = models.BooleanField("Ошибка генерации", default=False)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Сообщение чата"
        verbose_name_plural = "Сообщения чата"
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.get_role_display()}: {Truncator(self.content).chars(50)}"


class LLMInteractionLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Успешно"
        ERROR = "error", "Ошибка"
        DEMO = "demo", "Демо-режим"

    session = models.ForeignKey(
        ConsultationSession,
        on_delete=models.CASCADE,
        related_name="llm_logs",
        verbose_name="Сеанс",
    )
    request_message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
        verbose_name="Входное сообщение",
    )
    response_message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="response_logs",
        verbose_name="Выходное сообщение",
    )
    model_name = models.CharField("Модель", max_length=100)
    status = models.CharField("Статус", max_length=16, choices=Status.choices)
    total_duration_ms = models.PositiveIntegerField("Длительность, мс", null=True, blank=True)
    prompt_tokens = models.PositiveIntegerField("Prompt token count", null=True, blank=True)
    completion_tokens = models.PositiveIntegerField("Completion token count", null=True, blank=True)
    error_text = models.TextField("Текст ошибки", blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Журнал вызова LLM"
        verbose_name_plural = "Журнал вызовов LLM"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.model_name} — {self.get_status_display()}"
