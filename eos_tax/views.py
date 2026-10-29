import time
from datetime import datetime

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.core.exceptions import PermissionDenied
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
from eos_tax.forms import TaxConfigurationForm, TaxRateFormSet, TaxRateReadOnlyFormSet
from eos_tax.models import TaxRate
from eos_tax.db.bot_audit import get_unaudited_mains
from eos_tax.db.bot_store import READINGS, get_stored_reports, settings_fingerprint
from eos_tax.db.bots import (
    find_characters,
    get_character_month,
)
from eos_tax.db.bot_signals import (
    get_clock_detail,
    get_rhythm_detail,
    get_run_detail,
)
from eos_tax.db.gm_transactions import get_gm_page, get_stored_gm_report, save_gm_note
from eos_tax.db.payments import (
    STATE_OPEN,
    STATE_PAID,
    STATE_PROGRESS,
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
from eos_tax import progress
from eos_tax.tasks import queue_bot_reports, queue_corporations, queue_gm_report
from eos_tax.util import get_dates, format_isk

logger = get_extension_logger(__name__)

# the overview's ?show= values; "all" applies no filter
OVERVIEW_FILTERS = (STATE_OPEN, STATE_PAID, STATE_PROGRESS, "all")

# what datetime() accepts, minus one at the top because the year filters are
# built as a half open range up to January of the following year
MIN_YEAR = 1
MAX_YEAR = 9998

# gm_bots_access opens the bots lists and GM Transactions alone, so every
# view of those two pages takes either the old permission or the new one
BOTS_GM_READ = ("eos_tax.admin_view", "eos_tax.gm_bots_access")
BOTS_GM_WRITE = ("eos_tax.manage_settings", "eos_tax.gm_bots_access")


def any_permission_required(perms, raise_exception=False):
    """permission_required with one of perms instead of all of them."""
    def check(user):
        if any(user.has_perm(perm) for perm in perms):
            return True
        if raise_exception:
            raise PermissionDenied
        return False

    return user_passes_test(check)


@login_required
@any_permission_required(("eos_tax.basic_access", "eos_tax.gm_bots_access"))
def index(request):
    # the menu entry points here; without basic_access there is no overview,
    # and the login redirect would only send them back
    if not request.user.has_perm("eos_tax.basic_access"):
        return redirect("eos_tax:bots")

    dates = get_dates()
    characters = get_all_characters_from_user(user=request.user)
    corps = get_all_corps_for_user(characters)
    # outstanding only by default, like eos-invoices' overview: a corp
    # officer lands here to see what can be collected now. ?paid=1 is the
    # link of the old two-button toggle, kept so a bookmark still shows
    # everything it showed before
    show = request.GET.get("show")
    if show not in OVERVIEW_FILTERS:
        show = "all" if request.GET.get("paid") == "1" else STATE_OPEN

    website_data = get_website_data(dates=dates, admin=request.user.has_perm('eos_tax.admin_view'), corps=corps)
    # told apart from "nothing owed at all" before the filter narrows it,
    # so the empty state can say which of the two it is
    has_any_data = bool(website_data)

    if show != "all":
        website_data = [row for row in website_data if row["state"] == show]

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
        "show": show,
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
@any_permission_required(BOTS_GM_READ)
def gm_transactions(request):
    """Characters with a GM transaction in their journal, or a wallet below zero."""
    stored = get_stored_gm_report()

    if stored is None:
        queue_gm_report()
        # an eager Celery - the tests - has found them by now
        stored = get_stored_gm_report()

    context = {
        "title": _("GM Transactions"),
        "version": VERSION,
        "pending": stored is None,
        "js_config": {
            "searchLabel": _("Search:"),
            "searchPlaceholder": _("Character, Corporation or Main"),
        },
    }
    if stored is not None:
        context.update(get_gm_page(stored))

    return render(request, "eos_tax/gm-transactions.html", context)


@login_required
@any_permission_required(BOTS_GM_READ)
# a 403, not the login redirect: fetched by a script, like settings_recalculate
@any_permission_required(BOTS_GM_WRITE, raise_exception=True)
@require_POST
def gm_transactions_recalculate(request):
    """Queues the GM job alone, not the tax run it normally comes with.

    "queued" is False while a run of it is still waiting or going - the
    bar shows that one.
    """
    return JsonResponse({"queued": queue_gm_report()})


@login_required
# a 403, not the login redirect: fetched by gm-transactions.js. Read access
# alone - whoever reads the page may annotate it, the user's choice
@any_permission_required(BOTS_GM_READ, raise_exception=True)
@require_POST
def gm_transactions_note(request):
    """Stores the note of one row; answers {"text": <as stored>}."""
    try:
        character_id = int(request.POST.get("character_id", ""))
        entry_id = int(request.POST.get("entry_id", ""))
    except ValueError:
        return HttpResponseBadRequest("character_id and entry_id must be numbers")

    try:
        text = save_gm_note(character_id, entry_id, request.POST.get("text", ""), request.user)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))

    return JsonResponse({"text": text})


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
    # admin_view reads the page, only manage_settings writes it - a POST
    # without it is refused here, not merely left without a save button
    can_manage = request.user.has_perm("eos_tax.manage_settings")

    if request.method == "POST" and not can_manage:
        raise PermissionDenied

    if request.method == "POST":
        # before the form exists: validating it already writes the posted
        # values into `config`, and a fingerprint taken after that would
        # never differ from the saved one
        before = settings_fingerprint(config)
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

            # the months the reader is most likely to look at next; any
            # other month notices the change when it is opened
            if settings_fingerprint(config) != before:
                queue_bot_reports(_previous_and_running_month())

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
    elif can_manage:
        form = TaxConfigurationForm(instance=config)
        rates = TaxRateFormSet(queryset=schedule)
    else:
        form = TaxConfigurationForm(instance=config)
        rates = TaxRateReadOnlyFormSet(queryset=schedule)
        for each in [form, *rates]:
            for field in each.fields.values():
                field.disabled = True

    now = datetime.now()

    context = {
        "title": _("Settings"),
        "version": VERSION,
        "form": form,
        "rates": rates,
        "can_manage": can_manage,
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
        "member_added_gross": format_isk(breakdown["member_added_gross"]),
        "unaudited_characters": [
            {**character, "isk": format_isk(character["gross"])}
            for character in breakdown["unaudited_characters"]
        ],
        "amount_to_pay": format_isk(breakdown["amount_to_pay"]),
        "by_type": [
            {**row, "sum": format_isk(row["sum"])}
            for row in breakdown["by_type"]
        ],
        "amount_paid": (
            format_isk(breakdown["amount_paid"])
            if breakdown["amount_paid"] is not None
            else ""
        ),
        "payments": [
            {**payment, "amount": format_isk(payment["amount"])}
            for payment in breakdown["payments"]
        ],
        # the sign stays with paid_difference for the template to branch on
        "isk_paid_difference": format_isk(abs(breakdown["paid_difference"])),
    }


@login_required
@permission_required("eos_tax.admin_view")
# a 403 rather than the login redirect of the pages: this is fetched by a
# script, which would otherwise swap the login page into the result
@permission_required("eos_tax.manage_settings", raise_exception=True)
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
        corporations = list(
            EveCorporationInfo.objects.filter(
                alliance__alliance_id__in=config.alliance_ids()
            ).values_list("corporation_id", "corporation_name")
        )

        queue_corporations(corporations, [(month, year)], progress.MANUAL)

        return render(request, "eos_tax/partials/recalculate-queued.html", {
            "count": len(corporations),
        })

    try:
        corp_id = int(corp_id)
    except ValueError:
        return HttpResponseBadRequest("corp_id must be an integer or 'all'")

    # a run of one, so the bar on another admin's page shows it as well
    corp_name = (
        EveCorporationInfo.objects.filter(corporation_id=corp_id)
        .values_list("corporation_name", flat=True).first()
        or str(corp_id)
    )
    run_id = progress.start_run(progress.MANUAL, [
        {"corp_id": corp_id, "corp_name": corp_name, "month": month, "year": year},
    ])
    with progress.tracked(run_id, corp_id, month, year) as outcome:
        outcome["result"] = update_corp(corp_id=corp_id, month=month, year=year)

    breakdown = _breakdown_for_display(outcome["result"])

    return render(request, "eos_tax/partials/recalculate-result.html", {
        "breakdown": breakdown,
    })


@login_required
@any_permission_required(BOTS_GM_READ)
def progress_state(request):
    """The runs for the progress bar; polled while one of them is going.

    "now" is the server's clock: the page tells a run that started after it
    was loaded from one it already shows the result of, and the browser's
    own clock may be minutes off.
    """
    runs = progress.get_runs()
    # the tax runs list every corporation with its outcome - beyond the two
    # pages gm_bots_access opens
    if not request.user.has_perm("eos_tax.admin_view"):
        runs = [run for run in runs if run["kind"] in (progress.BOTS, progress.GM)]

    return JsonResponse({"now": time.time(), "runs": runs})


@login_required
@any_permission_required(BOTS_GM_READ)
# taking a run off hides it from every admin, so it is a write as well
@any_permission_required(BOTS_GM_WRITE, raise_exception=True)
@require_POST
def progress_dismiss(request, run_id):
    """Takes a finished run off the bar - for every admin, not only this one."""
    runs = progress.get_runs()
    # gm_bots_access does not see the tax runs, so it cannot take one off
    if not request.user.has_perm("eos_tax.manage_settings") and any(
        run["id"] == run_id and run["kind"] not in (progress.BOTS, progress.GM)
        for run in runs
    ):
        raise PermissionDenied

    if any(run["id"] == run_id and not run["complete"] for run in runs):
        # a run still going would come back on the next poll of anyone else
        return HttpResponseBadRequest("the run is still going")

    progress.withdraw(run_id)

    return JsonResponse({"ok": True})


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
@any_permission_required(BOTS_GM_READ)
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
@any_permission_required(BOTS_GM_READ)
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

    reports = _stored_reports(selected, ["hours"])
    report = reports["hours"] if reports else {
        "listed": False, "groups": [], "stats": {}, "computed_at": None,
    }
    stats = report["stats"]
    # a visible marker beats digging through logs once the journal grows -
    # the job's time now, which is what the journal growing slows down
    stats["slow"] = stats.get("seconds_total", 0) > 2

    context = {
        "title": _("Bots"),
        "version": VERSION,
        "selected_month": month,
        "pending": reports is None,
        "listed": report["listed"],
        "groups": report["groups"],
        "groups_shown": stats.get("groups_shown", 0),
        "groups_total": stats.get("groups_total", 0),
        "computed_at": report["computed_at"],
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


@login_required
@any_permission_required(BOTS_GM_READ)
@any_permission_required(BOTS_GM_WRITE, raise_exception=True)
@require_POST
def bots_recalculate(request):
    """Queues the bots job of one month alone - see
    gm_transactions_recalculate."""
    try:
        selected = datetime.strptime(request.POST.get("month", ""), "%Y-%m")
    except ValueError:
        return HttpResponseBadRequest("month must be YYYY-MM")

    # the readings build the range up to the following month, as in
    # _selected_month
    if not MIN_YEAR <= selected.year <= MAX_YEAR:
        return HttpResponseBadRequest(f"year must be between {MIN_YEAR} and {MAX_YEAR}")

    return JsonResponse({
        "queued": bool(queue_bot_reports([(selected.month, selected.year)])),
    })


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
    "audit": _("Without current audit"),
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


# What renders each fetched tab. Kept beside the view rather than in the
# template so an unknown name is a 404 here instead of an empty page there.
BOT_SIGNALS = {
    "runs": "eos_tax/partials/bot-runs.html",
    "rhythm": "eos_tax/partials/bot-rhythm.html",
    "clock": "eos_tax/partials/bot-clock.html",
    # not a reading of its own: the characters of the four above whom
    # corptools no longer watches, picked out of their stored lists
    "audit": "eos_tax/partials/bot-audit.html",
}


def _previous_and_running_month():
    now = datetime.now()
    previous = (now.month - 1, now.year) if now.month > 1 else (12, now.year - 1)

    return [previous, (now.month, now.year)]


def _stored_reports(selected, signals):
    """The month's stored lists, or None while the job computes them.

    A missing or outdated list queues the job rather than being computed
    here - half a minute is more than a page should take, and more than a
    proxy in front of it may wait.
    """
    reports = get_stored_reports(selected.year, selected.month, signals)

    if reports is None:
        queue_bot_reports([(selected.month, selected.year)])
        # an eager Celery - the tests - has computed them by now
        reports = get_stored_reports(selected.year, selected.month, signals)

    return reports


@login_required
@any_permission_required(BOTS_GM_READ)
def bot_signal(request, signal):
    """One sub tab of the bots page, as a fragment.

    The tabs fetch these when they are opened. The lists come from the
    job; fetching them one at a time still keeps a visit that never leaves
    the first tab from loading four more.
    """
    if signal not in BOT_SIGNALS:
        raise Http404(signal)

    selected = _selected_month(request)
    month = f"{selected.year}-{selected.month:02d}"

    if signal == "audit":
        reports = _stored_reports(selected, list(READINGS))
        report = get_unaudited_mains(reports) if reports else None
    else:
        reports = _stored_reports(selected, [signal])
        report = reports[signal] if reports else None

    if report is None:
        return render(request, "eos_tax/partials/bot-pending.html")

    _remember_groups(request, month, signal, report["groups"])

    return render(request, BOT_SIGNALS[signal], {
        "listed": report["listed"],
        "groups": report["groups"],
        "stats": report["stats"],
        "computed_at": report["computed_at"],
        "selected_month": month,
    })


# The same three detections, read for one character instead of for everyone.
BOT_SIGNAL_DETAILS = {
    "runs": ("eos_tax/partials/bot-run-detail.html", get_run_detail),
    "rhythm": ("eos_tax/partials/bot-rhythm-detail.html", get_rhythm_detail),
    "clock": ("eos_tax/partials/bot-clock-detail.html", get_clock_detail),
}


@login_required
@any_permission_required(BOTS_GM_READ)
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
