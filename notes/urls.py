from django.urls import path

from . import views

urlpatterns = [
    path("", views.note_list, name="dashboard"),
    path("notes/create/", views.note_create, name="note_create"),
    path("notes/<int:note_id>/delete/", views.note_delete, name="note_delete"),
]
