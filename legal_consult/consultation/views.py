from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, RedirectView

from .forms import ChatMessageForm
from .models import ChatMessage, ConsultationCategory, ConsultationSession, LLMInteractionLog
from .services import OllamaService


class ConsultationIndexView(LoginRequiredMixin, ListView):
    template_name = "consultation/chat.html"
    context_object_name = "sessions"

    def get_queryset(self):
        return ConsultationSession.objects.filter(user=self.request.user).select_related(
            "category", "assigned_to"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_session = self.get_queryset().first()
        context["current_session"] = current_session
        context["message_form"] = ChatMessageForm()
        context["categories"] = ConsultationCategory.objects.filter(is_active=True)
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
        if self.request.user.has_perm("consultation.can_review_consultations"):
            return queryset
        return queryset.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.has_perm("consultation.can_review_consultations"):
            sessions = ConsultationSession.objects.select_related("category", "assigned_to", "user")
        else:
            sessions = ConsultationSession.objects.filter(user=self.request.user).select_related(
                "category", "assigned_to"
            )
        context["sessions"] = sessions
        context["message_form"] = ChatMessageForm()
        context["categories"] = ConsultationCategory.objects.filter(is_active=True)
        return context


class SessionListView(LoginRequiredMixin, ListView):
    template_name = "consultation/sessions.html"
    context_object_name = "sessions"

    def get_queryset(self):
        queryset = ConsultationSession.objects.select_related("category", "assigned_to", "user")
        if self.request.user.has_perm("consultation.can_review_consultations"):
            return queryset
        return queryset.filter(user=self.request.user)


class AllSessionsView(PermissionRequiredMixin, ListView):
    permission_required = "consultation.can_review_consultations"
    template_name = "consultation/dashboard.html"
    context_object_name = "sessions"

    def get_queryset(self):
        return ConsultationSession.objects.select_related("category", "assigned_to", "user")


@require_POST
def send_message_api(request, pk: int):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется авторизация."}, status=401)

    session_queryset = ConsultationSession.objects.select_related("user")
    if not request.user.has_perm("consultation.can_review_consultations"):
        session_queryset = session_queryset.filter(user=request.user)

    session = get_object_or_404(session_queryset, pk=pk)
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
