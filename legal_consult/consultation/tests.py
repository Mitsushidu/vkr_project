from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ConsultationSession


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
