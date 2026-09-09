from django.urls import path

from . import views

app_name = "eos_tax"

urlpatterns = [
    path("", views.index, name="index"),
    path("statistics/", views.statistics, name="statistics"),
    path("statistics/data/", views.statistics_data, name="statistics_data"),
    path("settings/", views.settings, name="settings"),
    path("bots/", views.bots, name="bots"),
    path("bots/<int:character_id>/", views.bot_detail, name="bot_detail"),
    path("tax-changes/", views.tax_changes, name="tax_changes"),
    path("tax-changes/<int:corp_id>/", views.tax_change_detail, name="tax_change_detail"),
]
