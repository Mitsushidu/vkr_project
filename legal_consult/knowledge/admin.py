from django.contrib import admin

from .models import ConsultationSource, LegalDocument, LegalFragment


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "document_type", "source_name", "is_active", "updated_at")
    list_filter = ("is_active", "document_type", "source_name")
    search_fields = ("title", "source_uid", "document_type")


@admin.register(LegalFragment)
class LegalFragmentAdmin(admin.ModelAdmin):
    list_display = ("document", "fragment_type", "article_number", "heading", "is_active")
    list_filter = ("is_active", "fragment_type", "category_hint")
    search_fields = ("heading", "text", "article_number")
    autocomplete_fields = ("document",)


@admin.register(ConsultationSource)
class ConsultationSourceAdmin(admin.ModelAdmin):
    list_display = ("session", "fragment", "rank", "score", "created_at")
    readonly_fields = (
        "created_at",
        "session",
        "request_message",
        "response_message",
        "fragment",
        "rank",
        "score",
    )
