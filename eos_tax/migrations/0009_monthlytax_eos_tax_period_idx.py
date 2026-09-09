"""Index the period. Separate from the constraint on purpose.

MariaDB cannot roll DDL back, so two schema changes in one migration leave the
first one behind when the second fails. This one cannot fail on data.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("eos_tax", "0008_single_holding_corporation"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="monthlytax",
            index=models.Index(fields=["year", "month"], name="eos_tax_period_idx"),
        ),
    ]
