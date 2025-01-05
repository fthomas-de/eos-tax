from datetime import datetime
from dateutil.relativedelta import relativedelta

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry  

from eos_tax.models import MonthlyTax
from eos_tax.app_settings import LAST_MONTH, CURRENT_MONTH, TAX_CORPORATIONS, USE_REASON

from allianceauth.services.hooks import get_extension_logger

DONATION_TYPES = ["player_donation", "corporation_account_withdrawal"]
logger = get_extension_logger(__name__)

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

def get_eve_alliance_id(id:int):
    alliance = EveAllianceInfo.objects.filter(id=id).first()
    if alliance:
        return alliance.alliance_id

def corp_has_payed(corp_id:int, month:int, year:int):
    
    amount_to_pay = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).values('tax_value').first()
    if not amount_to_pay:
        return False
    else:
        amount_to_pay = float(amount_to_pay['tax_value'])

    if USE_REASON:
        payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, reason=f"{corp_id}/{month}/{year}", amount=amount_to_pay).values('id').all()
    else:
        payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, amount=amount_to_pay).values('id').all()
    payed = len(payments) > 0

    if payed:
        logger.info(f"corp_has_payed: Payment found ({amount_to_pay}): {get_corp_name(corp_id)} ({corp_id}) for {month}/{year}")
    else:
        logger.info(f"corp_has_payed: No Payment found ({amount_to_pay}): {get_corp_name(corp_id)} ({corp_id}) for {month}/{year}")

    return payed
