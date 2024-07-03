from datetime import datetime
from dateutil.relativedelta import relativedelta

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.app_settings import LAST_MONTH, CURRENT_MONTH

def get_dates():

    dates = []

    if LAST_MONTH:
        dates.append(((datetime.now() - relativedelta(months=1)).month,(datetime.now() - relativedelta(months=1)).year))

    if CURRENT_MONTH:     
        dates.append((datetime.now().month, datetime.now().year))

    return dates

def format_isk(isk):
    return str(f'{int(isk):,}').replace(',','.')

def get_corp_name(corp_id:int):
    return EveCorporationInfo.objects.filter(corporation_id=corp_id).first().corporation_name

def get_eve_allaince_id(id:int):
    return EveAllianceInfo.objects.filter(id=id).first().alliance_id