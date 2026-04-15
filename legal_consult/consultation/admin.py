from django.contrib import admin

from .models import ChatMessage, ConsultationCategory, ConsultationSession, LLMInteractionLog


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "created_at", "is_error")


@admin.register(ConsultationCategory)
class ConsultationCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ConsultationSession)
class ConsultationSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "status", "category", "assigned_to", "updated_at")
    list_filter = ("status", "category", "requires_specialist")
    search_fields = ("title", "user__username", "user__email")
    autocomplete_fields = ("user", "assigned_to", "category")
    inlines = [ChatMessageInline]


@admin.register(LLMInteractionLog)
class LLMInteractionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "model_name", "status", "total_duration_ms", "created_at")
    list_filter = ("status", "model_name")
    search_fields = ("session__title", "error_text")
