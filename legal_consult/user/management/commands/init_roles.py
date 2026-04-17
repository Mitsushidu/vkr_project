from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from user.roles import MANAGED_PERMISSION_CODENAMES, ROLE_NAMES, ROLE_PERMISSIONS


class Command(BaseCommand):
    help = "Создаёт базовые группы и назначает им права"

    def handle(self, *args, **options):
        for role_name in ROLE_NAMES:
            codenames = ROLE_PERMISSIONS[role_name]
            group, _ = Group.objects.get_or_create(name=role_name)
            current_managed_permissions = group.permissions.filter(
                codename__in=MANAGED_PERMISSION_CODENAMES
            )
            target_permissions = Permission.objects.filter(codename__in=codenames)

            group.permissions.remove(*current_managed_permissions)
            group.permissions.add(*target_permissions)
            self.stdout.write(self.style.SUCCESS(f"Группа '{role_name}' настроена."))
