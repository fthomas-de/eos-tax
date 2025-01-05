from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.app_settings import TAX_RATE
from eos_tax.db_connector import get_website_data
from eos_tax.util import get_dates

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    dates = get_dates()
    website_data = get_website_data(dates=dates)
    context = {"title":"Taxes to pay: " + str(TAX_RATE*100) + "%", "website_data":website_data }
    return render(request, "eos_tax/index.html", context)
