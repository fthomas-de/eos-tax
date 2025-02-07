from datetime import datetime
from dateutil.relativedelta import relativedelta

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry  

from eos_tax.models import MonthlyTax
from eos_tax.app_settings import LAST_MONTH, CURRENT_MONTH, TAX_CORPORATIONS, USE_REASON, TAX_RATE

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
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if corp_info:
        return corp_info.corporation_name

def get_alliance_name(corp_id:int):
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if not corp_info:
        return
    
    alliance_info = EveAllianceInfo.objects.filter(id=corp_info.alliance_id).first()
    if alliance_info:
        return alliance_info.alliance_name

def get_eve_alliance_id(id:int):
    alliance = EveAllianceInfo.objects.filter(id=id).first()
    if alliance:
        return alliance.alliance_id

def get_amount_to_pay(tax_value:int, corp_tax:int):
    return int((tax_value/(corp_tax/100))*TAX_RATE)

def corp_has_payed(corp_id:int, month:int, year:int):
    
    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data:
        return False
    else:
        amount_to_pay = float(get_amount_to_pay(tax_data.tax_value, tax_data.tax_percentage))

    if USE_REASON:
        payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, reason__icontains=f"{corp_id}/{month}/{year}", amount__lte=amount_to_pay*-1).values('id').all()
        logger.info(f"1")
        if len(payments) == 0:
            payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, reason__icontains=f"{corp_id}/{month}/{year}", amount__gte=amount_to_pay).values('id').all()
            logger.info(f"2")
    else:
        payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, amount=amount_to_pay*-1).values('id').all()
        if len(payments) == 0:
            payments = CorporationWalletJournalEntry.objects.filter(second_party_id__in=TAX_CORPORATIONS, ref_type__in=DONATION_TYPES, amount=amount_to_pay).values('id').all()
    payed = len(payments) > 0

    if payed:
        logger.info(f"corp_has_payed: Payment found ({format_isk(amount_to_pay)}): from {get_corp_name(corp_id)} to holding corp {TAX_CORPORATIONS} for >{corp_id}/{month}/{year}<")
    else:
        logger.info(f"corp_has_payed: No Payment found ({format_isk(amount_to_pay)}): from {get_corp_name(corp_id)} to holding corp {TAX_CORPORATIONS} for >{corp_id}/{month}/{year}<")

    return payed
