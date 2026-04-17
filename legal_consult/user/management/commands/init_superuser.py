import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Создаёт начального суперпользователя для демонстрационного запуска, если его ещё нет"

    def handle(self, *args, **options):
        user_model = get_user_model()
        existing_superuser = user_model.objects.filter(is_superuser=True).first()
        if existing_superuser:
            self.stdout.write(
                self.style.WARNING(
                    f"Суперпользователь уже существует: {existing_superuser.get_username()}."
                )
            )
            return

        username = os.getenv("INIT_SUPERUSER_USERNAME", "admin")
        email = os.getenv("INIT_SUPERUSER_EMAIL", "admin@example.com")
        password = os.getenv("INIT_SUPERUSER_PASSWORD", "admin12345")

        if user_model.objects.filter(username=username).exists():
            raise CommandError(
                f"Пользователь '{username}' уже существует и не является суперпользователем."
            )

        user_model.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Суперпользователь '{username}' создан."
            )
        )
