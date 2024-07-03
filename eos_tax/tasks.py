from celery import shared_task

from itertools import product

from allianceauth.services.hooks import get_extension_logger
from allianceauth.eveonline.models import EveCorporationInfo

from eos_tax.db_connector import update_corp
from eos_tax.app_settings import TAX_ALLIANCES
from eos_tax.util import get_dates, get_eve_allaince_id

logger = get_extension_logger(__name__)

# Create your tasks here


# Example Task
@shared_task
def run_update_alliance():
    #alliance_ids = [a.alliance_id for a in EveAllianceInfo.objects.filter(alliance_id__in=TAX_ALLIANCES).all()]
    corporation_info = { 
        x.corporation_id:x.corporation_name for x in EveCorporationInfo.objects.filter().all() 
            if get_eve_allaince_id(x.alliance_id) in TAX_ALLIANCES}
    dates = get_dates()
    #print(corporation_info)
    #print(dates)
    # check if corp in alliance 
    for corp_id in corporation_info.keys():
        for month, year in dates:
            # split for parallel processing
            run_update_corporation.delay(corp_id=corp_id, month=month, year=year)

@shared_task
def run_update_corporation(corp_id:int, month: int = -1, year: int = -1):
    update_corp(corp_id=corp_id, month=month, year=year)