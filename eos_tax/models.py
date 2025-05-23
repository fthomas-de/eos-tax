from django.db import models

# Create your models here.
from bravado.exception import HTTPNotFound
from corptools.models import CorporationWalletJournalEntry
from allianceauth.eveonline.providers import EveSwaggerProvider, ObjectNotFound

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
    tax_value = models.BigIntegerField (verbose_name="Tax value", blank=False, default=0)
    tax_percentage = models.IntegerField(verbose_name="Tax percentage", blank=False, default=0)
    payed = models.BooleanField(verbose_name="Payed", default=False)

    

class EveSwaggerProviderWithTax(EveSwaggerProvider):
    def get_corp_tax(self, corp_id: int):
        """Fetch corporation from ESI."""
        try:
            data = self.client.Corporation.get_corporations_corporation_id(corporation_id=corp_id).result()
            return float("%.4f" % data['tax_rate'])
        
        except HTTPNotFound:
            raise ObjectNotFound(corp_id, 'corporation')



