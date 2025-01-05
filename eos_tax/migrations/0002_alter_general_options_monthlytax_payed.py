# Generated by Django 4.2.13 on 2025-01-04 23:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eos_tax', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='general',
            options={'default_permissions': (), 'managed': False, 'permissions': (('basic_access', 'Can view his corp data'), ('admin_view', 'Can view all data'))},
        ),
        migrations.AddField(
            model_name='monthlytax',
            name='payed',
            field=models.BooleanField(default=False, verbose_name='Payed'),
        ),
    ]
