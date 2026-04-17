from django.contrib.auth.models import Group


ROLE_USER = "Пользователь"
ROLE_SUPPORT = "Специалист поддержки"
ROLE_LAWYER = "Юрист-консультант"
ROLE_HEAD = "Руководитель юридического отдела"
ROLE_ADMIN = "Системный администратор"

ROLE_NAMES = (
    ROLE_USER,
    ROLE_SUPPORT,
    ROLE_LAWYER,
    ROLE_HEAD,
    ROLE_ADMIN,
)

ROLE_GROUP_FILTER = {"name__in": ROLE_NAMES}

LEGACY_MANAGED_PERMISSION_CODENAMES = {
    "can_route_consultations",
    "can_review_consultations",
}

ROLE_PERMISSIONS = {
    ROLE_USER: [],
    ROLE_SUPPORT: [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "can_view_all_consultations",
        "can_change_consultation_status",
        "can_mark_needs_specialist",
    ],
    ROLE_LAWYER: [
        "view_consultationsession",
        "change_consultationsession",
        "view_chatmessage",
        "can_change_consultation_status",
        "can_close_consultation",
    ],
    ROLE_HEAD: [
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
    ROLE_ADMIN: [
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

MANAGED_PERMISSION_CODENAMES = {
    codename
    for permissions in ROLE_PERMISSIONS.values()
    for codename in permissions
} | LEGACY_MANAGED_PERMISSION_CODENAMES


def is_role_name(role_name: str | None) -> bool:
    return bool(role_name) and role_name in ROLE_NAMES


def is_role_group(group: Group | None) -> bool:
    return bool(group) and is_role_name(group.name)


def get_role_groups_queryset():
    return Group.objects.filter(**ROLE_GROUP_FILTER).order_by("name")


def get_role_group(role):
    if isinstance(role, Group):
        if not is_role_group(role):
            raise Group.DoesNotExist(f"Группа '{role.name}' не является поддерживаемой ролью.")
        return role

    return Group.objects.get(name=role)


def get_user_primary_role(user):
    if not getattr(user, "is_authenticated", False):
        return None

    profile = getattr(user, "profile", None)
    if profile and profile.primary_role_id:
        return profile.primary_role

    role_groups = list(user.groups.filter(**ROLE_GROUP_FILTER))
    if len(role_groups) == 1:
        return role_groups[0]
    return None


def user_has_role(user, role_name: str) -> bool:
    if not getattr(user, "is_authenticated", False) or not is_role_name(role_name):
        return False
    return user.groups.filter(name=role_name).exists()


def sync_user_role_groups(user, primary_role=None) -> None:
    if not getattr(user, "pk", None):
        return

    if primary_role is None:
        profile = getattr(user, "profile", None)
        primary_role = profile.primary_role if profile and profile.primary_role_id else None
    elif not is_role_group(primary_role):
        raise Group.DoesNotExist(f"Группа '{primary_role.name}' не является поддерживаемой ролью.")

    target_groups = user.groups.filter(**ROLE_GROUP_FILTER)
    if primary_role is None:
        if target_groups.exists():
            user.groups.remove(*target_groups)
        return

    stale_groups = target_groups.exclude(pk=primary_role.pk)
    if stale_groups.exists():
        user.groups.remove(*stale_groups)

    if not user.groups.filter(pk=primary_role.pk).exists():
        user.groups.add(primary_role)


def assign_primary_role(user, role) -> Group | None:
    from .models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    primary_role = get_role_group(role) if role else None
    if primary_role and not is_role_group(primary_role):
        raise Group.DoesNotExist(f"Группа '{primary_role.name}' не является поддерживаемой ролью.")

    if profile.primary_role_id != getattr(primary_role, "pk", None):
        profile.primary_role = primary_role
        profile.save(update_fields=["primary_role"])
    else:
        sync_user_role_groups(user, primary_role)

    return primary_role
