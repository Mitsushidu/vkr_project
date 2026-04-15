from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsultationCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True, verbose_name="Название")),
                ("slug", models.SlugField(max_length=160, unique=True, verbose_name="Код")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
            ],
            options={
                "verbose_name": "Категория обращения",
                "verbose_name_plural": "Категории обращений",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="ConsultationSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=255, verbose_name="Заголовок")),
                ("status", models.CharField(choices=[("new", "Новое"), ("in_progress", "В обработке"), ("needs_specialist", "Требует специалиста"), ("completed", "Завершено"), ("closed", "Закрыто")], default="new", max_length=32, verbose_name="Статус")),
                ("requires_specialist", models.BooleanField(default=False, verbose_name="Требуется специалист")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_consultation_sessions", to=settings.AUTH_USER_MODEL, verbose_name="Назначенный специалист")),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sessions", to="consultation.consultationcategory", verbose_name="Категория")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="consultation_sessions", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Сеанс консультации",
                "verbose_name_plural": "Сеансы консультаций",
                "ordering": ("-updated_at",),
                "permissions": [("can_route_consultations", "Может маршрутизировать обращения"), ("can_review_consultations", "Может просматривать все обращения")],
            },
        ),
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("system", "Система"), ("user", "Пользователь"), ("assistant", "Ассистент")], max_length=16, verbose_name="Роль")),
                ("content", models.TextField(verbose_name="Содержание")),
                ("is_error", models.BooleanField(default=False, verbose_name="Ошибка генерации")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="consultation.consultationsession", verbose_name="Сеанс")),
            ],
            options={
                "verbose_name": "Сообщение чата",
                "verbose_name_plural": "Сообщения чата",
                "ordering": ("created_at",),
            },
        ),
        migrations.CreateModel(
            name="LLMInteractionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_name", models.CharField(max_length=100, verbose_name="Модель")),
                ("status", models.CharField(choices=[("success", "Успешно"), ("error", "Ошибка"), ("demo", "Демо-режим")], max_length=16, verbose_name="Статус")),
                ("total_duration_ms", models.PositiveIntegerField(blank=True, null=True, verbose_name="Длительность, мс")),
                ("prompt_tokens", models.PositiveIntegerField(blank=True, null=True, verbose_name="Prompt token count")),
                ("completion_tokens", models.PositiveIntegerField(blank=True, null=True, verbose_name="Completion token count")),
                ("error_text", models.TextField(blank=True, verbose_name="Текст ошибки")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("request_message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="request_logs", to="consultation.chatmessage", verbose_name="Входное сообщение")),
                ("response_message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="response_logs", to="consultation.chatmessage", verbose_name="Выходное сообщение")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="llm_logs", to="consultation.consultationsession", verbose_name="Сеанс")),
            ],
            options={
                "verbose_name": "Журнал вызова LLM",
                "verbose_name_plural": "Журнал вызовов LLM",
                "ordering": ("-created_at",),
            },
        ),
    ]
