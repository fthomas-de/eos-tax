from django.urls import path

from . import views

app_name = "eos_tax"

urlpatterns = [
    path("", views.index, name="index"),
]
