from django.db.models import Q, QuerySet

from .models import ConsultationSession


VIEW_ALL_CONSULTATIONS_PERMISSION = "consultation.can_view_all_consultations"
ASSIGN_CONSULTATION_PERMISSION = "consultation.can_assign_consultation"
CHANGE_CONSULTATION_STATUS_PERMISSION = "consultation.can_change_consultation_status"
MARK_NEEDS_SPECIALIST_PERMISSION = "consultation.can_mark_needs_specialist"
CLOSE_CONSULTATION_PERMISSION = "consultation.can_close_consultation"
REVIEW_LLM_LOGS_PERMISSION = "consultation.can_review_llm_logs"

SPECIALIST_WORK_PERMISSIONS = (
    CHANGE_CONSULTATION_STATUS_PERMISSION,
    MARK_NEEDS_SPECIALIST_PERMISSION,
    CLOSE_CONSULTATION_PERMISSION,
)


def user_can_view_all_consultations(user) -> bool:
    return user.is_authenticated and (
        user.is_superuser or user.has_perm(VIEW_ALL_CONSULTATIONS_PERMISSION)
    )


def get_visible_consultations_queryset(
    user,
    queryset: QuerySet | None = None,
) -> QuerySet:
    if queryset is None:
        queryset = ConsultationSession.objects.all()

    if not user.is_authenticated:
        return queryset.none()

    if user_can_view_all_consultations(user):
        return queryset

    if user.has_perm("consultation.can_change_consultation_status") or user.has_perm("consultation.can_close_consultation"):
        return queryset.filter(Q(user=user) | Q(assigned_to=user)).distinct()

    return queryset.filter(user=user)
