from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.db.models import Sum

from corptools.models import CorporationWalletJournalEntry  
from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.app_settings import LAST_MONTH, CURRENT_MONTH, TAX_ALLIANCES, TAX_TYPES, TAX_RATE

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    current_month = datetime.now().month
    current_year = datetime.now().year

    last_month = (datetime.now() - relativedelta(months=1)).month
    last_year = (datetime.now() - relativedelta(months=1)).year
    
    #corp = EveCorporationInfo.objects.get(corporation_id=corp_id)
    alliance_ids = [a.alliance_id for a in EveAllianceInfo.objects.filter(alliance_id__in=TAX_ALLIANCES).all()]

    corporation_info = { x.corporation_id:x.corporation_name for x in EveCorporationInfo.objects.filter().all()}
    tax_data_last_month = []
    if CURRENT_MONTH:
        tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=last_year, date__month=last_month).\
            values('tax_receiver_id').annotate(sum=Sum('amount')) 

        for tax in tax_data:
            if tax['sum']:
                print(tax['tax_receiver_id'], tax['sum'])

                tax_data_last_month.append({
                    "corporation_id":tax['tax_receiver_id'],
                    "corporation_name":corporation_info[tax['tax_receiver_id']],
                    "tax_value": str(f'{int(int(tax["sum"]) * TAX_RATE):,}').replace(',','.'),
                    "value": str(f'{int(tax["sum"]):,}').replace(',','.'),
                    "month":last_month,
                    "year":last_year
                })

    tax_data_current_month = []
    if LAST_MONTH:
        tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=current_year, date__month=current_month).\
            values('tax_receiver_id').annotate(sum=Sum('amount')) 

        for tax in tax_data:
            if tax['sum']:
                print(tax['tax_receiver_id'], tax['sum'])

                tax_data_current_month.append({
                    "corporation_id":tax['tax_receiver_id'],
                    "corporation_name":corporation_info[tax['tax_receiver_id']],
                    "tax_value": str(f'{int(int(tax["sum"]) * TAX_RATE):,}').replace(',','.'),
                    "value": str(f'{int(tax["sum"]):,}').replace(',','.'),
                    "month":current_month,
                    "year":current_year
                })

    context = {"title":"IGC Taxes (" + str(TAX_RATE*100) + "%)", "current_month":tax_data_current_month, "last_month":tax_data_last_month }
    return render(request, "eos_tax/index.html", context)
