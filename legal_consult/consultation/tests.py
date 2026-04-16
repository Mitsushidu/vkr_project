from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ChatMessage, ConsultationSession
from .services import OllamaService


class ConsultationViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="demo", password="demo-pass")

    def test_requires_login(self):
        response = self.client.get(reverse("consultation:index"))
        self.assertEqual(response.status_code, 302)

    def test_session_page_works_for_authenticated_user(self):
        self.client.login(username="demo", password="demo-pass")
        session = ConsultationSession.objects.create(user=self.user, title="Тест")
        response = self.client.get(reverse("consultation:session_detail", kwargs={"pk": session.pk}))
        self.assertEqual(response.status_code, 200)

    def test_llm_memory_is_isolated_by_consultation_session(self):
        first_session = ConsultationSession.objects.create(user=self.user, title="Диалог 1")
        second_session = ConsultationSession.objects.create(user=self.user, title="Диалог 2")
        ChatMessage.objects.create(
            session=first_session,
            role=ChatMessage.Role.USER,
            content="Вопрос из первого диалога",
        )
        ChatMessage.objects.create(
            session=first_session,
            role=ChatMessage.Role.ASSISTANT,
            content="Ответ из первого диалога",
        )
        ChatMessage.objects.create(
            session=second_session,
            role=ChatMessage.Role.USER,
            content="Вопрос из второго диалога",
        )

        messages = OllamaService._build_messages(first_session)

        self.assertEqual(
            messages[1:],
            [
                {"role": "user", "content": "Вопрос из первого диалога"},
                {"role": "assistant", "content": "Ответ из первого диалога"},
            ],
        )

    def test_llm_memory_uses_recent_messages_from_current_dialog(self):
        session = ConsultationSession.objects.create(user=self.user, title="Диалог")
        for index in range(5):
            ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.USER if index % 2 == 0 else ChatMessage.Role.ASSISTANT,
                content=f"Сообщение {index}",
            )

        with self.settings(OLLAMA_SESSION_MEMORY_LIMIT=3):
            messages = OllamaService._build_messages(session)

        self.assertEqual(
            messages[1:],
            [
                {"role": "user", "content": "Сообщение 2"},
                {"role": "assistant", "content": "Сообщение 3"},
                {"role": "user", "content": "Сообщение 4"},
            ],
        )
