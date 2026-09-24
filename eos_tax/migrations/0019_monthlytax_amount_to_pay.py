"""amount_to_pay stops the amount to pay from being recalculated on every
page load, chart and payment check. Existing rows already carry every
ingredient the formula needs - tax_value, tax_percentage, alliance_tax_rate -
so this works the figure out for them once, here, instead of leaving the
field at its default and every reader falling back to a live calculation.

The backfill must not raise. On MariaDB the column is already added by the
time it runs and there is no rollback: a crash halfway leaves the column in
place with the migration unrecorded, and the next migrate then fails on the
duplicate column instead of retrying.
"""

from datetime import date

from django.db import migrations, models


def get_pve_income(tax_value: int, corp_tax: float) -> float:
    """Mirrors eos_tax.util.get_pve_income - copied rather than imported, so
    this migration keeps working if that function's shape ever changes."""
    if corp_tax == 0:
        return float(tax_value)

    return float(tax_value / (corp_tax / 100))


def backfill_amount_to_pay(apps, schema_editor):
    MonthlyTax = apps.get_model("eos_tax", "MonthlyTax")
    TaxRate = apps.get_model("eos_tax", "TaxRate")
    TaxConfiguration = apps.get_model("eos_tax", "TaxConfiguration")

    config = TaxConfiguration.objects.first()
    base_rate = float(config.tax_rate) if config else 0.0

    for row in MonthlyTax.objects.all():
        rate = row.alliance_tax_rate

        if not rate:
            # the same fallback the overview used at read time until now: the
            # newest schedule entry not after this row's month, or the base
            # rate when the schedule does not reach back that far. The model
            # defaults month and year to 0, and date() refuses those - such a
            # row has no month to look up, so it takes the base rate.
            scheduled = None
            if row.year >= 1 and 1 <= row.month <= 12:
                scheduled = (
                    TaxRate.objects.filter(valid_from__lte=date(row.year, row.month, 1))
                    .order_by("-valid_from")
                    .first()
                )
            rate = float(scheduled.rate) if scheduled else base_rate

        income = get_pve_income(row.tax_value, row.tax_percentage)
        row.amount_to_pay = int(income * rate)
        row.save(update_fields=["amount_to_pay"])


class Migration(migrations.Migration):

    dependencies = [
        ('eos_tax', '0018_alter_taxconfiguration_bot_clock_min_apart_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlytax',
            name='amount_to_pay',
            field=models.BigIntegerField(default=0, help_text='ISK owed to the alliance for this month, in whole ISK. Worked out from tax_value, tax_percentage and alliance_tax_rate whenever the row is written, and kept with them from then on - the page, the chart and the payment check read it rather than redoing the arithmetic.', verbose_name='Amount to pay'),
        ),
        migrations.RunPython(backfill_amount_to_pay, migrations.RunPython.noop),
    ]
