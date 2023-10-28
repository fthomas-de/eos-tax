from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.db.models import Sum

from corptools.models import CorporationWalletJournalEntry  
from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.app_settings import LAST_MONTH, CURRENT_MONTH, TAX_ALLIANCES, TAX_TYPES, TAX_RATE
from eos_tax.models import EveSwaggerProviderWithTax


def format_isk(isk):
    return str(f'{int(isk):,}').replace(',','.')

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    esi = EveSwaggerProviderWithTax()

    website_data = []
    tax_data = []
    tax_rates = {}
    dates = []

    if not CURRENT_MONTH and not LAST_MONTH:
        return
    if LAST_MONTH:
        dates.append((datetime.now().month, datetime.now().year))
    if CURRENT_MONTH:
        dates.append(((datetime.now() - relativedelta(months=1)).month, (datetime.now() - relativedelta(months=1)).year))
    
    alliance_ids = [a.alliance_id for a in EveAllianceInfo.objects.filter(alliance_id__in=TAX_ALLIANCES).all()]
    corporation_info = { x.corporation_id:x.corporation_name for x in EveCorporationInfo.objects.filter().all()}

    for corp_id in corporation_info.keys():
        tax_rates[corp_id] = esi.get_corp_tax(corp_id)    
        break

    for (m, y) in dates:
    
        tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
            values('tax_receiver_id').annotate(sum=Sum('amount')) 

        for tax in tax_data:
            if tax['sum']:
                print("tax['tax_receiver_id'], tax['sum']", tax['tax_receiver_id'], tax['sum'])
                print("int(tax[sum]) / tax_rates[tax['tax_receiver_id']]", int(tax["sum"]) / tax_rates[tax['tax_receiver_id']])
                overall_ratted = int(tax["sum"]) / tax_rates[tax['tax_receiver_id']]
                isk_to_pay = overall_ratted * TAX_RATE
                print("isk to pay", isk_to_pay)
                print("tax_rates[tax['tax_receiver_id']]", tax_rates[tax['tax_receiver_id']])
                website_data.append({
                    "corporation_id":tax['tax_receiver_id'],
                    "corporation_name":corporation_info[tax['tax_receiver_id']],
                    "isk_to_pay": format_isk(isk_to_pay),
                    "month":m,
                    "year":y,
                    "corp_tax_rate":int(tax_rates[tax['tax_receiver_id']]*100)
                })

    context = {"title":"IGC Taxes (" + str(TAX_RATE*100) + "%)", "website_data":website_data }
    return render(request, "eos_tax/index.html", context)
