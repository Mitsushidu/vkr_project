from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, RedirectView

from .forms import (
    ChatMessageForm,
    ConsultationAssignmentForm,
    ConsultationCloseForm,
    ConsultationRequiresSpecialistForm,
    ConsultationStatusForm,
    DashboardFilterForm,
)
from .models import ChatMessage, ConsultationCategory, ConsultationSession, LLMInteractionLog
from .permissions import (
    ASSIGN_CONSULTATION_PERMISSION,
    CHANGE_CONSULTATION_STATUS_PERMISSION,
    CLOSE_CONSULTATION_PERMISSION,
    MARK_NEEDS_SPECIALIST_PERMISSION,
    VIEW_ALL_CONSULTATIONS_PERMISSION,
    get_visible_consultations_queryset,
)
from .services import OllamaService


def _build_staff_actions_context(user, session: ConsultationSession | None) -> dict:
    if session is None or not user.is_authenticated:
        return {
            "show_staff_actions": False,
            "can_assign_consultation": False,
            "can_change_consultation_status": False,
            "can_mark_needs_specialist": False,
            "can_close_consultation": False,
            "assignment_form": None,
            "status_form": None,
            "requires_specialist_form": None,
            "close_form": None,
        }

    can_assign = user.has_perm(ASSIGN_CONSULTATION_PERMISSION)
    can_change_status = user.has_perm(CHANGE_CONSULTATION_STATUS_PERMISSION)
    can_mark_specialist = user.has_perm(MARK_NEEDS_SPECIALIST_PERMISSION)
    can_close = user.has_perm(CLOSE_CONSULTATION_PERMISSION)

    return {
        "show_staff_actions": any((can_assign, can_change_status, can_mark_specialist, can_close)),
        "can_assign_consultation": can_assign,
        "can_change_consultation_status": can_change_status,
        "can_mark_needs_specialist": can_mark_specialist,
        "can_close_consultation": can_close,
        "assignment_form": ConsultationAssignmentForm(
            initial={"assigned_to": session.assigned_to_id, "category": session.category_id}
        )
        if can_assign
        else None,
        "status_form": ConsultationStatusForm(session=session) if can_change_status else None,
        "requires_specialist_form": ConsultationRequiresSpecialistForm(
            initial={"requires_specialist": "true" if session.requires_specialist else "false"}
        )
        if can_mark_specialist
        else None,
        "close_form": ConsultationCloseForm(session=session) if can_close else None,
    }


class ConsultationIndexView(LoginRequiredMixin, ListView):
    template_name = "consultation/chat.html"
    context_object_name = "sessions"

    def get_queryset(self):
        queryset = ConsultationSession.objects.select_related("category", "assigned_to", "user")
        return get_visible_consultations_queryset(self.request.user, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_session = self.get_queryset().first()
        context["current_session"] = current_session
        context["message_form"] = ChatMessageForm()
        context["categories"] = ConsultationCategory.objects.filter(is_active=True)
        context.update(_build_staff_actions_context(self.request.user, current_session))
        return context


class CreateSessionView(LoginRequiredMixin, RedirectView):
    pattern_name = "consultation:index"

    def get_redirect_url(self, *args, **kwargs):
        session = ConsultationSession.objects.create(user=self.request.user)
        messages.success(self.request, "Создан новый сеанс консультации.")
        return reverse_lazy("consultation:session_detail", kwargs={"pk": session.pk})


class SessionDetailView(LoginRequiredMixin, DetailView):
    model = ConsultationSession
    template_name = "consultation/chat.html"
    context_object_name = "current_session"

    def get_queryset(self):
        queryset = ConsultationSession.objects.select_related(
            "category", "assigned_to", "user"
        ).prefetch_related("messages")
        return get_visible_consultations_queryset(self.request.user, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_session = self.object
        sessions = get_visible_consultations_queryset(
            self.request.user,
            ConsultationSession.objects.select_related("category", "assigned_to", "user"),
        )
        context["sessions"] = sessions
        context["message_form"] = ChatMessageForm()
        context["categories"] = ConsultationCategory.objects.filter(is_active=True)
        context.update(_build_staff_actions_context(self.request.user, current_session))
        return context


class SessionListView(LoginRequiredMixin, ListView):
    template_name = "consultation/sessions.html"
    context_object_name = "sessions"

    def get_queryset(self):
        queryset = ConsultationSession.objects.select_related("category", "assigned_to", "user")
        return get_visible_consultations_queryset(self.request.user, queryset)


class AllSessionsView(PermissionRequiredMixin, ListView):
    permission_required = VIEW_ALL_CONSULTATIONS_PERMISSION
    template_name = "consultation/dashboard.html"
    context_object_name = "sessions"

    def get_queryset(self):
        queryset = ConsultationSession.objects.select_related("category", "assigned_to", "user")
        self.filter_form = DashboardFilterForm(self.request.GET or None)
        if self.filter_form.is_valid():
            status = self.filter_form.cleaned_data.get("status")
            category = self.filter_form.cleaned_data.get("category")
            assigned_to = self.filter_form.cleaned_data.get("assigned_to")
            if status:
                queryset = queryset.filter(status=status)
            if category:
                queryset = queryset.filter(category=category)
            if assigned_to:
                queryset = queryset.filter(assigned_to=assigned_to)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = getattr(self, "filter_form", DashboardFilterForm())
        context["can_mark_needs_specialist"] = self.request.user.has_perm(
            MARK_NEEDS_SPECIALIST_PERMISSION
        )
        context["can_close_consultation"] = self.request.user.has_perm(
            CLOSE_CONSULTATION_PERMISSION
        )
        return context


def _get_visible_session_for_action(request, pk: int) -> ConsultationSession:
    queryset = ConsultationSession.objects.select_related("category", "assigned_to", "user")
    return get_object_or_404(get_visible_consultations_queryset(request.user, queryset), pk=pk)


def _redirect_to_session(session: ConsultationSession):
    return redirect("consultation:session_detail", pk=session.pk)


@require_POST
def assign_consultation(request, pk: int):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.has_perm(ASSIGN_CONSULTATION_PERMISSION):
        raise PermissionDenied

    session = _get_visible_session_for_action(request, pk)
    form = ConsultationAssignmentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Не удалось обновить исполнителя или категорию обращения.")
        return _redirect_to_session(session)

    session.assigned_to = form.cleaned_data["assigned_to"]
    session.category = form.cleaned_data["category"]
    session.save(update_fields=["assigned_to", "category", "updated_at"])
    messages.success(request, "Исполнитель и категория обращения обновлены.")
    return _redirect_to_session(session)


@require_POST
def change_consultation_status(request, pk: int):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.has_perm(CHANGE_CONSULTATION_STATUS_PERMISSION):
        raise PermissionDenied

    session = _get_visible_session_for_action(request, pk)
    form = ConsultationStatusForm(request.POST, session=session)
    if not form.is_valid():
        messages.error(request, "Недопустимый переход статуса обращения.")
        return _redirect_to_session(session)

    session.status = form.cleaned_data["status"]
    if session.status == ConsultationSession.Status.NEEDS_SPECIALIST:
        session.requires_specialist = True
        session.save(update_fields=["status", "requires_specialist", "updated_at"])
    else:
        session.save(update_fields=["status", "updated_at"])
    messages.success(request, "Статус обращения обновлён.")
    return _redirect_to_session(session)


@require_POST
def mark_consultation_requires_specialist(request, pk: int):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.has_perm(MARK_NEEDS_SPECIALIST_PERMISSION):
        raise PermissionDenied

    session = _get_visible_session_for_action(request, pk)
    form = ConsultationRequiresSpecialistForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Не удалось обновить признак привлечения специалиста.")
        return _redirect_to_session(session)

    session.requires_specialist = form.cleaned_data["requires_specialist"]
    session.save(update_fields=["requires_specialist", "updated_at"])
    messages.success(request, "Признак привлечения специалиста обновлён.")
    return _redirect_to_session(session)


@require_POST
def close_consultation(request, pk: int):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.has_perm(CLOSE_CONSULTATION_PERMISSION):
        raise PermissionDenied

    session = _get_visible_session_for_action(request, pk)
    form = ConsultationCloseForm(request.POST, session=session)
    if not form.is_valid():
        messages.error(request, "Закрытие обращения недоступно в текущем статусе.")
        return _redirect_to_session(session)

    session.status = ConsultationSession.Status.CLOSED
    session.save(update_fields=["status", "updated_at"])
    messages.success(request, "Обращение закрыто.")
    return _redirect_to_session(session)


@require_POST
def send_message_api(request, pk: int):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется авторизация."}, status=401)

    session_queryset = ConsultationSession.objects.select_related("user")
    session = get_object_or_404(
        get_visible_consultations_queryset(request.user, session_queryset),
        pk=pk,
    )
    form = ChatMessageForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    content = form.cleaned_data["content"]
    user_message = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=content,
    )
    session.update_title_from_message(content)
    if session.status == ConsultationSession.Status.NEW:
        session.status = ConsultationSession.Status.IN_PROGRESS
        session.save(update_fields=["status", "updated_at"])

    llm_response = OllamaService.generate_reply(session)
    assistant_message = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.ASSISTANT,
        content=llm_response.text,
        is_error=llm_response.status == "error",
    )

    LLMInteractionLog.objects.create(
        session=session,
        request_message=user_message,
        response_message=assistant_message,
        model_name=llm_response.model_name,
        status=llm_response.status,
        total_duration_ms=llm_response.total_duration_ms,
        prompt_tokens=llm_response.prompt_tokens,
        completion_tokens=llm_response.completion_tokens,
        error_text=llm_response.error_text,
    )

    return JsonResponse(
        {
            "assistant_message": {
                "id": assistant_message.pk,
                "content": assistant_message.content,
                "created_at": assistant_message.created_at.strftime("%d.%m.%Y %H:%M"),
                "is_error": assistant_message.is_error,
            },
            "session": {
                "id": session.pk,
                "title": session.title,
                "status": session.get_status_display(),
            },
        }
    )
