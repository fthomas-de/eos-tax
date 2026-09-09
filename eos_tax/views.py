from datetime import datetime

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dates import MONTHS_3, WEEKDAYS_ABBR
from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from allianceauth.framework.api.user import get_all_characters_from_user

from eos_tax import VERSION
from eos_tax.app_settings import get_config
from eos_tax.forms import TaxConfigurationForm, TaxRateFormSet
from eos_tax.models import TaxRate
from eos_tax.db_connector import (
    ACTIVE_HOUR_MIN_ENTRIES,
    find_characters,
    get_corp_tax_changes,
    get_corp_tax_detail,
    get_all_corps_for_user,
    get_bot_report,
    get_character_month,
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


def _selected_year(request):
    """Year from the picker, falling back to the running one."""
    try:
        return int(request.GET.get("year", ""))
    except ValueError:
        return datetime.now().year



@login_required
@permission_required("eos_tax.admin_view")
def tax_changes(request):
    """Corporations whose ingame tax rate moved during the year."""
    year = _selected_year(request)
    report = get_corp_tax_changes(year)

    context = {
        "title": _("Corp Tax Changes"),
        "version": VERSION,
        "year": year,
        "years": get_statistics_years(),
        "rows": report["rows"],
        "stats": report["stats"],
    }
    return render(request, "eos_tax/tax-changes.html", context)


@login_required
@permission_required("eos_tax.admin_view")
def tax_change_detail(request, corp_id):
    """The daily curve behind one corporation."""
    year = _selected_year(request)
    detail = get_corp_tax_detail(corp_id, year)

    context = {
        "title": detail["corp_name"],
        "version": VERSION,
        "year": year,
        "years": get_statistics_years(),
        "detail": detail,
        "series": [
            {"day": day["day"].isoformat(),
             "rate": round(day["rate"] * 100, 3),
             "payouts": day["payouts"],
             "systems": day["systems"]}
            for day in detail["days"]
        ],
    }
    return render(request, "eos_tax/tax-change-detail.html", context)


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
def bot_detail(request, character_id):
    """One character's month, hour by hour, as a calendar."""
    selected = _selected_month(request)
    detail = get_character_month(character_id, selected.year, selected.month)

    context = {
        "title": detail["character_name"],
        "version": VERSION,
        "selected_month": selected.strftime("%Y-%m"),
        "detail": detail,
        # Django translates these itself, keyed 0 for Monday
        "weekdays": [WEEKDAYS_ABBR[index] for index in range(7)],
        "min_entries": ACTIVE_HOUR_MIN_ENTRIES,
    }
    return render(request, "eos_tax/bot-detail.html", context)


@login_required
@permission_required("eos_tax.admin_view")
def bots(request):
    config = get_config()
    selected = _selected_month(request)

    month = selected.strftime("%Y-%m")
    wanted = request.GET.get("character", "").strip()
    matches = find_characters(wanted)

    # one hit means the name was meant, so do not make them click it again
    if len(matches) == 1:
        detail = reverse("eos_tax:bot_detail", args=[matches[0]["eve_id"]])

        return redirect(f"{detail}?month={month}")

    report = get_bot_report(selected.year, selected.month)
    stats = report["stats"]
    # a visible marker beats digging through logs once the journal grows
    stats["slow"] = stats["seconds_total"] > 2

    context = {
        "title": _("Bots"),
        "version": VERSION,
        "selected_month": month,
        "candidates": report["candidates"],
        "longest_days": report["longest_days"],
        "stats": stats,
        "min_hours": config.bot_min_hours_per_day,
        "min_days": config.bot_min_days_per_month,
        "wanted": wanted,
        "matches": matches,
    }
    return render(request, "eos_tax/bots.html", context)
