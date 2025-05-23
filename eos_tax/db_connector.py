from datetime import datetime
from itertools import product

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry  
from django.db.models import Sum

from eos_tax.models import MonthlyTax, EveSwaggerProviderWithTax
from eos_tax.util import get_alliance_name, get_dates, format_isk, get_corp_name, corp_has_payed, get_amount_to_pay, get_eve_alliance_id
from eos_tax.app_settings import CORPORATION_BLACKLIST, TAX_ALLIANCES, TAX_CORPORATIONS, TAX_TYPES, TAX_RATE

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

    # examples: https://github.com/ppfeufer/allianceauth-afat/blob/master/afat/tasks.py   
    # tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
    #       values('tax_receiver_id').annotate(sum=Sum('amount'))          
def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: float = -1, month: int = -1, year: int = -1, payed: bool = False):
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    logger.info(f"set_corp_tax: {get_corp_name(corp_id)} ({corp_id}), tax_value: {format_isk(tax_value)} tax_percentage {tax_percentage} {month}/{year}")

    if selected_corp:
        selected_corp.corp_name=corp_name
        selected_corp.tax_value=tax_value
        selected_corp.tax_percentage=tax_percentage
        selected_corp.payed=payed
        
        selected_corp.save()

    else:
        return_value = MonthlyTax.objects.create(corp_id=corp_id, 
                                                 corp_name=corp_name,
                                                 tax_value=tax_value,
                                                 tax_percentage=tax_percentage,
                                                 month=month,
                                                 year=year)

def corp_tax_exists(corp_id: int, month: int = -1, year: int = -1) -> MonthlyTax:
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if selected_corp:
        return MonthlyTax
    
def get_website_data(dates: list = [], admin: bool = False, corps=[]):
    website_data = []
    for month, year in dates:
        selected_corps = []
        if not admin:
            if corps:
                selected_corps = MonthlyTax.objects.filter(month=month, year=year, corp_id__in=corps).all()
        else:
            selected_corps = MonthlyTax.objects.filter(month=month, year=year).all()

        current_month = datetime.now().month
        current_day = datetime.now().day

        for selected_corp in selected_corps:
            if selected_corp.corp_id in CORPORATION_BLACKLIST:
                continue
            if current_month > selected_corp.month and current_day >= 2:
                reason_code = f"{selected_corp.corp_id}/{selected_corp.month}/{selected_corp.year}"

            else:
                reason_code = ""
        
            website_data.append({
                "corporation_id":selected_corp.corp_id,
                "corporation_name":selected_corp.corp_name,
                "isk_to_pay": format_isk(get_amount_to_pay(selected_corp.tax_value, selected_corp.tax_percentage)),
                "month":selected_corp.month,
                "year":selected_corp.year,
                "corp_tax_rate":float("%.2f" % selected_corp.tax_percentage),
                "payed":selected_corp.payed,
                "reason":reason_code,
            })
    try:
        s = sorted(website_data, key=lambda x: x["year"])
        s = sorted(website_data, key=lambda x: x["month"])
        s = sorted(website_data, key=lambda x: x["corporation_name"])
        s = sorted(website_data, key=lambda x: x["payed"])
    except (KeyError):
        pass

    return s

def update_corp(corp_id:int, month: int = -1, year: int = -1):
    tax_data = []
    esi = EveSwaggerProviderWithTax()
        
    corp_tax_rate = esi.get_corp_tax(corp_id) 
    tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id=corp_id, ref_type__in=TAX_TYPES, date__year=year, date__month=month).\
        values('tax_receiver_id').annotate(sum=Sum('amount'))

    for tax in tax_data:
        if tax['sum']:
            overall_ratted = int(tax["sum"])

        payed = corp_has_payed(corp_id=corp_id, month=month, year=year)
        logger.info(f"update_corp: {get_corp_name(corp_id)} ({corp_id}): payed {payed} - {month}/{year}")
        set_corp_tax(
            corp_id=corp_id, 
            corp_name=get_corp_name(corp_id), 
            tax_value=overall_ratted,
            tax_percentage=corp_tax_rate*100,
            month=month,
            year=year,
            payed=payed
        )

def get_all_corps_for_user(characters: list = []):
    corporation_ids = []
    for char in characters:
        if char.corporation_id:
            corporation_ids.append(char.corporation_id)
    return corporation_ids

def get_tax_corp(corps:list = []):
    # input: user corps
    logger.debug(corps)

    # 1: get all tax_alliances, the user is in 
    tax_alliances = { 
        x.alliance_id for x in EveCorporationInfo.objects.filter(corporation_id__in=corps).all() 
            if get_eve_alliance_id(x.alliance_id) in TAX_ALLIANCES}
    logger.debug(tax_alliances)

    tax_corp = [x.corporation_name for x in EveCorporationInfo.objects.filter(corporation_id__in=TAX_CORPORATIONS).all() 
                if x.alliance_id in tax_alliances ]
    logger.debug(tax_corp)

    if tax_corp:
        return tax_corp[0]