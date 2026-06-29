from django.db import models

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("basic_access", "Can view his corp data"), ("admin_view", "Can view all data"))


class MonthlyTax(models.Model):
    corp_id = models.IntegerField(verbose_name="Corporation ID", blank=False)
    month = models.IntegerField(verbose_name="Taxed month", blank=False, default=0)
    year = models.IntegerField(verbose_name="Taxed year", blank=False, default=0)
    corp_name = models.CharField(verbose_name="Corporation name", max_length=254, blank=True, default='')
    tax_value = models.BigIntegerField(verbose_name="Tax value", blank=False, default=0)
    tax_percentage = models.FloatField(verbose_name="Tax percentage", blank=False, default=0)
    payed = models.BooleanField(verbose_name="Payed", default=False)
