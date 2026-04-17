from django.contrib import admin

from .models import UserProfile


MANAGE_USERS_PERMISSION = "user.can_manage_users"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "primary_role", "phone", "position")
    list_filter = ("primary_role",)
    search_fields = ("user__username", "user__email", "phone", "position")
    autocomplete_fields = ("user",)
    fields = ("user", "primary_role", "middle_name", "phone", "position")

    def has_module_permission(self, request):
        return super().has_module_permission(request) or request.user.has_perm(
            MANAGE_USERS_PERMISSION
        )

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or request.user.has_perm(
            MANAGE_USERS_PERMISSION
        )

    def has_add_permission(self, request):
        return super().has_add_permission(request) or request.user.has_perm(MANAGE_USERS_PERMISSION)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) or request.user.has_perm(
            MANAGE_USERS_PERMISSION
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) or request.user.has_perm(
            MANAGE_USERS_PERMISSION
        )

    def get_model_perms(self, request):
        permissions = super().get_model_perms(request)
        if request.user.has_perm(MANAGE_USERS_PERMISSION):
            permissions.update({"view": True, "add": True, "change": True, "delete": True})
        return permissions
