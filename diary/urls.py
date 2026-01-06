from django.urls import path
from . import views

urlpatterns = [
    path("", views.diary_list, name="diary_list"),
    path("new/", views.diary_create, name="diary_create"),
    path("diary/<int:pk>/", views.diary_detail, name="diary_detail"),
    path("diary/<int:pk>/movement/add/", views.movement_add, name="movement_add"),
]
