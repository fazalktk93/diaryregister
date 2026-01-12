from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from django.views.decorators.http import require_POST

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    # Password reset functionality
    path("password-reset/", auth_views.PasswordResetView.as_view(template_name="registration/password_reset.html"), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"), name="password_reset_confirm"),
    path("password-reset-complete/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
    # Enforce POST for logout to avoid CSRF-prone GET logouts
    path("logout/", require_POST(auth_views.LogoutView.as_view()), name="logout"),
    path("", include("diary.urls")),
]
