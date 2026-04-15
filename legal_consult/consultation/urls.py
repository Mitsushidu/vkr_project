from django.urls import path

from .views import (
    AllSessionsView,
    ConsultationIndexView,
    CreateSessionView,
    SessionDetailView,
    SessionListView,
    send_message_api,
)

app_name = "consultation"

urlpatterns = [
    path("", ConsultationIndexView.as_view(), name="index"),
    path("new/", CreateSessionView.as_view(), name="new_session"),
    path("sessions/", SessionListView.as_view(), name="session_list"),
    path("dashboard/", AllSessionsView.as_view(), name="dashboard"),
    path("session/<int:pk>/", SessionDetailView.as_view(), name="session_detail"),
    path("api/session/<int:pk>/message/", send_message_api, name="send_message_api"),
]
