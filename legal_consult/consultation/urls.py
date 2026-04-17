from django.urls import path

from .views import (
    AllSessionsView,
    ConsultationIndexView,
    CreateSessionView,
    SessionDetailView,
    SessionListView,
    assign_consultation,
    change_consultation_status,
    close_consultation,
    mark_consultation_requires_specialist,
    send_message_api,
)

app_name = "consultation"

urlpatterns = [
    path("", ConsultationIndexView.as_view(), name="index"),
    path("new/", CreateSessionView.as_view(), name="new_session"),
    path("sessions/", SessionListView.as_view(), name="session_list"),
    path("dashboard/", AllSessionsView.as_view(), name="dashboard"),
    path("session/<int:pk>/", SessionDetailView.as_view(), name="session_detail"),
    path("session/<int:pk>/assign/", assign_consultation, name="assign_consultation"),
    path("session/<int:pk>/status/", change_consultation_status, name="change_consultation_status"),
    path(
        "session/<int:pk>/requires-specialist/",
        mark_consultation_requires_specialist,
        name="mark_consultation_requires_specialist",
    ),
    path("session/<int:pk>/close/", close_consultation, name="close_consultation"),
    path("api/session/<int:pk>/message/", send_message_api, name="send_message_api"),
]
