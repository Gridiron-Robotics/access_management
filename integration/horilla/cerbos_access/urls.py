from django.urls import path

from . import views

urlpatterns = [
    path("access/", views.access_list, name="cerbos-access-view"),
    path("access/<int:employee_id>/edit/", views.access_edit, name="cerbos-access-edit"),
    path("access/<int:employee_id>/preview/", views.access_preview, name="cerbos-access-preview"),
    path("api/access/principal/<int:employee_id>/", views.principal_api, name="cerbos-principal-api"),
]
