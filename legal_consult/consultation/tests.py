from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import ChatMessage, ConsultationCategory, ConsultationSession, LLMInteractionLog
from .services import ConsultationAnalysis, LLMResponse, OllamaService, ProcessedConsultationReply
from user.roles import ROLE_HEAD, ROLE_LAWYER, ROLE_SUPPORT, assign_primary_role


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
        call_command("init_roles")
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
        self.support = get_user_model().objects.create_user(
            username="support",
            password="support-pass",
        )
        self.assigned_peer = get_user_model().objects.create_user(
            username="assigned-peer",
            password="peer-pass",
        )
        self.category = ConsultationCategory.objects.create(
            name="Семейное право",
            slug="family-law",
        )

        self.owner_session = ConsultationSession.objects.create(
            user=self.owner,
            title="Сессия владельца",
            category=self.category,
        )
        self.available_session = ConsultationSession.objects.create(
            user=self.other_user,
            title="Свободная сессия",
            category=self.category,
        )
        self.assigned_session = ConsultationSession.objects.create(
            user=self.other_user,
            assigned_to=self.lawyer,
            title="Назначенная юристу",
            category=self.category,
        )
        self.foreign_assigned_session = ConsultationSession.objects.create(
            user=self.other_user,
            assigned_to=self.assigned_peer,
            title="Назначенная другому специалисту",
            category=self.category,
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
        assign_primary_role(self.supervisor, ROLE_HEAD)

        response = self.client.get(reverse("consultation:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sessions"].count(), 4)
        self.assertTrue(self.supervisor.has_perm("consultation.can_view_all_consultations"))
        self.assertEqual(self.supervisor.user_permissions.count(), 0)

    def test_dashboard_rejects_generic_view_permission_without_new_permission(self):
        self.client.login(username="supervisor", password="supervisor-pass")

        response = self.client.get(reverse("consultation:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_lawyer_can_view_assigned_sessions_via_group_permissions(self):
        self.client.login(username="lawyer", password="lawyer-pass")
        assign_primary_role(self.lawyer, ROLE_LAWYER)

        response = self.client.get(reverse("consultation:session_list"))

        self.assertEqual(response.status_code, 200)
        visible_sessions = list(response.context["sessions"])
        self.assertIn(self.assigned_session, visible_sessions)
        self.assertTrue(self.lawyer.has_perm("consultation.can_change_consultation_status"))
        self.assertTrue(self.lawyer.has_perm("consultation.can_close_consultation"))
        self.assertEqual(self.lawyer.user_permissions.count(), 0)
        self.assertNotIn(self.available_session, visible_sessions)
        self.assertNotIn(self.owner_session, visible_sessions)
        self.assertNotIn(self.foreign_assigned_session, visible_sessions)

    def test_regular_user_can_view_only_own_sessions(self):
        self.client.login(username="owner", password="owner-pass")

        response = self.client.get(reverse("consultation:session_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["sessions"]), [self.owner_session])

    def test_employee_with_permission_can_change_status(self):
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.post(
            reverse("consultation:change_consultation_status", kwargs={"pk": self.available_session.pk}),
            {"status": ConsultationSession.Status.IN_PROGRESS},
        )

        self.available_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.available_session.status, ConsultationSession.Status.IN_PROGRESS)

    def test_regular_user_cannot_change_status(self):
        self.client.login(username="owner", password="owner-pass")

        response = self.client.post(
            reverse("consultation:change_consultation_status", kwargs={"pk": self.owner_session.pk}),
            {"status": ConsultationSession.Status.IN_PROGRESS},
        )

        self.owner_session.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.owner_session.status, ConsultationSession.Status.NEW)

    def test_head_can_assign_executor_and_change_category(self):
        assign_primary_role(self.supervisor, ROLE_HEAD)
        assign_primary_role(self.lawyer, ROLE_LAWYER)
        second_category = ConsultationCategory.objects.create(
            name="Трудовое право",
            slug="labor-law",
        )
        self.client.login(username="supervisor", password="supervisor-pass")

        response = self.client.post(
            reverse("consultation:assign_consultation", kwargs={"pk": self.available_session.pk}),
            {
                "assigned_to": self.lawyer.pk,
                "category": second_category.pk,
            },
        )

        self.available_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.available_session.assigned_to, self.lawyer)
        self.assertEqual(self.available_session.category, second_category)

    def test_employee_with_permission_can_mark_requires_specialist(self):
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.post(
            reverse(
                "consultation:mark_consultation_requires_specialist",
                kwargs={"pk": self.available_session.pk},
            ),
            {"requires_specialist": "true"},
        )

        self.available_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.available_session.requires_specialist)

    def test_close_consultation_works_only_with_close_permission(self):
        self.assigned_session.status = ConsultationSession.Status.COMPLETED
        self.assigned_session.save(update_fields=["status", "updated_at"])
        assign_primary_role(self.lawyer, ROLE_LAWYER)
        self.client.login(username="lawyer", password="lawyer-pass")

        response = self.client.post(
            reverse("consultation:close_consultation", kwargs={"pk": self.assigned_session.pk}),
            {},
        )

        self.assigned_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.assigned_session.status, ConsultationSession.Status.CLOSED)

    def test_close_consultation_is_forbidden_without_permission(self):
        self.available_session.status = ConsultationSession.Status.COMPLETED
        self.available_session.save(update_fields=["status", "updated_at"])
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.post(
            reverse("consultation:close_consultation", kwargs={"pk": self.available_session.pk}),
            {},
        )

        self.available_session.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.available_session.status, ConsultationSession.Status.COMPLETED)

    def test_invalid_status_transition_is_not_applied(self):
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.post(
            reverse("consultation:change_consultation_status", kwargs={"pk": self.available_session.pk}),
            {"status": ConsultationSession.Status.COMPLETED},
        )

        self.available_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.available_session.status, ConsultationSession.Status.NEW)

    def test_regular_user_does_not_see_staff_actions_block(self):
        self.client.login(username="owner", password="owner-pass")

        response = self.client.get(
            reverse("consultation:session_detail", kwargs={"pk": self.owner_session.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Служебные действия")
        self.assertFalse(response.context["show_staff_actions"])

    def test_support_user_sees_staff_actions_block(self):
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.get(
            reverse("consultation:session_detail", kwargs={"pk": self.available_session.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Служебные действия")
        self.assertTrue(response.context["show_staff_actions"])
        self.assertTrue(response.context["can_change_consultation_status"])
        self.assertTrue(response.context["can_mark_needs_specialist"])
        self.assertFalse(response.context["can_assign_consultation"])
        self.assertFalse(response.context["can_close_consultation"])

    def test_ui_shows_only_actions_allowed_by_permissions(self):
        assign_primary_role(self.support, ROLE_SUPPORT)
        self.client.login(username="support", password="support-pass")

        response = self.client.get(
            reverse("consultation:session_detail", kwargs={"pk": self.available_session.pk})
        )

        self.assertContains(
            response,
            reverse("consultation:change_consultation_status", kwargs={"pk": self.available_session.pk}),
        )
        self.assertContains(
            response,
            reverse(
                "consultation:mark_consultation_requires_specialist",
                kwargs={"pk": self.available_session.pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse("consultation:assign_consultation", kwargs={"pk": self.available_session.pk}),
        )
        self.assertNotContains(
            response,
            reverse("consultation:close_consultation", kwargs={"pk": self.available_session.pk}),
        )

    def test_head_ui_shows_assignment_but_not_specialist_toggle(self):
        assign_primary_role(self.supervisor, ROLE_HEAD)
        self.client.login(username="supervisor", password="supervisor-pass")

        response = self.client.get(
            reverse("consultation:session_detail", kwargs={"pk": self.available_session.pk})
        )

        self.assertContains(
            response,
            reverse("consultation:assign_consultation", kwargs={"pk": self.available_session.pk}),
        )
        self.assertContains(
            response,
            reverse("consultation:change_consultation_status", kwargs={"pk": self.available_session.pk}),
        )
        self.assertContains(
            response,
            reverse("consultation:close_consultation", kwargs={"pk": self.available_session.pk}),
        )
        self.assertNotContains(
            response,
            reverse(
                "consultation:mark_consultation_requires_specialist",
                kwargs={"pk": self.available_session.pk},
            ),
        )

    def test_dashboard_is_forbidden_for_regular_user(self):
        self.client.login(username="owner", password="owner-pass")

        response = self.client.get(reverse("consultation:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_filters_by_status(self):
        assign_primary_role(self.supervisor, ROLE_HEAD)
        self.available_session.status = ConsultationSession.Status.IN_PROGRESS
        self.available_session.save(update_fields=["status", "updated_at"])
        self.owner_session.status = ConsultationSession.Status.NEW
        self.owner_session.save(update_fields=["status", "updated_at"])
        self.client.login(username="supervisor", password="supervisor-pass")

        response = self.client.get(
            reverse("consultation:dashboard"),
            {"status": ConsultationSession.Status.IN_PROGRESS},
        )

        self.assertEqual(response.status_code, 200)
        sessions = list(response.context["sessions"])
        self.assertEqual(sessions, [self.available_session])

    def test_dashboard_filters_by_category_and_assignee(self):
        assign_primary_role(self.supervisor, ROLE_HEAD)
        assign_primary_role(self.lawyer, ROLE_LAWYER)
        other_category = ConsultationCategory.objects.create(
            name="Административное право",
            slug="admin-law",
        )
        self.assigned_session.category = other_category
        self.assigned_session.save(update_fields=["category", "updated_at"])
        self.client.login(username="supervisor", password="supervisor-pass")

        response = self.client.get(
            reverse("consultation:dashboard"),
            {"category": other_category.pk, "assigned_to": self.lawyer.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["sessions"]), [self.assigned_session])


class ConsultationRoutingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="client", password="client-pass")
        self.category = ConsultationCategory.objects.create(
            name="Семейное право",
            slug="family-law",
        )
        self.session = ConsultationSession.objects.create(user=self.user, title="Маршрутизация")

    def _analysis(self, **overrides):
        payload = {
            "scenario": ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
            "category": ConsultationSession.AnalysisCategory.FAMILY,
            "is_typical": True,
            "has_enough_information": True,
            "needs_clarification": False,
            "needs_specialist": False,
            "confidence": 0.82,
            "missing_information": [],
            "clarifying_questions": [],
            "short_reason": "Типовой семейный вопрос.",
        }
        payload.update(overrides)
        return ConsultationAnalysis.from_payload(payload)

    def test_analysis_is_triggered_after_new_user_message(self):
        self.client.login(username="client", password="client-pass")
        processed = ProcessedConsultationReply(
            analysis=self._analysis(),
            llm_response=LLMResponse(
                text="Краткий вывод:\nТестовый ответ.",
                status="success",
                model_name="demo-model",
            ),
            analysis_llm_response=LLMResponse(
                text='{"scenario":"typical_answer"}',
                status="success",
                model_name="demo-model",
            ),
        )

        with patch("consultation.views.OllamaService.process_user_message", return_value=processed) as mocked:
            response = self.client.post(
                reverse("consultation:send_message_api", kwargs={"pk": self.session.pk}),
                {"content": "Помогите понять мои права после развода."},
            )

        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once()
        self.assertEqual(self.session.messages.filter(role=ChatMessage.Role.USER).count(), 1)
        self.assertEqual(self.session.messages.filter(role=ChatMessage.Role.ASSISTANT).count(), 1)

    def test_send_message_logs_analysis_and_generation_separately(self):
        self.client.login(username="client", password="client-pass")
        processed = ProcessedConsultationReply(
            analysis=self._analysis(),
            llm_response=LLMResponse(
                text="Краткий вывод:\nТестовый ответ.",
                status="success",
                model_name="demo-model",
            ),
            analysis_llm_response=LLMResponse(
                text='{"scenario":"typical_answer"}',
                status="success",
                model_name="demo-model",
            ),
        )

        with patch("consultation.views.OllamaService.process_user_message", return_value=processed):
            response = self.client.post(
                reverse("consultation:send_message_api", kwargs={"pk": self.session.pk}),
                {"content": "Помогите понять мои права после развода."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(LLMInteractionLog.objects.count(), 2)
        analysis_log, generation_log = LLMInteractionLog.objects.order_by("created_at", "pk")
        self.assertIsNone(analysis_log.response_message)
        self.assertEqual(analysis_log.request_message.role, ChatMessage.Role.USER)
        self.assertIsNotNone(generation_log.response_message)
        self.assertEqual(generation_log.response_message.role, ChatMessage.Role.ASSISTANT)

    def test_typical_question_with_enough_data_gives_structured_answer(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="После развода у нас есть спор о порядке общения с ребенком и уже есть письменные договоренности.",
        )
        analysis = self._analysis()
        response = LLMResponse(
            text=(
                "Краткий вывод:\nМожно дать первичный справочный ответ.\n\n"
                "Что важно учесть:\n- Нужны точные обстоятельства.\n\n"
                "Рекомендуемые действия:\n1. Соберите документы.\n\n"
                "Что желательно уточнить дополнительно:\nДополнительные уточнения на текущем этапе не требуются.\n\n"
                "Ограничение консультации:\n"
                "Данный ответ носит справочный характер и не заменяет полноценную юридическую консультацию специалиста."
            ),
            status="success",
            model_name="demo-model",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"typical_answer"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=response,
        ):
            processed = OllamaService.process_user_message(self.session, user_message)

        self.session.refresh_from_db()
        self.assertEqual(processed.analysis.scenario, ConsultationSession.AnalysisScenario.TYPICAL_ANSWER)
        self.assertIn("Краткий вывод:", processed.llm_response.text)
        self.assertIn("Что важно учесть:", processed.llm_response.text)
        self.assertIn("Рекомендуемые действия:", processed.llm_response.text)
        self.assertFalse(self.session.awaiting_clarification)
        self.assertEqual(self.session.last_analysis_scenario, ConsultationSession.AnalysisScenario.TYPICAL_ANSWER)

    def test_typical_question_with_missing_data_gives_clarification(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Меня уволили, что делать?",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.LABOR,
            has_enough_information=False,
            needs_clarification=True,
            confidence=0.48,
            missing_information=["Дата увольнения", "Какое основание указал работодатель"],
            clarifying_questions=[
                "Когда именно произошло увольнение?",
                "Какое основание увольнения указал работодатель в документах?",
            ],
            short_reason="Не хватает ключевых фактов по увольнению.",
        )
        response = LLMResponse(
            text=(
                "Для первичной консультации нужно уточнить несколько обстоятельств.\n\n"
                "1. Когда именно произошло увольнение?\n"
                "2. Какое основание увольнения указал работодатель в документах?\n\n"
                "После уточнения можно будет дать более точный справочный ответ."
            ),
            status="success",
            model_name="demo-model",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"needs_clarification"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=response,
        ):
            processed = OllamaService.process_user_message(self.session, user_message)

        self.session.refresh_from_db()
        self.assertEqual(processed.analysis.scenario, ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION)
        self.assertTrue(self.session.awaiting_clarification)
        self.assertFalse(self.session.requires_specialist)
        self.assertEqual(self.session.status, ConsultationSession.Status.IN_PROGRESS)
        self.assertIn("нужно уточнить", processed.llm_response.text.lower())

    def test_generate_response_maps_clarification_scenario_to_existing_prompt_key(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Меня уволили, что делать?",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.LABOR,
            has_enough_information=False,
            needs_clarification=True,
            confidence=0.51,
        )

        with self.settings(OLLAMA_ENABLED=True), patch.object(
            OllamaService,
            "_perform_ollama_chat",
            return_value=LLMResponse(
                text="Для первичной консультации нужно уточнить несколько обстоятельств.",
                status="success",
                model_name="demo-model",
            ),
        ) as mocked:
            response = OllamaService.generate_response_for_analysis(
                self.session,
                analysis,
                user_message,
            )

        self.assertEqual(response.status, "success")
        mocked.assert_called_once()

    def test_clarification_questions_are_limited_to_two_by_default(self):
        analysis = ConsultationAnalysis.from_payload(
            {
                "scenario": ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
                "category": ConsultationSession.AnalysisCategory.CIVIL,
                "is_typical": True,
                "has_enough_information": False,
                "needs_specialist": False,
                "needs_clarification": True,
                "confidence": 0.31,
                "missing_information": [
                    "Точная дата события",
                    "Какие документы есть",
                    "Был ли официальный ответ",
                ],
                "clarifying_questions": [
                    "Когда произошло событие?",
                    "Какие документы у вас есть на руках?",
                    "Получали ли вы официальный ответ?",
                ],
                "short_reason": "Для безопасного ответа пока не хватает базовых обстоятельств.",
            }
        )

        self.assertEqual(len(analysis.clarifying_questions), 2)
        self.assertEqual(len(analysis.missing_information), 2)

    def test_complex_case_escalates_only_in_extreme_scenario(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Получил судебное определение и нужно срочно обжаловать действия по делу.",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST,
            is_typical=False,
            has_enough_information=False,
            needs_specialist=True,
            confidence=0.93,
            short_reason="Есть признаки процессуально сложного случая.",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"needs_specialist"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=LLMResponse(
                text="Ситуация требует участия специалиста.",
                status="success",
                model_name="demo-model",
            ),
        ):
            OllamaService.process_user_message(self.session, user_message)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ConsultationSession.Status.NEEDS_SPECIALIST)
        self.assertTrue(self.session.requires_specialist)
        self.assertFalse(self.session.awaiting_clarification)

    def test_general_sanction_question_prefers_typical_answer(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Что грозит за хранение наркотиков без цели сбыта?",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.CIVIL,
            has_enough_information=False,
            needs_clarification=True,
            confidence=0.58,
            missing_information=["Точное вещество"],
            clarifying_questions=["Какое именно вещество фигурирует в ситуации?"],
            short_reason="Неизвестно точное вещество.",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"needs_clarification"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=LLMResponse(
                text="Краткий вывод:\nМожно дать общий первичный ответ с оговорками.",
                status="success",
                model_name="demo-model",
            ),
        ):
            processed = OllamaService.process_user_message(self.session, user_message)

        self.assertEqual(processed.analysis.scenario, ConsultationSession.AnalysisScenario.TYPICAL_ANSWER)
        self.assertFalse(processed.analysis.needs_specialist)

    def test_after_substantive_clarification_system_prefers_typical_answer(self):
        ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Что грозит за хранение марихуаны?",
        )
        ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.ASSISTANT,
            content=(
                "Для первичной консультации нужно уточнить несколько обстоятельств.\n"
                "1. Какое количество вещества?\n"
                "2. Есть ли судимости и признаки сбыта?"
            ),
        )
        self.session.awaiting_clarification = True
        self.session.save(update_fields=["awaiting_clarification", "updated_at"])
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Речь о хранении 1 грамма марихуаны, вещество найдено в машине, судимостей нет, предметов для сбыта не было.",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.CIVIL,
            has_enough_information=False,
            needs_clarification=True,
            confidence=0.63,
            missing_information=[
                "Количество вещества",
                "Есть ли судимости",
                "Есть ли признаки сбыта",
            ],
            clarifying_questions=[
                "Какое количество вещества фигурирует в ситуации?",
                "Есть ли судимости?",
                "Есть ли признаки сбыта?",
            ],
            short_reason="Модель пытается запросить те же обстоятельства повторно.",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"needs_clarification"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=LLMResponse(
                text="Краткий вывод:\nНа этой стадии можно дать первичный справочный ответ с оговорками.",
                status="success",
                model_name="demo-model",
            ),
        ):
            processed = OllamaService.process_user_message(self.session, user_message)

        self.assertEqual(processed.analysis.scenario, ConsultationSession.AnalysisScenario.TYPICAL_ANSWER)
        self.assertEqual(processed.analysis.clarifying_questions, [])
        self.session.refresh_from_db()
        self.assertFalse(self.session.awaiting_clarification)

    def test_known_facts_are_not_requested_again_in_second_clarification(self):
        ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.ASSISTANT,
            content=(
                "Для первичной консультации нужно уточнить несколько обстоятельств.\n"
                "1. Когда нашли вещество?\n"
                "2. Есть ли судимости?"
            ),
        )
        self.session.awaiting_clarification = True
        self.session.save(update_fields=["awaiting_clarification", "updated_at"])
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Нашли вчера.",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION,
            category=ConsultationSession.AnalysisCategory.CIVIL,
            has_enough_information=False,
            needs_clarification=True,
            confidence=0.34,
            missing_information=[
                "вчера",
                "Есть ли предметы для сбыта",
            ],
            clarifying_questions=[
                "Когда нашли вещество?",
                "Были ли предметы для сбыта?",
            ],
            short_reason="Данных всё ещё мало, но часть уже известна.",
        )

        adjusted = OllamaService._adjust_analysis_for_context(
            self.session,
            user_message,
            analysis,
            was_awaiting_clarification=True,
        )

        self.assertEqual(adjusted.scenario, ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION)
        self.assertEqual(adjusted.clarifying_questions, ["Были ли предметы для сбыта?"])
        self.assertEqual(adjusted.missing_information, ["Есть ли предметы для сбыта"])

    def test_specialist_escalation_is_not_used_instead_of_primary_answer(self):
        analysis = ConsultationAnalysis.from_payload(
            {
                "scenario": ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST,
                "category": ConsultationSession.AnalysisCategory.CIVIL,
                "is_typical": True,
                "has_enough_information": False,
                "needs_specialist": True,
                "needs_clarification": False,
                "confidence": 0.44,
                "missing_information": ["Точное количество вещества"],
                "clarifying_questions": [],
                "short_reason": "Случай ещё не выглядит high-risk.",
            }
        )

        self.assertNotEqual(analysis.scenario, ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST)

    def test_low_confidence_specialist_scenario_is_downgraded_to_clarification(self):
        analysis = ConsultationAnalysis.from_payload(
            {
                "scenario": ConsultationSession.AnalysisScenario.NEEDS_SPECIALIST,
                "category": ConsultationSession.AnalysisCategory.CIVIL,
                "is_typical": False,
                "has_enough_information": False,
                "needs_specialist": True,
                "needs_clarification": False,
                "confidence": 0.32,
                "missing_information": ["Недостаточно данных о стадии спора"],
                "clarifying_questions": [],
                "short_reason": "Есть риск, но уверенность анализа низкая.",
            }
        )

        self.assertEqual(analysis.scenario, ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION)
        self.assertTrue(analysis.needs_clarification)
        self.assertFalse(analysis.needs_specialist)

    def test_category_is_saved_when_match_exists(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="После развода есть спор о выплате алиментов.",
        )
        analysis = self._analysis(category=ConsultationSession.AnalysisCategory.FAMILY)

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"typical_answer"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=LLMResponse(
                text="Краткий вывод:\nТест.",
                status="success",
                model_name="demo-model",
            ),
        ):
            OllamaService.process_user_message(self.session, user_message)

        self.session.refresh_from_db()
        self.assertEqual(self.session.last_analysis_category, ConsultationSession.AnalysisCategory.FAMILY)
        self.assertEqual(self.session.category, self.category)

    def test_analysis_json_is_validated(self):
        with self.assertRaises(ValueError):
            ConsultationAnalysis.from_response_text("```json\n{\"scenario\":\"unknown\"}\n```")

    def test_invalid_analysis_response_is_handled_safely(self):
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Подскажите по разделу имущества.",
        )

        with self.settings(OLLAMA_ENABLED=True), patch.object(
            OllamaService,
            "_perform_ollama_chat",
            return_value=LLMResponse(
                text="невалидный ответ",
                status="success",
                model_name="demo-model",
            ),
        ):
            analysis = OllamaService.analyze_user_message(self.session, user_message)

        self.assertEqual(analysis.scenario, ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION)
        self.assertFalse(analysis.needs_specialist)
        self.assertGreater(len(analysis.clarifying_questions), 0)

    def test_low_confidence_prefers_clarification_over_escalation(self):
        analysis = ConsultationAnalysis.from_payload(
            {
                "scenario": ConsultationSession.AnalysisScenario.INSUFFICIENT_CONFIDENCE,
                "category": ConsultationSession.AnalysisCategory.CIVIL,
                "is_typical": False,
                "has_enough_information": False,
                "needs_specialist": False,
                "needs_clarification": False,
                "confidence": 0.24,
                "missing_information": ["Неясна стадия спора"],
                "clarifying_questions": [],
                "short_reason": "Низкая уверенность без признаков крайнего случая.",
            }
        )

        self.assertEqual(analysis.scenario, ConsultationSession.AnalysisScenario.NEEDS_CLARIFICATION)
        self.assertTrue(analysis.needs_clarification)
        self.assertFalse(analysis.needs_specialist)

    def test_typical_answer_is_allowed_with_reasonable_caveats(self):
        analysis = ConsultationAnalysis.from_payload(
            {
                "scenario": ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
                "category": ConsultationSession.AnalysisCategory.CIVIL,
                "is_typical": True,
                "has_enough_information": False,
                "needs_specialist": False,
                "needs_clarification": True,
                "confidence": 0.64,
                "missing_information": ["Точная дата события"],
                "clarifying_questions": ["Когда именно произошло событие?"],
                "short_reason": "Можно ответить в общем виде с оговорками.",
            }
        )

        self.assertEqual(analysis.scenario, ConsultationSession.AnalysisScenario.TYPICAL_ANSWER)

    def test_manual_specialist_mode_is_not_reset_by_auto_analysis(self):
        self.session.status = ConsultationSession.Status.NEEDS_SPECIALIST
        self.session.requires_specialist = True
        self.session.save(update_fields=["status", "requires_specialist", "updated_at"])
        user_message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Дополнительно сообщаю новые обстоятельства по делу.",
        )
        analysis = self._analysis(
            scenario=ConsultationSession.AnalysisScenario.TYPICAL_ANSWER,
            confidence=0.91,
            short_reason="По одному сообщению вопрос выглядит более простым.",
        )

        with patch.object(
            OllamaService,
            "_analyze_user_message_with_trace",
            return_value=(
                analysis,
                LLMResponse(
                    text='{"scenario":"typical_answer"}',
                    status="success",
                    model_name="demo-model",
                ),
            ),
        ), patch.object(
            OllamaService,
            "generate_response_for_analysis",
            return_value=LLMResponse(
                text="Краткий вывод:\nТест.",
                status="success",
                model_name="demo-model",
            ),
        ):
            OllamaService.process_user_message(self.session, user_message)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ConsultationSession.Status.NEEDS_SPECIALIST)
        self.assertTrue(self.session.requires_specialist)
        self.assertFalse(self.session.awaiting_clarification)
