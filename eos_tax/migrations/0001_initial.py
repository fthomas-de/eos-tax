# Generated by Django 4.2.13 on 2024-07-03 19:24

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='General',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'permissions': (('basic_access', 'Can access this app'),),
                'managed': False,
                'default_permissions': (),
            },
        ),
        migrations.CreateModel(
            name='MonthlyTax',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('corp_id', models.IntegerField(verbose_name='Corporation ID')),
                ('month', models.IntegerField(default=0, verbose_name='Taxed month')),
                ('year', models.IntegerField(default=0, verbose_name='Taxed year')),
                ('corp_name', models.CharField(blank=True, default='', max_length=254, verbose_name='Corporation name')),
                ('tax_value', models.BigIntegerField(default=0, verbose_name='Tax value')),
                ('tax_percentage', models.IntegerField(default=0, verbose_name='Tax percentage')),
            ],
        ),
    ]
