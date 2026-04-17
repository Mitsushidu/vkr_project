from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


MANAGED_PERMISSION_CODENAMES = {
    "add_consultationsession",
    "change_consultationsession",
    "delete_consultationsession",
    "view_consultationsession",
    "view_chatmessage",
    "view_llminteractionlog",
    "add_userprofile",
    "change_userprofile",
    "delete_userprofile",
    "view_userprofile",
    "can_view_all_consultations",
    "can_assign_consultation",
    "can_change_consultation_status",
    "can_mark_needs_specialist",
    "can_close_consultation",
    "can_review_llm_logs",
    "can_manage_users",
    "can_route_consultations",
    "can_review_consultations",
}


ROLE_PERMISSIONS = {
    "Пользователь": [],
    "Специалист поддержки": [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "can_view_all_consultations",
        "can_change_consultation_status",
        "can_mark_needs_specialist",
    ],
    "Юрист-консультант": [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "can_change_consultation_status",
        "can_close_consultation",
    ],
    "Руководитель юридического отдела": [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "view_llminteractionlog",
        "can_view_all_consultations",
        "can_assign_consultation",
        "can_change_consultation_status",
        "can_close_consultation",
        "can_review_llm_logs",
    ],
    "Системный администратор": [
        "add_consultationsession",
        "change_consultationsession",
        "delete_consultationsession",
        "view_consultationsession",
        "view_chatmessage",
        "view_llminteractionlog",
        "add_userprofile",
        "change_userprofile",
        "delete_userprofile",
        "view_userprofile",
        "can_view_all_consultations",
        "can_assign_consultation",
        "can_change_consultation_status",
        "can_mark_needs_specialist",
        "can_close_consultation",
        "can_review_llm_logs",
        "can_manage_users",
    ],
}


class Command(BaseCommand):
    help = "Создаёт базовые группы и назначает им права"

    def handle(self, *args, **options):
        for role_name, codenames in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=role_name)
            current_managed_permissions = group.permissions.filter(
                codename__in=MANAGED_PERMISSION_CODENAMES
            )
            target_permissions = Permission.objects.filter(codename__in=codenames)

            group.permissions.remove(*current_managed_permissions)
            group.permissions.add(*target_permissions)
            self.stdout.write(self.style.SUCCESS(f"Группа '{role_name}' настроена."))
