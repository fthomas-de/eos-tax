from datetime import datetime

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.dates import MONTHS_3
from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from allianceauth.framework.api.user import get_all_characters_from_user

from eos_tax import VERSION
from eos_tax.app_settings import get_config
from eos_tax.forms import TaxConfigurationForm, TaxRateFormSet
from eos_tax.models import TaxRate
from eos_tax.db_connector import (
    get_all_corps_for_user,
    get_bot_report,
    get_statistics_alliances,
    get_statistics_series,
    get_statistics_years,
    get_tax_corp,
    get_website_data,
)
from eos_tax.util import get_dates, get_amount_to_pay

logger = get_extension_logger(__name__)

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    dates = get_dates()
    characters = get_all_characters_from_user(user=request.user)
    corps = get_all_corps_for_user(characters)
    website_data = get_website_data(dates=dates, admin=request.user.has_perm('eos_tax.admin_view'), corps=corps)
    now = datetime.now()
    # round, not int: 0.29 * 100 lands on 28.999... in binary floating point
    current_rate = round(get_config().rate_for(now.year, now.month) * 100)
    context = {"title": _("Taxes to pay: %(rate)s%%") % {"rate": current_rate}, "website_data":website_data, "version":VERSION, "tax_corp":get_tax_corp(corps)}
    return render(request, "eos_tax/index.html", context)


@login_required
@permission_required("eos_tax.admin_view")
def statistics(request):
    years = get_statistics_years()
    context = {
        "title": _("Statistics"),
        "version": VERSION,
        "years": years,
        "alliances": get_statistics_alliances(),
        "selected_year": years[0] if years else "",
    }
    return render(request, "eos_tax/statistics.html", context)


@login_required
@permission_required("eos_tax.admin_view")
def statistics_data(request):
    """Series for one year, refetched by the chart whenever a filter changes."""
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponseBadRequest("year must be an integer")

    alliance = request.GET.get("alliance") or None
    if alliance is not None:
        try:
            alliance = int(alliance)
        except ValueError:
            return HttpResponseBadRequest("alliance must be an integer")

    return JsonResponse({
        "year": year,
        "alliance_id": alliance,
        "labels": [str(MONTHS_3[month]) for month in range(1, 13)],
        "series": get_statistics_series(year, alliance),
    })


@login_required
@permission_required("eos_tax.admin_view")
def settings(request):
    config = get_config()
    schedule = TaxRate.objects.all()

    if request.method == "POST":
        form = TaxConfigurationForm(request.POST, instance=config)
        rates = TaxRateFormSet(request.POST, queryset=schedule)

        # validate both before branching, or the second form never gets to
        # show its errors when the first one already failed
        form_ok = form.is_valid()
        rates_ok = rates.is_valid()

        if form_ok and rates_ok:
            form.save()
            rates.save()
            messages.success(request, _("Settings saved."))

            return redirect("eos_tax:settings")
    else:
        form = TaxConfigurationForm(instance=config)
        rates = TaxRateFormSet(queryset=schedule)

    context = {
        "title": _("Settings"),
        "version": VERSION,
        "form": form,
        "rates": rates,
    }
    return render(request, "eos_tax/settings.html", context)


def _selected_month(request):
    """Month from the picker, falling back to the running one."""
    try:
        return datetime.strptime(request.GET.get("month", ""), "%Y-%m")
    except ValueError:
        return datetime.now()


@login_required
@permission_required("eos_tax.admin_view")
def bots(request):
    config = get_config()
    selected = _selected_month(request)

    report = get_bot_report(selected.year, selected.month)
    stats = report["stats"]
    # a visible marker beats digging through logs once the journal grows
    stats["slow"] = stats["seconds_total"] > 2

    context = {
        "title": _("Bots"),
        "version": VERSION,
        "selected_month": selected.strftime("%Y-%m"),
        "candidates": report["candidates"],
        "longest_days": report["longest_days"],
        "stats": stats,
        "min_hours": config.bot_min_hours_per_day,
        "min_days": config.bot_min_days_per_month,
    }
    return render(request, "eos_tax/bots.html", context)
