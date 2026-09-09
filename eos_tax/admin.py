from django.contrib import admin

from solo.admin import SingletonModelAdmin

from eos_tax.forms import TaxConfigurationAdminForm, TaxRateAdminForm
from eos_tax.models import TaxConfiguration, TaxRate


@admin.register(TaxConfiguration)
class TaxConfigurationAdmin(SingletonModelAdmin):
    """Fallback editor, the same route corptools offers for its own config."""

    form = TaxConfigurationAdminForm
    filter_horizontal = ("tax_alliances", "corporation_blacklist")


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    form = TaxRateAdminForm
    list_display = ("valid_from", "rate")
    ordering = ("-valid_from",)
