from django.urls import path

from . import views

app_name = "eos_tax"

urlpatterns = [
    path("", views.index, name="index"),
    path("statistics/", views.statistics, name="statistics"),
    path("statistics/data/", views.statistics_data, name="statistics_data"),
    path("settings/", views.settings, name="settings"),
    path("settings/recalculate/", views.settings_recalculate, name="settings_recalculate"),
    path("bots/", views.bots, name="bots"),
    path("bots/<int:character_id>/", views.bot_detail, name="bot_detail"),
    # the sub tabs of the bots page, fetched one at a time when opened
    path("bots/signal/<slug:signal>/", views.bot_signal, name="bot_signal"),
    # the same three readings for one character, behind the tabs of its
    # detail page
    path(
        "bots/signal/<slug:signal>/<int:character_id>/",
        views.bot_signal_detail,
        name="bot_signal_detail",
    ),
    path("tax-changes/", views.tax_changes, name="tax_changes"),
    path("tax-changes/<int:corp_id>/", views.tax_change_detail, name="tax_change_detail"),
]
