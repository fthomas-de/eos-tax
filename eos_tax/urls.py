from django.urls import path

from . import views

app_name = "eos_tax"

urlpatterns = [
    path("", views.index, name="index"),
    path("statistics/", views.statistics, name="statistics"),
    path("statistics/data/", views.statistics_data, name="statistics_data"),
    path("settings/", views.settings, name="settings"),
    path("bots/", views.bots, name="bots"),
]
