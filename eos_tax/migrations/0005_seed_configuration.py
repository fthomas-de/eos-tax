"""Carry the local.py values into the database, once.

From here on the settings page is the only source of truth - editing local.py
has no further effect. Alliances and corporations Alliance Auth does not know
yet cannot be linked; those ids are printed so they can be added by hand.
"""

from decimal import Decimal

from django.conf import settings
from django.db import migrations

# django-solo addresses its singleton by a fixed primary key
SINGLETON_PK = 1


def seed_configuration(apps, schema_editor):
    TaxConfiguration = apps.get_model("eos_tax", "TaxConfiguration")
    MonthlyTax = apps.get_model("eos_tax", "MonthlyTax")
    EveAllianceInfo = apps.get_model("eveonline", "EveAllianceInfo")
    EveCorporationInfo = apps.get_model("eveonline", "EveCorporationInfo")

    if TaxConfiguration.objects.filter(pk=SINGLETON_PK).exists():
        return

    tax_rate = getattr(settings, "TAX_RATE", 1)

    config = TaxConfiguration.objects.create(
        pk=SINGLETON_PK,
        tax_rate=Decimal(str(tax_rate)),
        tax_types=getattr(settings, "TAX_TYPES", ["bounty_prizes"]),
        last_month=getattr(settings, "LAST_MONTH", False),
        current_month=getattr(settings, "CURRENT_MONTH", False),
        use_reason=getattr(settings, "USE_REASON", False),
    )

    def link(name, relation, queryset, wanted, label):
        """Link what Alliance Auth knows and name the ids it does not.

        The name is passed in rather than read off the manager: a forward
        many-to-many manager carries no `field` attribute.
        """
        found = list(queryset)
        relation.set(found)

        missing = set(wanted) - {getattr(entry, label) for entry in found}
        if missing:
            print(
                f"  eos_tax: {name} - unknown to Alliance Auth, "
                f"not linked: {sorted(missing)}"
            )

    alliance_ids = getattr(settings, "TAX_ALLIANCES", [])
    if alliance_ids:
        link(
            "tax_alliances",
            config.tax_alliances,
            EveAllianceInfo.objects.filter(alliance_id__in=alliance_ids),
            alliance_ids,
            "alliance_id",
        )

    holding_ids = getattr(settings, "TAX_CORPORATIONS", [])
    if holding_ids:
        link(
            "tax_corporations",
            config.tax_corporations,
            EveCorporationInfo.objects.filter(corporation_id__in=holding_ids),
            holding_ids,
            "corporation_id",
        )

    blacklist_ids = getattr(settings, "CORPORATION_BLACKLIST", [])
    if blacklist_ids:
        link(
            "corporation_blacklist",
            config.corporation_blacklist,
            EveCorporationInfo.objects.filter(corporation_id__in=blacklist_ids),
            blacklist_ids,
            "corporation_id",
        )

    # existing rows were calculated with whatever local.py said at the time,
    # which is the value we just seeded
    MonthlyTax.objects.filter(alliance_tax_rate=0).update(alliance_tax_rate=float(tax_rate))


class Migration(migrations.Migration):

    dependencies = [
        ("eos_tax", "0004_monthlytax_alliance_tax_rate_taxconfiguration"),
    ]

    operations = [
        migrations.RunPython(seed_configuration, migrations.RunPython.noop),
    ]
