from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q

from user.roles import ROLE_ADMIN, ROLE_HEAD, ROLE_LAWYER, ROLE_SUPPORT

from .models import ConsultationCategory, ConsultationSession


User = get_user_model()

EMPLOYEE_ROLE_NAMES = (
    ROLE_SUPPORT,
    ROLE_LAWYER,
    ROLE_HEAD,
    ROLE_ADMIN,
)

STATUS_TRANSITIONS = {
    ConsultationSession.Status.NEW: (
        ConsultationSession.Status.IN_PROGRESS,
        ConsultationSession.Status.NEEDS_SPECIALIST,
    ),
    ConsultationSession.Status.IN_PROGRESS: (
        ConsultationSession.Status.NEEDS_SPECIALIST,
        ConsultationSession.Status.COMPLETED,
    ),
    ConsultationSession.Status.NEEDS_SPECIALIST: (
        ConsultationSession.Status.IN_PROGRESS,
        ConsultationSession.Status.COMPLETED,
    ),
    ConsultationSession.Status.COMPLETED: (),
    ConsultationSession.Status.CLOSED: (),
}


class ChatMessageForm(forms.Form):
    content = forms.CharField(
        label="Сообщение",
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Опишите правовую ситуацию или задайте вопрос...",
                "class": "chat-textarea",
            }
        ),
    )


class ConsultationAssignmentForm(forms.Form):
    assigned_to = forms.ModelChoiceField(
        label="Исполнитель",
        queryset=User.objects.none(),
        required=False,
    )
    category = forms.ModelChoiceField(
        label="Категория",
        queryset=ConsultationCategory.objects.none(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = (
            User.objects.filter(Q(groups__name__in=EMPLOYEE_ROLE_NAMES) | Q(is_superuser=True))
            .distinct()
            .order_by("username")
        )
        self.fields["category"].queryset = ConsultationCategory.objects.order_by("name")


class ConsultationStatusForm(forms.Form):
    status = forms.ChoiceField(label="Статус", choices=())

    def __init__(self, *args, session: ConsultationSession, **kwargs):
        self.session = session
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (status, ConsultationSession.Status(status).label)
            for status in STATUS_TRANSITIONS.get(session.status, ())
        ]

    def clean_status(self):
        status = self.cleaned_data["status"]
        if status not in STATUS_TRANSITIONS.get(self.session.status, ()):
            raise ValidationError("Недопустимый переход статуса.")
        return status


class ConsultationRequiresSpecialistForm(forms.Form):
    requires_specialist = forms.TypedChoiceField(
        label="Требуется специалист",
        choices=(("true", "Да"), ("false", "Нет")),
        coerce=lambda value: str(value).lower() == "true",
    )


class ConsultationCloseForm(forms.Form):
    def __init__(self, *args, session: ConsultationSession, **kwargs):
        self.session = session
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.session.status != ConsultationSession.Status.COMPLETED:
            raise ValidationError("Закрыть можно только завершённое обращение.")
        if self.session.status == ConsultationSession.Status.CLOSED:
            raise ValidationError("Обращение уже закрыто.")
        return cleaned_data
