from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/data/<int:year>/", views.dashboard_data, name="dashboard_data"),
    path("list/", views.diary_list, name="diary_list"),
    path("reports/", views.reports_table, name="reports_table"),
    path("reports/pdf/<int:year>/", views.reports_pdf, name="reports_pdf"),
    path("reports/csv/<int:year>/", views.reports_csv, name="reports_csv"),
    path("reports/year/<int:year>/", views.diary_year_report, name="diary_year_report"),
    path("new/", views.diary_create, name="diary_create"),
    path("directory/", views.offices_directory, name="directory"),
    path("diary/<int:pk>/", views.diary_detail, name="diary_detail"),
    path("diary/<int:pk>/edit/", views.diary_edit, name="diary_edit"),
    path("diary/<int:pk>/delete/", views.diary_delete, name="diary_delete"),
    path("diary/<int:pk>/movement/add/", views.movement_add, name="movement_add"),
    path("change-password/", views.change_password, name="change_password"),
]
