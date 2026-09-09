import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import product

from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)
from allianceauth.framework.api.evecharacter import (
    get_main_character_from_evecharacter,
)
from corptools.models import CorporationWalletJournalEntry, EveName
from django.db.models import Sum
from django.db.models.functions import ExtractHour, TruncDate

from eos_tax.models import MonthlyTax
from eos_tax.util import get_alliance_name, get_dates, format_isk, get_corp_name, corp_has_payed, get_amount_to_pay, get_pve_income, get_eve_alliance_id
from eos_tax.app_settings import get_config

from allianceauth.services.hooks import get_extension_logger
from eos_tax import __version__

logger = get_extension_logger(__name__)

    # examples: https://github.com/ppfeufer/allianceauth-afat/blob/master/afat/tasks.py   
    # tax_data = CorporationWalletJournalEntry.objects.filter(tax_receiver_id__in=corporation_info.keys(), ref_type__in=TAX_TYPES, date__year=y, date__month=m).\
    #       values('tax_receiver_id').annotate(sum=Sum('amount'))          
def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: float = -1, month: int = -1, year: int = -1, payed: bool = False, alliance_tax_rate: float = 0):
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    # corp_name is handed in by the caller; looking it up again cost a query
    # per corporation and month, for a log line
    logger.info(f"set_corp_tax: {corp_name or corp_id} ({corp_id}), tax_value: {format_isk(tax_value)} tax_percentage {tax_percentage} {month}/{year}")

    if selected_corp:
        selected_corp.corp_name=corp_name
        selected_corp.tax_value=tax_value
        selected_corp.tax_percentage=tax_percentage
        selected_corp.payed=payed
        selected_corp.alliance_tax_rate=alliance_tax_rate
        
        selected_corp.save()

    else:
        MonthlyTax.objects.create(
            corp_id=corp_id,
            corp_name=corp_name,
            tax_value=tax_value,
            tax_percentage=tax_percentage,
            month=month,
            year=year,
            payed=payed,
            alliance_tax_rate=alliance_tax_rate,
        )

def corp_tax_exists(corp_id: int, month: int = -1, year: int = -1) -> MonthlyTax:
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if selected_corp:
        return MonthlyTax
    
def get_website_data(dates: list = [], admin: bool = False, corps=[]):
    config = get_config()
    blacklist = config.blacklisted_corporation_ids()
    website_data = []
    for month, year in dates:
        # resolved once per month; the per row fallback used to read the
        # configuration again for every single row
        fallback_rate = config.rate_for(year, month)
        selected_corps = []
        if not admin:
            if corps:
                selected_corps = MonthlyTax.objects.filter(month=month, year=year, corp_id__in=corps).all()
        else:
            selected_corps = MonthlyTax.objects.filter(month=month, year=year).all()

        current_month = datetime.now().month
        current_day = datetime.now().day

        for selected_corp in selected_corps:
            if selected_corp.corp_id in blacklist:
                continue
            if ( current_month > selected_corp.month or ( current_month == 1 and selected_corp.month == 12 ) ) and current_day >= 2:
                reason_code = f"{selected_corp.corp_id}/{selected_corp.month}/{selected_corp.year}"

            else:
                reason_code = ""
        
            # rows written before the rate was stored per row carry a zero;
            # resolved once here so the column and the amount cannot drift
            applied_rate = selected_corp.alliance_tax_rate or fallback_rate

            amount_to_pay = get_amount_to_pay(
                selected_corp.tax_value,
                selected_corp.tax_percentage,
                applied_rate,
            )

            website_data.append({
                "corporation_id":selected_corp.corp_id,
                "corporation_name":selected_corp.corp_name,
                "isk_to_pay": format_isk(amount_to_pay),
                "isk_to_pay_value": int(amount_to_pay),
                "month":selected_corp.month,
                "year":selected_corp.year,
                "period": selected_corp.year * 100 + selected_corp.month,
                "corp_tax_rate":float("%.2f" % selected_corp.tax_percentage),
                # stored as a fraction, shown as a percentage like the corp tax
                "alliance_tax_rate":float("%.2f" % (applied_rate * 100)),
                "payed":selected_corp.payed,
                "reason":reason_code,
            })
    # unpaid first, then by corporation, then chronologically
    website_data.sort(key=lambda x: (x["payed"], x["corporation_name"], x["year"], x["month"]))

    return website_data

def update_corp(corp_id:int, month: int = -1, year: int = -1):
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if not corp_info:
        logger.warning(f"dbcon update_corp: unknown corporation {corp_id} - skipped")
        return

    corp_tax_rate = float("%.4f" % corp_info.tax_rate)
    logger.info(f"dbcon update_corp1: {corp_info.corporation_name} ({corp_id}): tax_rate {corp_tax_rate} - {month}/{year}")

    config = get_config()
    start, end = _month_range(year, month)

    # filter is on a single corp, so the whole month collapses into one sum
    tax_sum = CorporationWalletJournalEntry.objects.filter(
        tax_receiver_id=corp_id,
        ref_type__in=config.tax_types,
        date__gte=start,
        date__lt=end,
    ).aggregate(total=Sum("amount"))["total"]

    if not tax_sum:
        logger.info(f"dbcon update_corp2: {corp_info.corporation_name} ({corp_id}): no journal entries - {month}/{year}")
        return

    overall_ratted = int(tax_sum)
    payed = corp_has_payed(
        corp_id=corp_id,
        month=month,
        year=year,
        config=config,
        corp_name=corp_info.corporation_name,
    )
    logger.info(f"dbcon update_corp3: {corp_info.corporation_name} ({corp_id}): payed {payed} - {month}/{year}")
    set_corp_tax(
        corp_id=corp_id,
        corp_name=corp_info.corporation_name,
        tax_value=overall_ratted,
        tax_percentage=corp_tax_rate*100,
        month=month,
        year=year,
        payed=payed,
        alliance_tax_rate=config.rate_for(year, month),
    )

def get_all_corps_for_user(characters: list = []):
    corporation_ids = []
    for char in characters:
        if char.corporation_id:
            corporation_ids.append(char.corporation_id)
    return corporation_ids

def get_tax_corp(corps:list = []):
    # input: user corps
    logger.debug(corps)

    config = get_config()
    alliance_ids = config.alliance_ids()
    holding = config.tax_corporation

    # 1: get all tax_alliances, the user is in 
    tax_alliances = { 
        x.alliance_id for x in EveCorporationInfo.objects.filter(corporation_id__in=corps).all() 
            if get_eve_alliance_id(x.alliance_id) in alliance_ids}
    logger.debug(tax_alliances)

    if holding and holding.alliance_id in tax_alliances:
        return holding.corporation_name

# Validated categorical palette: eight slots that stay separable under colour
# vision deficiency on both a light and a dark surface. Past eight corporations
# hue alone stops working, so the line style carries part of the identity.
CHART_PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                       "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CHART_PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
                      "#d55181", "#008300", "#9085e9", "#e66767"]
CHART_DASHES = [[], [7, 4], [2, 3]]

# how many characters the bots page falls back to when nothing crosses the
# thresholds - enough to judge whether the thresholds fit, short enough to read
LONGEST_DAYS_LIMIT = 10


def get_statistics_years():
    """Years that carry data. There is no backfill, so this grows month by month."""
    return sorted(MonthlyTax.objects.values_list("year", flat=True).distinct(), reverse=True)


def _corporation_infos(corp_ids):
    return {
        info.corporation_id: info
        for info in EveCorporationInfo.objects.filter(
            corporation_id__in=corp_ids
        ).select_related("alliance")
    }


def _colour_slots():
    """One stable palette slot per corporation, derived from every corporation
    that has data - not from the filtered result. Switching year or alliance
    therefore never repaints the corporations that stay on screen."""
    corp_ids = sorted(set(MonthlyTax.objects.values_list("corp_id", flat=True)))
    return {corp_id: slot for slot, corp_id in enumerate(corp_ids)}


def get_statistics_alliances():
    """Configured alliances that have at least one taxed corporation."""
    corp_ids = MonthlyTax.objects.values_list("corp_id", flat=True).distinct()
    alliance_ids = get_config().alliance_ids()

    alliances = {}
    for info in _corporation_infos(corp_ids).values():
        alliance = info.alliance
        if alliance and alliance.alliance_id in alliance_ids:
            alliances[alliance.alliance_id] = alliance.alliance_name

    return [
        {"alliance_id": alliance_id, "alliance_name": name}
        for alliance_id, name in sorted(alliances.items(), key=lambda item: item[1].lower())
    ]


def get_statistics_series(year: int, alliance_id: int = None):
    """Monthly tax and gross PvE income per corporation for one year."""
    config = get_config()
    alliance_ids = config.alliance_ids()
    rows = MonthlyTax.objects.filter(year=year).exclude(
        corp_id__in=config.blacklisted_corporation_ids()
    )
    infos = _corporation_infos({row.corp_id for row in rows})
    slots = _colour_slots()
    # twelve lookups instead of one per row
    fallback_rates = {month: config.rate_for(year, month) for month in range(1, 13)}

    corps = {}
    for row in rows:
        info = infos.get(row.corp_id)
        alliance = info.alliance if info else None

        if not alliance or alliance.alliance_id not in alliance_ids:
            continue
        if alliance_id and alliance.alliance_id != alliance_id:
            continue
        if not 1 <= row.month <= 12:
            continue

        corp = corps.setdefault(row.corp_id, {
            "corp_id": row.corp_id,
            "name": row.corp_name or info.corporation_name,
            "alliance_name": alliance.alliance_name,
            # Alliance Auth keeps this from ESI, the same source Dotlan reads
            "members": info.member_count or 0,
            "tax": [0.0] * 12,
            "income": [0.0] * 12,
        })
        corp["tax"][row.month - 1] += get_amount_to_pay(
            row.tax_value,
            row.tax_percentage,
            row.alliance_tax_rate or fallback_rates[row.month],
        )
        corp["income"][row.month - 1] += get_pve_income(row.tax_value, row.tax_percentage)

    series = sorted(corps.values(), key=lambda corp: corp["name"].lower())
    for corp in series:
        slot = slots.get(corp["corp_id"], 0)
        corp["color_light"] = CHART_PALETTE_LIGHT[slot % len(CHART_PALETTE_LIGHT)]
        corp["color_dark"] = CHART_PALETTE_DARK[slot % len(CHART_PALETTE_DARK)]
        corp["dash"] = CHART_DASHES[(slot // len(CHART_PALETTE_LIGHT)) % len(CHART_DASHES)]
        corp["tax_total"] = round(sum(corp["tax"]))
        corp["income_total"] = round(sum(corp["income"]))
        corp["tax"] = [round(value) for value in corp["tax"]]
        corp["income"] = [round(value) for value in corp["income"]]

    return series


def _month_range(year: int, month: int):
    """Half open range for one month.

    date__month becomes EXTRACT(MONTH FROM date), which no index can serve;
    a range comparison can."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)

    return start, end


def _taxed_corporation_ids(config):
    """Corporations of the configured alliances, as far as Alliance Auth knows them."""
    return list(
        EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=config.alliance_ids()
        ).values_list("corporation_id", flat=True)
    )


def _main_characters(character_ids):
    """Main character name per character id, in one query.

    The relation chain is pre-loaded so Alliance Auth's helper does not fire
    three more queries per character.
    """
    characters = EveCharacter.objects.filter(
        character_id__in=character_ids
    ).select_related("character_ownership__user__profile__main_character")

    mains = {}
    for character in characters:
        main = get_main_character_from_evecharacter(character)
        if main:
            mains[character.character_id] = main.character_name

    return mains


def _row(character_id, days, contributed, config):
    suspicious = [
        day for day, hours in days.items() if len(hours) > config.bot_min_hours_per_day
    ]

    return {
        "character_id": character_id,
        "character_name": str(character_id),
        "main_name": "",
        "suspicious_days": len(suspicious),
        "active_days": len(days),
        "max_hours": max(len(hours) for hours in days.values()),
        "contributed": int(contributed or 0),
        "contributed_isk": format_isk(contributed or 0),
    }


def get_bot_report(year: int, month: int):
    """Characters whose taxed income looks automated, plus what the run cost.

    A day counts as suspicious once a character earned taxed income in more
    than bot_min_hours_per_day different hours of that day; the character is
    listed once more than bot_min_days_per_month such days pile up.

    When nothing crosses both thresholds the report falls back to the ten
    longest days of the month - an empty page says nothing about whether the
    thresholds are sensible, that list does.

    Days are cut on EVE time, not on the server locale - otherwise the boundary
    moves and a night of ratting is split across two days.
    """
    started = time.perf_counter()
    config = get_config()
    corp_ids = _taxed_corporation_ids(config)

    stats = {
        "buckets": 0,
        "characters": 0,
        "candidates": 0,
        "seconds_query": 0.0,
        "seconds_aggregate": 0.0,
        "seconds_total": 0.0,
    }

    def finish(candidates, longest_days):
        stats["candidates"] = len(candidates)
        stats["seconds_total"] = time.perf_counter() - started

        return {
            "candidates": candidates,
            "longest_days": longest_days,
            "stats": stats,
        }

    if not corp_ids or not config.tax_types:
        return finish([], [])

    start, end = _month_range(year, month)
    entries = CorporationWalletJournalEntry.objects.filter(
        ref_type__in=config.tax_types,
        tax_receiver_id__in=corp_ids,
        date__gte=start,
        date__lt=end,
    )

    # one row per character, day and hour - at most 24 per character and day,
    # so the grouping below stays small no matter how large the journal is
    query_started = time.perf_counter()
    buckets = list(
        entries.annotate(
            day=TruncDate("date", tzinfo=timezone.utc),
            hour=ExtractHour("date", tzinfo=timezone.utc),
        )
        # the name is resolved for the handful of shown rows further down;
        # joining it here widens the DISTINCT over the whole month
        .values("second_party_id", "day", "hour")
        .distinct()
    )
    contributed = {
        row["second_party_id"]: row["total"] or 0
        for row in entries.values("second_party_id").annotate(total=Sum("tax"))
    }
    stats["seconds_query"] = time.perf_counter() - query_started
    stats["buckets"] = len(buckets)

    aggregate_started = time.perf_counter()
    hours_per_day = defaultdict(lambda: defaultdict(set))
    for row in buckets:
        character_id = row["second_party_id"]
        if character_id is None:
            continue

        hours_per_day[character_id][row["day"]].add(row["hour"])

    stats["characters"] = len(hours_per_day)

    rows = [
        _row(character_id, days, contributed.get(character_id), config)
        for character_id, days in hours_per_day.items()
    ]

    candidates = [
        row for row in rows if row["suspicious_days"] > config.bot_min_days_per_month
    ]
    candidates.sort(key=lambda entry: (-entry["suspicious_days"], -entry["max_hours"]))

    longest_days = []
    if not candidates:
        longest_days = sorted(
            rows,
            key=lambda entry: (
                -entry["max_hours"],
                -entry["active_days"],
                -entry["contributed"],
            ),
        )[:LONGEST_DAYS_LIMIT]

    shown = candidates or longest_days
    shown_ids = [entry["character_id"] for entry in shown]
    names = dict(
        EveName.objects.filter(eve_id__in=shown_ids).values_list("eve_id", "name")
    )
    mains = _main_characters(shown_ids)

    for entry in shown:
        character_id = entry["character_id"]
        entry["character_name"] = names.get(character_id) or str(character_id)
        entry["main_name"] = mains.get(character_id, "")

    stats["seconds_aggregate"] = time.perf_counter() - aggregate_started

    return finish(candidates, longest_days)


def get_bot_candidates(year: int, month: int):
    """Just the candidates, for callers that do not care what the run cost."""
    return get_bot_report(year, month)["candidates"]
