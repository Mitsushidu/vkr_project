from django.core.management.base import BaseCommand
from django.utils.text import slugify

from consultation.models import ConsultationCategory


DEFAULT_CATEGORIES = [
    "Семейное право",
    "Трудовое право",
    "Жилищное право",
    "Защита прав потребителей",
    "Наследственное право",
    "Административные вопросы",
]


class Command(BaseCommand):
    help = "Создаёт базовые категории юридических обращений"

    def handle(self, *args, **options):
        for name in DEFAULT_CATEGORIES:
            obj, created = ConsultationCategory.objects.get_or_create(
                slug=slugify(name, allow_unicode=True),
                defaults={"name": name},
            )
            action = "Создана" if created else "Уже существует"
            self.stdout.write(self.style.SUCCESS(f"{action}: {obj.name}"))
