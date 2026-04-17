from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .roles import (
    ROLE_ADMIN,
    ROLE_HEAD,
    ROLE_LAWYER,
    ROLE_NAMES,
    ROLE_SUPPORT,
    assign_primary_role,
    get_user_primary_role,
    user_has_role,
)


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
    def test_init_roles_creates_all_supported_groups(self):
        call_command("init_roles")

        self.assertSetEqual(set(Group.objects.filter(name__in=ROLE_NAMES).values_list("name", flat=True)), set(ROLE_NAMES))

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


class RoleAssignmentTests(TestCase):
    def setUp(self):
        call_command("init_roles")
        self.user = get_user_model().objects.create_user(username="role-user", password="pass12345")

    def test_assign_primary_role_sets_profile_and_group_membership(self):
        assign_primary_role(self.user, ROLE_SUPPORT)
        self.user.refresh_from_db()

        self.assertEqual(self.user.profile.primary_role.name, ROLE_SUPPORT)
        self.assertEqual(get_user_primary_role(self.user).name, ROLE_SUPPORT)
        self.assertTrue(user_has_role(self.user, ROLE_SUPPORT))
        self.assertTrue(self.user.groups.filter(name=ROLE_SUPPORT).exists())
        self.assertTrue(self.user.has_perm("consultation.can_mark_needs_specialist"))
        self.assertEqual(self.user.user_permissions.count(), 0)

    def test_reassign_primary_role_keeps_single_target_group(self):
        extra_group = Group.objects.create(name="Рабочая группа")
        self.user.groups.add(extra_group)

        assign_primary_role(self.user, ROLE_SUPPORT)
        assign_primary_role(self.user, ROLE_HEAD)
        self.user.refresh_from_db()

        role_groups = set(self.user.groups.filter(name__in=ROLE_NAMES).values_list("name", flat=True))
        self.assertEqual(role_groups, {ROLE_HEAD})
        self.assertTrue(self.user.groups.filter(pk=extra_group.pk).exists())
        self.assertEqual(self.user.profile.primary_role.name, ROLE_HEAD)
        self.assertTrue(self.user.has_perm("consultation.can_assign_consultation"))
        self.assertFalse(self.user.has_perm("consultation.can_mark_needs_specialist"))

    def test_user_profile_save_syncs_primary_role_with_groups(self):
        profile = self.user.profile
        profile.primary_role = Group.objects.get(name=ROLE_LAWYER)
        profile.save()
        self.user.refresh_from_db()

        self.assertEqual(get_user_primary_role(self.user).name, ROLE_LAWYER)
        self.assertTrue(self.user.groups.filter(name=ROLE_LAWYER).exists())
        self.assertEqual(self.user.groups.filter(name__in=ROLE_NAMES).count(), 1)


class ProfileViewTests(TestCase):
    def setUp(self):
        call_command("init_roles")
        self.user = get_user_model().objects.create_user(
            username="profile-user",
            password="profile-pass",
            email="profile@example.com",
        )

    def test_profile_shows_primary_role(self):
        assign_primary_role(self.user, ROLE_ADMIN)
        self.client.login(username="profile-user", password="profile-pass")

        response = self.client.get(reverse("user:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["primary_role"].name, ROLE_ADMIN)
        self.assertContains(response, ROLE_ADMIN)
