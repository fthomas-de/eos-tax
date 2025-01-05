from itertools import product

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry  
from django.db.models import Sum

from eos_tax.models import MonthlyTax, EveSwaggerProviderWithTax
from eos_tax.util import get_dates, format_isk, get_corp_name, corp_has_payed
from eos_tax.app_settings import TAX_TYPES, TAX_RATE

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

    # examples: https://github.com/ppfeufer/allianceauth-afat/blob/master/afat/tasks.py   
    # tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
    #       values('tax_receiver_id').annotate(sum=Sum('amount'))          
def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: int = -1, month: int = -1, year: int = -1, payed: bool = False):
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
    
def get_website_data(dates: list = []):
    website_data = []
    for month, year in dates:
        selected_corps = MonthlyTax.objects.filter(month=month, year=year).all()

        for selected_corp in selected_corps:
            website_data.append({
                "corporation_id":selected_corp.corp_id,
                "corporation_name":selected_corp.corp_name,
                "isk_to_pay": format_isk((selected_corp.tax_value/(selected_corp.tax_percentage/100))*TAX_RATE),
                "month":selected_corp.month,
                "year":selected_corp.year,
                "corp_tax_rate":selected_corp.tax_percentage,
                "payed":selected_corp.payed,
                "reason":f"{selected_corp.corp_id}/{selected_corp.month}/{selected_corp.year}"
            })

    return website_data

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
            tax_percentage=int(corp_tax_rate*100),
            month=month,
            year=year,
            payed=payed
        )