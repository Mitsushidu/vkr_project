from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .roles import get_user_primary_role


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "user/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["primary_role"] = get_user_primary_role(self.request.user)
        return context
