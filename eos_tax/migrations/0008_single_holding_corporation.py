"""Narrow the holding corporation from many to one.

Order matters here: the new field has to exist and the old relation has to
survive long enough to be read, or the configured corporation is dropped on
the way. Django's generated order would have removed it first.
"""

import django.db.models.deletion
from django.db import migrations, models


def carry_over_holding_corporation(apps, schema_editor):
    TaxConfiguration = apps.get_model("eos_tax", "TaxConfiguration")

    for config in TaxConfiguration.objects.all():
        holding = config.tax_corporations.order_by("corporation_id").first()

        if holding is None:
            continue

        dropped = config.tax_corporations.exclude(pk=holding.pk)
        if dropped.exists():
            names = sorted(dropped.values_list("corporation_name", flat=True))
            print(
                f"  eos_tax: keeping {holding.corporation_name} as holding corporation, "
                f"dropping {names}"
            )

        config.tax_corporation = holding
        config.save(update_fields=["tax_corporation"])


class Migration(migrations.Migration):

    dependencies = [
        ("eos_tax", "0007_taxrate"),
        ("eveonline", "0025_remove_evecharacter_last_updated_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="taxconfiguration",
            name="tax_corporation",
            field=models.ForeignKey(
                blank=True,
                help_text="The single corporation that receives the tax payments.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="eveonline.evecorporationinfo",
                verbose_name="Holding corporation",
            ),
        ),
        migrations.RunPython(
            carry_over_holding_corporation, migrations.RunPython.noop
        ),
        migrations.RemoveField(
            model_name="taxconfiguration",
            name="tax_corporations",
        ),
    ]
