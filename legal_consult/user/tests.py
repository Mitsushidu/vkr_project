from django.contrib.auth import get_user_model
from django.test import TestCase


class UserProfileTests(TestCase):
    def test_profile_created_automatically(self):
        user = get_user_model().objects.create_user(username="signal-user", password="pass12345")
        self.assertTrue(hasattr(user, "profile"))
