from django.contrib import admin

from .models import ChatMessage, ConsultationCategory, ConsultationSession, LLMInteractionLog


REVIEW_LLM_LOGS_PERMISSION = "consultation.can_review_llm_logs"
ASSIGN_CONSULTATION_PERMISSION = "consultation.can_assign_consultation"
CHANGE_CONSULTATION_STATUS_PERMISSION = "consultation.can_change_consultation_status"
MARK_NEEDS_SPECIALIST_PERMISSION = "consultation.can_mark_needs_specialist"
CLOSE_CONSULTATION_PERMISSION = "consultation.can_close_consultation"


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

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if not request.user.has_perm(ASSIGN_CONSULTATION_PERMISSION):
            readonly_fields.append("assigned_to")
        if not request.user.has_perm(CHANGE_CONSULTATION_STATUS_PERMISSION):
            readonly_fields.append("status")
        if not request.user.has_perm(MARK_NEEDS_SPECIALIST_PERMISSION):
            readonly_fields.append("requires_specialist")
        return readonly_fields

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "status" in form.base_fields and not request.user.has_perm(CLOSE_CONSULTATION_PERMISSION):
            form.base_fields["status"].choices = [
                choice
                for choice in form.base_fields["status"].choices
                if choice[0] != ConsultationSession.Status.CLOSED
            ]
        return form


@admin.register(LLMInteractionLog)
class LLMInteractionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "model_name", "status", "total_duration_ms", "created_at")
    list_filter = ("status", "model_name")
    search_fields = ("session__title", "error_text")

    def has_module_permission(self, request):
        return super().has_module_permission(request) or request.user.has_perm(
            REVIEW_LLM_LOGS_PERMISSION
        )

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or request.user.has_perm(
            REVIEW_LLM_LOGS_PERMISSION
        )

    def get_model_perms(self, request):
        permissions = super().get_model_perms(request)
        if request.user.has_perm(REVIEW_LLM_LOGS_PERMISSION):
            permissions["view"] = True
        return permissions
