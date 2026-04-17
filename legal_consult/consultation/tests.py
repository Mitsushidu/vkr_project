from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
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


class ConsultationPermissionsTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="owner", password="owner-pass")
        self.other_user = get_user_model().objects.create_user(
            username="other-user",
            password="other-pass",
        )
        self.lawyer = get_user_model().objects.create_user(username="lawyer", password="lawyer-pass")
        self.supervisor = get_user_model().objects.create_user(
            username="supervisor",
            password="supervisor-pass",
        )
        self.assigned_peer = get_user_model().objects.create_user(
            username="assigned-peer",
            password="peer-pass",
        )

        self.owner_session = ConsultationSession.objects.create(
            user=self.owner,
            title="Сессия владельца",
        )
        self.available_session = ConsultationSession.objects.create(
            user=self.other_user,
            title="Свободная сессия",
        )
        self.assigned_session = ConsultationSession.objects.create(
            user=self.other_user,
            assigned_to=self.lawyer,
            title="Назначенная юристу",
        )
        self.foreign_assigned_session = ConsultationSession.objects.create(
            user=self.other_user,
            assigned_to=self.assigned_peer,
            title="Назначенная другому специалисту",
        )

    def test_custom_permissions_are_created(self):
        for codename in [
            "can_view_all_consultations",
            "can_assign_consultation",
            "can_change_consultation_status",
            "can_mark_needs_specialist",
            "can_close_consultation",
            "can_review_llm_logs",
        ]:
            self.assertTrue(
                Permission.objects.filter(
                    content_type__app_label="consultation",
                    codename=codename,
                ).exists()
            )

    def test_dashboard_uses_new_view_all_permission(self):
        self.client.login(username="supervisor", password="supervisor-pass")
        self.supervisor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="consultation",
                codename="can_view_all_consultations",
            )
        )

        response = self.client.get(reverse("consultation:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sessions"].count(), 4)

    def test_dashboard_rejects_generic_view_permission_without_new_permission(self):
        self.client.login(username="supervisor", password="supervisor-pass")
        self.supervisor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="consultation",
                codename="view_consultationsession",
            )
        )

        response = self.client.get(reverse("consultation:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_lawyer_can_view_assigned_and_available_sessions_only(self):
        self.client.login(username="lawyer", password="lawyer-pass")
        self.lawyer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="consultation",
                codename="can_change_consultation_status",
            ),
            Permission.objects.get(
                content_type__app_label="consultation",
                codename="can_close_consultation",
            ),
        )

        response = self.client.get(reverse("consultation:session_list"))

        self.assertEqual(response.status_code, 200)
        visible_sessions = list(response.context["sessions"])
        self.assertIn(self.assigned_session, visible_sessions)
        self.assertIn(self.available_session, visible_sessions)
        self.assertIn(self.owner_session, visible_sessions)
        self.assertNotIn(self.foreign_assigned_session, visible_sessions)

    def test_regular_user_can_view_only_own_sessions(self):
        self.client.login(username="owner", password="owner-pass")

        response = self.client.get(reverse("consultation:session_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["sessions"]), [self.owner_session])
