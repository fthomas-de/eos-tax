from django.db import models

# Create your models here.
from corptools.models import CorporationWalletJournalEntry  

class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("basic_access", "Can access this app"),)


class MonthlyTax(models.Model):
    corp_id = models.IntegerField(verbose_name="Corporation ID")
    corp_name = models.CharField(verbose_name="Corporation name", max_length=254)
    tax_value = models.IntegerField(verbose_name="Tax value")
    tax_percentage = models.IntegerField(verbose_name="Tax percentage")
    month = models.IntegerField(verbose_name="Taxed month")
    year = models.IntegerField(verbose_name="Taxed year")
    

