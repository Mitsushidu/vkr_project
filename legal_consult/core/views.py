from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = "core/home.html"


class AboutView(TemplateView):
    template_name = "core/about.html"


class ServicesView(TemplateView):
    template_name = "core/services.html"


class ContactsView(TemplateView):
    template_name = "core/contacts.html"
