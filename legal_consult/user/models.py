from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models

from .roles import ROLE_GROUP_FILTER, is_role_group


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Пользователь",
    )
    middle_name = models.CharField("Отчество", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    position = models.CharField("Должность", max_length=150, blank=True)
    primary_role = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_user_profiles",
        verbose_name="Основная роль",
        limit_choices_to=ROLE_GROUP_FILTER,
    )

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"
        permissions = [
            ("can_manage_users", "Может управлять пользователями"),
        ]

    def __str__(self) -> str:
        return f"Профиль: {self.user.username}"

    def clean(self):
        super().clean()
        if self.primary_role and not is_role_group(self.primary_role):
            raise ValidationError({"primary_role": "Можно выбрать только одну из поддерживаемых ролей."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        from .roles import sync_user_role_groups

        sync_user_role_groups(self.user, self.primary_role)
