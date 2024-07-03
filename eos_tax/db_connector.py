from itertools import product

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry  
from django.db.models import Sum

from eos_tax.models import MonthlyTax, EveSwaggerProviderWithTax
from eos_tax.util import get_dates, format_isk, get_corp_name
from eos_tax.app_settings import TAX_TYPES, TAX_RATE

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

    # examples: https://github.com/ppfeufer/allianceauth-afat/blob/master/afat/tasks.py   
    # tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
    #       values('tax_receiver_id').annotate(sum=Sum('amount'))          
def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: int = -1, month: int = -1, year: int = -1):

    # exists: update
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    
    logger.info(f"Set Tax: {get_corp_name(corp_id)} ({corp_id}), tax_value: {format_isk(tax_value)} tax_percentage {tax_percentage} {month}/{year}")

    #print("tax_value", tax_value)
    if selected_corp:
        #print("update")
        selected_corp.corp_name=corp_name
        selected_corp.tax_value=tax_value
        selected_corp.tax_percentage=tax_percentage

        selected_corp.save()

    else:
        #print("create")
        return_value = MonthlyTax.objects.create(corp_id=corp_id, 
                                                 corp_name=corp_name,
                                                 tax_value=tax_value,
                                                 tax_percentage=tax_percentage,
                                                 month=month,
                                                 year=year)
        
        
    #print("return_value:", return_value)

def corp_tax_exists(corp_id: int, month: int = -1, year: int = -1) -> MonthlyTax:
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if selected_corp:
        return MonthlyTax
    
def get_website_data(dates: list = []):
    website_data = []
    for month, year in dates:
        selected_corps = MonthlyTax.objects.filter(month=month, year=year).all()

        for selected_corp in selected_corps:

            #print("tax_value", selected_corp.tax_value)
            #print("tax_percentage", selected_corp.tax_percentage)
            #print("TAX_RATE", TAX_RATE)

            website_data.append({
                "corporation_id":selected_corp.corp_id,
                "corporation_name":selected_corp.corp_name,
                "isk_to_pay": format_isk((selected_corp.tax_value/(selected_corp.tax_percentage/100))*TAX_RATE),
                "month":selected_corp.month,
                "year":selected_corp.year,
                "corp_tax_rate":selected_corp.tax_percentage
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
            #print("tax['sum']", tax['sum'])
            #print("tax['tax_receiver_id'], tax['sum']", tax['tax_receiver_id'], tax['sum'])
            #print("int(tax[sum]) / tax_rates[tax['tax_receiver_id']]", int(tax["sum"]) / tax_rates[tax['tax_receiver_id']])
            overall_ratted = int(tax["sum"]) #/ corp_tax_rate
            #isk_to_pay = overall_ratted * TAX_RATE
            #print("isk to pay", int(isk_to_pay))
            #print("tax_rates[tax['tax_receiver_id']]", tax_rates[tax['tax_receiver_id']])
                
        set_corp_tax(
            corp_id=corp_id, 
            corp_name=get_corp_name(corp_id), 
            tax_value=overall_ratted,
            tax_percentage=int(corp_tax_rate*100),
            month=month,
            year=year
        )

