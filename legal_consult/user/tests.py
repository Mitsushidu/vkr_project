from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase


class UserProfileTests(TestCase):
    def test_profile_created_automatically(self):
        user = get_user_model().objects.create_user(username="signal-user", password="pass12345")
        self.assertTrue(hasattr(user, "profile"))

    def test_custom_manage_users_permission_exists(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="user",
                codename="can_manage_users",
            ).exists()
        )


class InitRolesCommandTests(TestCase):
    def test_init_roles_assigns_domain_permissions(self):
        call_command("init_roles")

        support_permissions = set(
            Group.objects.get(name="Специалист поддержки").permissions.values_list(
                "codename",
                flat=True,
            )
        )
        lawyer_permissions = set(
            Group.objects.get(name="Юрист-консультант").permissions.values_list(
                "codename",
                flat=True,
            )
        )
        supervisor_permissions = set(
            Group.objects.get(name="Руководитель юридического отдела").permissions.values_list(
                "codename",
                flat=True,
            )
        )
        admin_permissions = set(
            Group.objects.get(name="Системный администратор").permissions.values_list(
                "codename",
                flat=True,
            )
        )

        self.assertIn("can_view_all_consultations", support_permissions)
        self.assertIn("can_mark_needs_specialist", support_permissions)
        self.assertNotIn("can_assign_consultation", support_permissions)

        self.assertIn("can_change_consultation_status", lawyer_permissions)
        self.assertIn("can_close_consultation", lawyer_permissions)
        self.assertNotIn("can_view_all_consultations", lawyer_permissions)

        self.assertIn("can_assign_consultation", supervisor_permissions)
        self.assertIn("can_review_llm_logs", supervisor_permissions)
        self.assertIn("can_view_all_consultations", supervisor_permissions)

        self.assertIn("can_manage_users", admin_permissions)
        self.assertIn("can_assign_consultation", admin_permissions)
        self.assertIn("delete_userprofile", admin_permissions)

    def test_init_roles_preserves_unmanaged_group_permissions(self):
        group = Group.objects.create(name="Специалист поддержки")
        extra_permission = Permission.objects.get(
            content_type__app_label="consultation",
            codename="view_consultationcategory",
        )
        group.permissions.add(extra_permission)

        call_command("init_roles")

        self.assertTrue(
            Group.objects.get(name="Специалист поддержки").permissions.filter(
                pk=extra_permission.pk
            ).exists()
        )
