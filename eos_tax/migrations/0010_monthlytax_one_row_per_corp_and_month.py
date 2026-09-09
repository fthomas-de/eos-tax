"""One row per corporation and month.

The check runs first. Adding the constraint to data that already breaks it
fails halfway through with a database error that names one row and no way to
find the others, and on MariaDB there is no rollback to fall back on.
"""

from django.db import migrations, models
from django.db.models import Count

LISTED = 20


def refuse_duplicates(apps, schema_editor):
    """Stop before the constraint rather than during it."""
    MonthlyTax = apps.get_model("eos_tax", "MonthlyTax")

    duplicates = list(
        MonthlyTax.objects.values("corp_id", "year", "month")
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
        .order_by("-rows", "corp_id", "year", "month")
    )

    if not duplicates:
        return

    shown = "\n".join(
        f"    corporation {entry['corp_id']}: {entry['month']}/{entry['year']}, "
        f"{entry['rows']} rows"
        for entry in duplicates[:LISTED]
    )
    more = (
        f"\n    ... and {len(duplicates) - LISTED} more"
        if len(duplicates) > LISTED
        else ""
    )

    raise RuntimeError(
        f"eos_tax cannot add its uniqueness constraint: {len(duplicates)} "
        f"corporation and month combinations hold more than one row.\n"
        f"{shown}{more}\n"
        f"Decide which row to keep - they can differ in tax_value, payed and "
        f"alliance_tax_rate - then run the migration again. Nothing has been "
        f"changed."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("eos_tax", "0009_monthlytax_eos_tax_period_idx"),
    ]

    operations = [
        migrations.RunPython(refuse_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="monthlytax",
            constraint=models.UniqueConstraint(
                fields=("corp_id", "year", "month"),
                name="eos_tax_one_row_per_corp_and_month",
            ),
        ),
    ]
