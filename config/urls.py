from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from django.views.decorators.http import require_POST

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    # Enforce POST for logout to avoid CSRF-prone GET logouts
    path("logout/", require_POST(auth_views.LogoutView.as_view()), name="logout"),
    path("", include("diary.urls")),
]
