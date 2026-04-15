from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


ROLE_PERMISSIONS = {
    "Пользователь": [],
    "Специалист поддержки": [
        "view_consultationsession",
        "change_consultationsession",
        "can_route_consultations",
    ],
    "Юрист-консультант": [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "can_review_consultations",
    ],
    "Руководитель юридического отдела": [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "view_llminteractionlog",
        "can_review_consultations",
        "can_route_consultations",
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
        "view_userprofile",
    ],
}


class Command(BaseCommand):
    help = "Создаёт базовые группы и назначает им права"

    def handle(self, *args, **options):
        for role_name, codenames in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=role_name)
            permissions = Permission.objects.filter(codename__in=codenames)
            group.permissions.set(permissions)
            self.stdout.write(self.style.SUCCESS(f"Группа '{role_name}' настроена."))
