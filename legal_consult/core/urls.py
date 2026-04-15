from django.urls import path

from .views import AboutView, ContactsView, HomeView, ServicesView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("about/", AboutView.as_view(), name="about"),
    path("services/", ServicesView.as_view(), name="services"),
    path("contacts/", ContactsView.as_view(), name="contacts"),
]
