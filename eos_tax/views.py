from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from allianceauth.framework.api.user import get_all_characters_from_user

from eos_tax import VERSION
from eos_tax.app_settings import TAX_RATE
from eos_tax.db_connector import get_all_corps_for_user, get_tax_corp, get_website_data
from eos_tax.util import get_dates, get_amount_to_pay

logger = get_extension_logger(__name__)

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    dates = get_dates()
    characters = get_all_characters_from_user(user=request.user)
    corps = get_all_corps_for_user(characters)
    website_data = get_website_data(dates=dates, admin=request.user.has_perm('eos_tax.admin_view'), corps=corps)
    context = {"title":"Taxes to pay: " + str(int(TAX_RATE*100)) + "%", "website_data":website_data, "version":VERSION, "tax_corp":get_tax_corp(corps)}
    return render(request, "eos_tax/index.html", context)
