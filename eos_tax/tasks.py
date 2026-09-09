from celery import shared_task

from allianceauth.services.hooks import get_extension_logger
from allianceauth.eveonline.models import EveCorporationInfo

from eos_tax.db_connector import update_corp
from eos_tax.app_settings import get_config
from eos_tax.util import get_dates

logger = get_extension_logger(__name__)

# Create your tasks here

# main task
@shared_task
def run_update_alliance():
    # one query for the whole list. Walking every corporation and resolving its
    # alliance one by one cost a query per corporation, which is the bulk of the
    # work once an alliance has its corporations registered in Alliance Auth.
    corporations = EveCorporationInfo.objects.filter(
        alliance__alliance_id__in=get_config().alliance_ids()
    ).values_list("corporation_id", "corporation_name")

    dates = get_dates()

    for corp_id, corp_name in corporations:
        for month, year in dates:
            logger.info(f"queueing: {corp_name} ({corp_id}), date: {month}/{year}")
            # split for parallel processing
            run_update_corporation.delay(corp_id=corp_id, month=month, year=year)

# helper task
@shared_task
def run_update_corporation(corp_id:int, month: int = -1, year: int = -1):
    update_corp(corp_id=corp_id, month=month, year=year)
