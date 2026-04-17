from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from .forms import RegistrationForm
from .roles import ROLE_USER, assign_primary_role
from .roles import get_user_primary_role


class RegisterView(FormView):
    template_name = "registration/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("consultation:index")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("consultation:index")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        Group.objects.get_or_create(name=ROLE_USER)
        assign_primary_role(user, ROLE_USER)
        auth_login(self.request, user)
        messages.success(self.request, "Регистрация завершена. Вы вошли в систему.")
        return super().form_valid(form)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "user/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["primary_role"] = get_user_primary_role(self.request.user)
        return context
