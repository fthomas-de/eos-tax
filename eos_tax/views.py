from datetime import datetime

from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.shortcuts import redirect, render
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.dates import MONTHS_3, WEEKDAYS_ABBR
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from allianceauth.eveonline.models import EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from allianceauth.framework.api.user import get_all_characters_from_user

from eos_tax import VERSION
from eos_tax.app_settings import get_config
from eos_tax.forms import TaxConfigurationForm, TaxRateFormSet
from eos_tax.models import TaxRate
from eos_tax.db.bots import (
    find_characters,
    get_bot_report,
    get_character_month,
)
from eos_tax.db.bot_signals import (
    get_clock_detail,
    get_clock_offset,
    get_daily_profile,
    get_rhythm_detail,
    get_run_detail,
    get_unbroken_runs,
)
from eos_tax.db.payments import (
    get_all_corps_for_user,
    get_tax_corp,
    get_website_data,
    update_corp,
)
from eos_tax.db.shared import alts_of
from eos_tax.db.statistics import (
    get_statistics_alliances,
    get_statistics_series,
    get_statistics_years,
)
from eos_tax.db.tax_changes import get_corp_tax_changes, get_corp_tax_detail
from eos_tax.tasks import run_update_corporation
from eos_tax.util import get_dates, format_isk

logger = get_extension_logger(__name__)

# what datetime() accepts, minus one at the top because the year filters are
# built as a half open range up to January of the following year
MIN_YEAR = 1
MAX_YEAR = 9998

@login_required
@permission_required("eos_tax.basic_access")
def index(request):
    dates = get_dates()
    characters = get_all_characters_from_user(user=request.user)
    corps = get_all_corps_for_user(characters)
    # outstanding only by default, like eos-invoices' overview - ?paid=1
    # brings the paid rows back rather than needing a second page
    include_paid = request.GET.get("paid") == "1"

    website_data = get_website_data(dates=dates, admin=request.user.has_perm('eos_tax.admin_view'), corps=corps)
    # told apart from "nothing owed at all" before the filter narrows it,
    # so the empty state can say which of the two it is
    has_any_data = bool(website_data)

    if not include_paid:
        website_data = [row for row in website_data if not row["payed"]]

    # the rate of the month the rows below are for - the first of the
    # configured months, which is the payable one when both are shown - and
    # not the running month's, which the table was not calculated with
    now = datetime.now()
    shown_month, shown_year = dates[0] if dates else (now.month, now.year)
    # one decimal, because 7.5 % rounded to a whole number reads as 8 %;
    # floatformat -1 drops the decimal when there is none and writes the
    # separator the reader's language uses. Rounded first: 0.29 * 100 lands
    # on 28.999... in binary floating point
    shown_rate = floatformat(
        round(get_config().rate_for(shown_year, shown_month) * 100, 1), -1
    )
    context = {
        "title": _("Taxes to pay: %(rate)s%%") % {"rate": shown_rate},
        "website_data": website_data,
        "include_paid": include_paid,
        "has_any_data": has_any_data,
        "version": VERSION,
        "tax_corp": get_tax_corp(corps),
        # what the page's own script needs; a static file cannot reach the
        # catalogue, so the strings travel to it as data
        "js_config": {
            "searchLabel": _("Corporation:"),
            "searchPlaceholder": _("Filter by corporation name"),
        },
    }
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
        "js_config": {
            "dataUrl": reverse("eos_tax:statistics_data"),
            "text": {
                "loading": _("Loading…"),
                "empty": _("No data for this selection."),
                "error": _("Could not load the statistics."),
                "corporations": _("corporations"),
                "other": _("Other"),
                "shown": _("{shown} of {total} corporations drawn"),
                "covered": _("{value} of the tax covered"),
                "income": _("{value} ISK income"),
                "tax": _("{value} ISK tax"),
            },
        },
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
    """Year from the picker, falling back to the running one.

    The range matters as much as the type: the value goes on to build
    datetime(year + 1, 1, 1), which refuses anything outside year 1 to 9999,
    so a hand written ?year=9999 would raise below instead of here.
    """
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return datetime.now().year

    if not MIN_YEAR <= year <= MAX_YEAR:
        return datetime.now().year

    return year



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
        "js_config": {
            "searchLabel": _("Search:"),
            "searchPlaceholder": _("Corporation name, or a rate such as 0 or 100"),
        },
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
        # the two words the columns above are headed with - the tooltip used
        # to spell them out in English while the headers were translated
        "js_config": {
            "axis": _("Share of the bounty in percent"),
            "payouts": _("Payouts"),
            "systems": _("Systems"),
        },
    }
    return render(request, "eos_tax/tax-change-detail.html", context)


# Every bot-detection field starts this way; used only to decide which tab
# reopens after a failed save. The template groups the fields itself, so this
# is not a second copy of that grouping - just the one bit a redisplay needs.
BOT_FIELD_PREFIX = "bot_"


@login_required
@permission_required("eos_tax.admin_view")
def settings(request):
    config = get_config()
    schedule = TaxRate.objects.all()
    active_tab = "tax"

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

        # a bot-only error must reopen the Bot tab, or the page looks like it
        # silently dropped the change instead of rejecting it. A tax error -
        # on the form or on the rate schedule - keeps the default Tax tab,
        # even when a bot field also failed: the plain tabs here cannot show
        # both panes' errors at once, and a tax error is never allowed to
        # hide behind a tab that is not open.
        bot_only = (
            form.errors
            and all(name.startswith(BOT_FIELD_PREFIX) for name in form.errors)
            and not any(rates.errors)
            and not rates.non_form_errors()
        )
        active_tab = "bot" if bot_only else "tax"
    else:
        form = TaxConfigurationForm(instance=config)
        rates = TaxRateFormSet(queryset=schedule)

    now = datetime.now()

    context = {
        "title": _("Settings"),
        "version": VERSION,
        "form": form,
        "rates": rates,
        "active_tab": active_tab,
        "corporations": EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=config.alliance_ids()
        ).order_by("corporation_name"),
        "recalculate_month": now.month,
        "recalculate_year": now.year,
        "js_config": {
            "recalculateUrl": reverse("eos_tax:settings_recalculate"),
            "loading": _("Calculating…"),
            "error": _("Could not recalculate this month."),
        },
    }
    return render(request, "eos_tax/settings.html", context)


def _breakdown_for_display(breakdown):
    """The recalculate log's ISK figures, grouped the way format_isk groups
    them everywhere else in the app - the raw ints stay in update_corp's
    return value for whatever else ends up testing or reading it."""
    if not breakdown["ok"]:
        return breakdown

    return {
        **breakdown,
        "tax_value": format_isk(breakdown["tax_value"]),
        "gross_income": format_isk(breakdown["gross_income"]),
        "amount_to_pay": format_isk(breakdown["amount_to_pay"]),
        "by_type": [
            {**row, "sum": format_isk(row["sum"])}
            for row in breakdown["by_type"]
        ],
    }


@login_required
@permission_required("eos_tax.admin_view")
@require_POST
def settings_recalculate(request):
    """Recalculates one Corporation or every configured one, on demand.

    The periodic task only ever touches the previous and the running month;
    this is how any other month gets a second pass - a journal that just
    finished importing, or a rate that was just corrected. One Corporation
    runs synchronously and comes back with the arithmetic behind its figure;
    every Corporation is queued the same way the periodic task queues them,
    since running dozens synchronously would time the request out.
    """
    config = get_config()

    try:
        month = int(request.POST.get("month", ""))
        year = int(request.POST.get("year", ""))
    except ValueError:
        return HttpResponseBadRequest("month and year must be integers")

    if not 1 <= month <= 12:
        return HttpResponseBadRequest("month must be between 1 and 12")

    # the month range ends at the first of the following month, which
    # datetime refuses past the year 9999 - a 500 here, and for "all" one
    # failing Celery subtask per Corporation
    if not MIN_YEAR <= year <= MAX_YEAR:
        return HttpResponseBadRequest(f"year must be between {MIN_YEAR} and {MAX_YEAR}")

    corp_id = request.POST.get("corp_id", "all")

    if corp_id == "all":
        corp_ids = list(
            EveCorporationInfo.objects.filter(
                alliance__alliance_id__in=config.alliance_ids()
            ).values_list("corporation_id", flat=True)
        )

        for cid in corp_ids:
            run_update_corporation.delay(corp_id=cid, month=month, year=year)

        return render(request, "eos_tax/partials/recalculate-queued.html", {
            "count": len(corp_ids),
        })

    try:
        corp_id = int(corp_id)
    except ValueError:
        return HttpResponseBadRequest("corp_id must be an integer or 'all'")

    breakdown = _breakdown_for_display(update_corp(corp_id=corp_id, month=month, year=year))

    return render(request, "eos_tax/partials/recalculate-result.html", {
        "breakdown": breakdown,
    })


def _selected_month(request):
    """Month from the picker, falling back to the running one.

    Range checked for the same reason as _selected_year: strptime accepts
    9999-12, and the month range built from it would not.
    """
    try:
        selected = datetime.strptime(request.GET.get("month", ""), "%Y-%m")
    except ValueError:
        return datetime.now()

    if not MIN_YEAR <= selected.year <= MAX_YEAR:
        return datetime.now()

    return selected


@login_required
@permission_required("eos_tax.admin_view")
def bot_detail(request, character_id):
    """One character's month, hour by hour, as a calendar."""
    config = get_config()
    selected = _selected_month(request)
    detail = get_character_month(character_id, selected.year, selected.month)

    context = {
        "title": detail["character_name"],
        "version": VERSION,
        "selected_month": selected.strftime("%Y-%m"),
        "detail": detail,
        # Django translates these itself, keyed 0 for Monday
        "weekdays": [WEEKDAYS_ABBR[index] for index in range(7)],
        "min_entries": config.bot_hours_min_entries,
        # handed over by the list the reader clicked through from, so this
        # page does not start a reading of its own to find out
        "family": _family_for(
            request, character_id, selected.strftime("%Y-%m")
        ),
        # the month travels in the url so a tab opened after the form was
        # submitted fetches the month on screen, not the running one
        "js_config": {
            "signals": {
                name: (
                    reverse(
                        "eos_tax:bot_signal_detail", args=[name, character_id]
                    )
                    + f"?month={selected.strftime('%Y-%m')}"
                )
                for name in BOT_SIGNAL_DETAILS
            },
            "loading": _("Loading…"),
            "error": _("Could not load this view."),
        },
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
        "groups": report["groups"],
        "groups_shown": report["groups_shown"],
        "groups_total": report["groups_total"],
        "stats": stats,
        "min_hours": config.bot_min_hours_per_day,
        "min_days": config.bot_min_days_per_month,
        "wanted": wanted,
        "matches": matches,
        # the month travels in the url, so a tab opened after the form was
        # submitted fetches the month on screen rather than the running one
        "js_config": {
            "signals": {
                name: f"{reverse('eos_tax:bot_signal', args=[name])}?month={month}"
                for name in BOT_SIGNALS
            },
            "loading": _("Loading…"),
            "error": _("Could not load this view."),
        },
    }

    _remember_groups(request, month, "hours", report["groups"])

    return render(request, "eos_tax/bots.html", context)


# What the list the reader came from already knew about a main.
#
# Each reading walks the whole month for the whole alliance, so the character
# page must not start one just to fill a dropdown - that is the cost the tabs
# were split up to avoid. The grouping the reader was looking at is carried
# forward instead: it is already on screen when they click a name.
SESSION_FAMILY = "eos_tax_family"

# Only for the heading of that dropdown, so it says which of the four lists
# the assessments beside the names came from. The tabs carry their own copies
# of these words; sharing one dictionary between a view and four templates
# would be the tail wagging the dog.
BOT_SIGNAL_LABELS = {
    "hours": _("Hours per day"),
    "runs": _("Unbroken runs"),
    "rhythm": _("Against the Corporation"),
    "clock": _("Off the Corporation clock"),
}


def _remember_groups(request, month, signal, groups):
    """Keep this grouping for whichever character page is opened next.

    Groups of one are left out: a dropdown listing nobody but the character
    already on screen is a button that does nothing.
    """
    index = {}
    families = []

    for group in groups:
        if group["count"] < 2:
            continue

        for row in group["characters"]:
            index[str(row["character_id"])] = len(families)

        families.append({
            "main": group["main_name"],
            "characters": [
                {
                    "id": row["character_id"],
                    "name": row["character_name"],
                    "level": row["level"],
                }
                for row in group["characters"]
            ],
        })

    request.session[SESSION_FAMILY] = {
        "month": month,
        "signal": signal,
        "index": index,
        "families": families,
    }


def _remembered_family(request, character_id, month):
    """The main's other characters, as the list that led here saw them.

    Nothing when the reader did not come from a list, or came from one for a
    different month - a stale grouping beside a fresh month would be worse
    than no grouping, because it would look current.
    """
    remembered = request.session.get(SESSION_FAMILY) or {}

    if remembered.get("month") != month:
        return None

    position = (remembered.get("index") or {}).get(str(character_id))

    try:
        family = remembered["families"][position]
    except (KeyError, IndexError, TypeError):
        return None

    others = [
        member for member in family["characters"]
        if member["id"] != character_id
    ]

    if not others:
        return None

    return {
        "main": family["main"],
        "signal": BOT_SIGNAL_LABELS.get(remembered.get("signal"), ""),
        "characters": others,
    }


def _family_for(request, character_id, month):
    """Who else is on this account, with assessments where they are known.

    Two sources, in that order. The grouping the reader clicked through from
    carries an assessment per character and costs nothing, but it is only
    there when they came from a list - and it holds only the characters that
    list mentioned.

    Arriving cold, from a bookmark or the search box, Alliance Auth still
    knows who belongs together. That answer has no assessments in it, because
    producing one means reading the whole month for the whole alliance, which
    is the cost the tabs were split up to avoid. A jump list without badges is
    worth more than no jump list.
    """
    remembered = _remembered_family(request, character_id, month)

    if remembered:
        return remembered

    parsed = datetime.strptime(month, "%Y-%m")
    family = alts_of(character_id, parsed.year, parsed.month)

    if not family or not family["characters"]:
        return None

    return {
        "main": family["main"],
        # no reading to name, so the dropdown says what it is instead
        "signal": "",
        "characters": family["characters"],
    }


# Which reading of the month each tab shows, and what renders it. Kept beside
# the view rather than in the template so an unknown name is a 404 here
# instead of an empty page there.
BOT_SIGNALS = {
    "runs": ("eos_tax/partials/bot-runs.html", get_unbroken_runs),
    "rhythm": ("eos_tax/partials/bot-rhythm.html", get_daily_profile),
    "clock": ("eos_tax/partials/bot-clock.html", get_clock_offset),
}


@login_required
@permission_required("eos_tax.admin_view")
def bot_signal(request, signal):
    """One sub tab of the bots page, as a fragment.

    The tabs fetch these when they are opened. Three of the four readings
    would otherwise be computed on every visit to the page, and most visits
    only ever look at the first.
    """
    if signal not in BOT_SIGNALS:
        raise Http404(signal)

    template, report_for = BOT_SIGNALS[signal]
    selected = _selected_month(request)
    report = report_for(selected.year, selected.month)

    month = f"{selected.year}-{selected.month:02d}"
    _remember_groups(request, month, signal, report["groups"])

    return render(request, template, {
        "rows": report["rows"],
        "longest": report.get("longest", []),
        "groups": report["groups"],
        "stats": report["stats"],
        "selected_month": month,
    })


# The same three detections, read for one character instead of for everyone.
BOT_SIGNAL_DETAILS = {
    "runs": ("eos_tax/partials/bot-run-detail.html", get_run_detail),
    "rhythm": ("eos_tax/partials/bot-rhythm-detail.html", get_rhythm_detail),
    "clock": ("eos_tax/partials/bot-clock-detail.html", get_clock_detail),
}


@login_required
@permission_required("eos_tax.admin_view")
def bot_signal_detail(request, signal, character_id):
    """One detection, read for one character, as a fragment.

    Fetched by the tabs of the character page the same way the list page
    fetches its own - three of the four readings are never looked at on most
    visits.
    """
    if signal not in BOT_SIGNAL_DETAILS:
        raise Http404(signal)

    template, detail_for = BOT_SIGNAL_DETAILS[signal]
    selected = _selected_month(request)
    detail = detail_for(character_id, selected.year, selected.month)

    return render(request, template, {
        "detail": detail,
        "character_id": character_id,
        "selected_month": f"{selected.year}-{selected.month:02d}",
    })
