from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from user.views import RegisterView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("consultation/", include("consultation.urls")),
    path("profile/", include("user.urls")),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/register/", RegisterView.as_view(), name="register"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
