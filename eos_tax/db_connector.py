import time
import re
from collections import defaultdict
from functools import lru_cache
from math import sqrt
from statistics import median
from datetime import date, datetime, timedelta, timezone
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
from django.db.models import Count, Q, Sum
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
    
def is_payable(month: int, year: int, today=None) -> bool:
    """Whether that month is over far enough to be transferred.

    The reason code appears from the second of the following month, which is
    when the last journal entries of the closed month have arrived. The badge
    and the overview both ask this, so they cannot disagree about what is due.
    """
    today = today or datetime.now()

    if today.day < 2:
        return False

    return year * 100 + month < today.year * 100 + today.month


def get_open_payment_count(dates: list, admin: bool = False, corps=None) -> int:
    """How many rows are waiting to be paid, for the menu badge.

    Rendered on every page of the site, so this counts in the database rather
    than building the overview and measuring it.
    """
    payable = [(month, year) for month, year in dates if is_payable(month, year)]

    if not payable or (not admin and not corps):
        return 0

    periods = Q()
    for month, year in payable:
        periods |= Q(month=month, year=year)

    rows = MonthlyTax.objects.filter(periods, payed=False)

    if not admin:
        rows = rows.filter(corp_id__in=corps)

    return rows.exclude(
        corp_id__in=get_config().blacklisted_corporation_ids()
    ).count()


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

        for selected_corp in selected_corps:
            if selected_corp.corp_id in blacklist:
                continue

            reason_code = (
                f"{selected_corp.corp_id}/{selected_corp.month}/{selected_corp.year}"
                if is_payable(selected_corp.month, selected_corp.year)
                else ""
            )
        
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

# Line styles still carry part of the identity past the first few
# corporations, so hue never has to do the job alone.
CHART_DASHES = [[], [7, 4], [2, 3]]

# How far a colour may stray towards black or white before it stops reading on
# one of the two surfaces. The cube reaches into both corners.
CHART_MIN_LIGHTNESS = 0.22
CHART_MAX_LIGHTNESS = 0.78

# How close red, green and blue may sit before the colour is a grey. The cube
# has a full diagonal of them and they read as each other on a chart.
CHART_MIN_SPREAD = 40


def _lightness(rgb):
    return (max(rgb) + min(rgb)) / 510


def _hue(rgb):
    red, green, blue = (channel / 255 for channel in rgb)
    high, low = max(red, green, blue), min(red, green, blue)
    span = high - low

    if not span:
        return 0.0

    if high == red:
        return ((green - blue) / span % 6) * 60
    if high == green:
        return ((blue - red) / span + 2) * 60

    return ((red - green) / span + 4) * 60


def _saturation(rgb):
    high, low = max(rgb) / 255, min(rgb) / 255
    span = high - low

    if not span:
        return 0.0

    return span / (2 - high - low) if (high + low) > 1 else span / (high + low)


def _oklab(rgb):
    """Perceptual coordinates, so a distance means what the eye sees.

    Plain RGB distance says #008000 and #00a000 are as far apart as #000080 and
    #0000a0, which is nonsense - the eye separates greens far better than blues.
    """
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)

    long = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)

    return (
        0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short,
    )


def _distance(first, second):
    return sqrt(sum((a - b) ** 2 for a, b in zip(_oklab(first), _oklab(second)))) * 100


def _cube_colours(count):
    """`count` colours, each the midpoint of one subcube of the RGB cube.

    Cutting every axis into the same number of segments gives cuts**3 cubes, so
    the number of colours grows cubically - three cuts already cover 27
    corporations, four cover 64.
    """
    if count < 1:
        return []

    cuts = 1
    while cuts ** 3 < count:
        cuts += 1

    usable = []
    while True:
        piece = 255 // cuts
        candidates = []

        for index in range(cuts ** 3):
            blue = (index % cuts) * piece + piece // 2
            green = (index // cuts % cuts) * piece + piece // 2
            red = (index // (cuts * cuts) % cuts) * piece + piece // 2
            rgb = (red, green, blue)

            if max(rgb) - min(rgb) < CHART_MIN_SPREAD:
                continue  # the grey diagonal
            if not CHART_MIN_LIGHTNESS <= _lightness(rgb) <= CHART_MAX_LIGHTNESS:
                continue  # too near black or white to read on one of the themes

            candidates.append(rgb)

        if len(candidates) >= count:
            usable = candidates
            break

        cuts += 1  # dropping greys and extremes cost us the headroom

    # Farthest first: start from the most vivid mid-lightness cube, then keep
    # taking whichever colour sits furthest from everything already taken. The
    # answer sorts by hue instead, which is right for rendering the palette as
    # a gradient strip and wrong here - it puts near neighbours on consecutive
    # slots, which is exactly the pair a reader has to tell apart.
    chosen = [
        max(usable, key=lambda rgb: _saturation(rgb) * (1 - abs(_lightness(rgb) - 0.5)))
    ]
    remaining = [rgb for rgb in usable if rgb != chosen[0]]

    while len(chosen) < count:
        pick = max(
            remaining,
            key=lambda rgb: min(_distance(rgb, taken) for taken in chosen),
        )
        chosen.append(pick)
        remaining.remove(pick)

    return chosen


@lru_cache(maxsize=8)
def _chart_palette(count):
    """`count` hex colours, no two of them alike.

    Cached: the answer is the same for a given count, and picking farthest
    first costs count squared distance comparisons.
    """
    return tuple(
        f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in _cube_colours(count)
    )

# how many characters the bots page falls back to when nothing crosses the
# thresholds - enough to judge whether the thresholds fit, short enough to read
LONGEST_DAYS_LIMIT = 10

# An hour counts as active once the same taxed ref_type appears in it twice.
# A single entry is noise - a stray bounty tick, one ess payout - and used to
# make the hour count all the same.
#
# The game pays out about every 20 minutes to someone ratting without a break,
# so an hour of uninterrupted play should really hold three entries. Two is the
# deliberately tolerant setting: play gets interrupted, and a false negative
# costs less than accusing a player.
ACTIVE_HOUR_MIN_ENTRIES = 2

# The matrix paints one hue at a share of the busiest day. The floor keeps a
# single active hour visible, the ceiling keeps the number on top of it
# readable - on the light themes and the dark ones alike, which is why this is
# an alpha over the theme's own primary and not a palette of fixed colours.
MATRIX_ALPHA_FLOOR = 0.10
MATRIX_ALPHA_CEILING = 0.55
MATRIX_LEGEND_STEPS = 5


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
    palette = _chart_palette(max(len(slots), 1))
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
        # the palette is built for every corporation that has data, so a
        # corporation keeps its colour when the filter changes and when the
        # display switches between the line chart and the pie
        colour = palette[slot % len(palette)]
        corp["color_light"] = colour
        corp["color_dark"] = colour
        corp["dash"] = CHART_DASHES[(slot // len(palette)) % len(CHART_DASHES)]
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


def _tax_receivers(entries, character_ids):
    """Corporation name per character, from the journal rows themselves.

    A character who moved mid month shows up under two receivers; the one that
    got the most tax wins, because the column names where the character earned,
    not every corporation it passed through.
    """
    if not character_ids:
        return {}

    totals = (
        entries.filter(second_party_id__in=character_ids)
        .values("second_party_id", "tax_receiver_id")
        .annotate(total=Sum("tax"))
    )

    dominant = {}
    for row in totals:
        character_id = row["second_party_id"]
        best = dominant.get(character_id)

        if best is None or (row["total"] or 0) > best[1]:
            dominant[character_id] = (row["tax_receiver_id"], row["total"] or 0)

    names = dict(
        EveCorporationInfo.objects.filter(
            corporation_id__in={corp_id for corp_id, _ in dominant.values()}
        ).values_list("corporation_id", "corporation_name")
    )

    return {
        character_id: names.get(corp_id) or str(corp_id)
        for character_id, (corp_id, _) in dominant.items()
    }


def _row(character_id, days, contributed, config):
    suspicious = [
        day for day, hours in days.items() if len(hours) > config.bot_min_hours_per_day
    ]

    return {
        "character_id": character_id,
        "character_name": str(character_id),
        "corporation_name": "",
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

    # one row per character, day, hour and ref_type, counted - the count is
    # what decides whether the hour was active. Grouping replaces the DISTINCT
    # that used to run here and returns fewer rows, because only the groups
    # that reach the threshold survive.
    query_started = time.perf_counter()
    buckets = list(
        entries.annotate(
            day=TruncDate("date", tzinfo=timezone.utc),
            hour=ExtractHour("date", tzinfo=timezone.utc),
        )
        # the name is resolved for the handful of shown rows further down;
        # joining it here widens the grouping over the whole month
        .values("second_party_id", "day", "hour", "ref_type")
        .annotate(seen=Count("id"))
        .filter(seen__gte=ACTIVE_HOUR_MIN_ENTRIES)
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
    corporations = _tax_receivers(entries, shown_ids)

    for entry in shown:
        character_id = entry["character_id"]
        entry["character_name"] = names.get(character_id) or str(character_id)
        entry["corporation_name"] = corporations.get(character_id, "")
        entry["main_name"] = mains.get(character_id, "")

    stats["seconds_aggregate"] = time.perf_counter() - aggregate_started

    return finish(candidates, longest_days)


def _matrix_alpha(hours: int, busiest: int) -> float:
    """Where this day sits on the ramp, as an alpha over the theme's primary."""
    if not hours or not busiest:
        return 0

    span = MATRIX_ALPHA_CEILING - MATRIX_ALPHA_FLOOR

    return round(MATRIX_ALPHA_FLOOR + span * hours / busiest, 2)


# --- corp tax changes --------------------------------------------------------
#
# The corporation wallet only ever shows the corporation's slice - `tax` equals
# `amount` on every bounty row - so the ingame rate is not in the journal
# directly. It can be recovered: `reason` lists the NPCs killed as
# `type_id: count`, and the SDE knows what each of them pays. The corporation's
# slice over the full bounty is the rate that was in force at that moment.
#
# The ratio is the rate times the system's Dynamic Bounty modifier, not the
# rate alone. That does not matter for spotting a change: a corporation
# switching its rate moves every system on the same day, while the bounty
# modifier drifts per system. The number of systems behind a step is reported
# so the difference stays visible.

# entityKillBounty - what an NPC pays before any modifier
BOUNTY_ATTRIBUTE_ID = 481

# "18085: 2,18086: 3" - NPC type and how many of them died
KILL_PAIR = re.compile(r"(\d+)\s*:\s*(\d+)")

# Fallback for how far the share has to move to be worth listing. The settings
# page owns the real number - this is what applies before anyone has saved one.
# Stored the way the rates are, as a fraction: 0.0045 is 0.45 percentage points.
#
# Measured in points of the share, not relative percent, so nine percent to ten
# is one point. That is a deliberate trade - only a relative comparison cancels
# the system's bounty modifier out, and in points it stays in - but points are
# what a person means when they say a Corporation went from nine to ten.
#
# The same number decides what counts as one level, so days within it join a
# plateau. A rate switched once jumps clear; a rate crept upward in several
# smaller steps would be absorbed, because the plateau's median moves with it.
# Toggling is a jump, so that is a trade worth making, but it is a trade.
#
# A level also has to hold for RATE_MIN_DAYS_PER_PLATEAU days, which is what
# keeps a single odd day out of the list.
RATE_STEP_TOLERANCE = 0.0045


def _configured_tolerance():
    """The smallest move worth listing, as a fraction of the share."""
    points = get_config().tax_change_min_points

    return float(points) / 100 if points else RATE_STEP_TOLERANCE

# a day with fewer payouts than this says too little to stand on its own
RATE_MIN_PAYOUTS_PER_DAY = 3

# a plateau shorter than this is noise, not a rate that was in force
RATE_MIN_DAYS_PER_PLATEAU = 2

# days per rolling median. Three is enough to drop a single day where a fleet
# payout landed either side of a minute boundary.
SMOOTHING_WINDOW = 3


@lru_cache(maxsize=1)
def _npc_bounties():
    """What each NPC pays, from the static data export.

    eve_sde is not a hard dependency of this app - without it the whole feature
    reports that it cannot run rather than breaking the page.
    """
    try:
        from eve_sde.models import TypeDogma
    except ImportError:
        logger.warning("eos_tax: eve_sde is not installed, no corp tax changes")
        return {}

    return dict(
        TypeDogma.objects.filter(dogma_attribute_id=BOUNTY_ATTRIBUTE_ID)
        .exclude(value=None)
        .values_list("item_type_id", "value")
    )


def _full_bounty(reason, bounties):
    """What the kills in that reason were worth before the corporation's cut."""
    total = 0.0

    for type_id, count in KILL_PAIR.findall(reason or ""):
        total += bounties.get(int(type_id), 0.0) * int(count)

    return total


def _payouts(year: int, corp_ids):
    """Effective rate per payout, as {corp_id: [(day, system, ratio)]}.

    Rows sharing a minute, a system and a kill list are one fleet payout split
    between its members. Splitting them would divide the ratio by the size of
    the fleet, so they are summed back together first.
    """
    bounties = _npc_bounties()
    if not bounties or not corp_ids:
        return {}

    config = get_config()
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    entries = (
        CorporationWalletJournalEntry.objects.filter(
            ref_type__in=config.tax_types,
            tax_receiver_id__in=corp_ids,
            date__gte=start,
            date__lt=end,
        )
        .exclude(reason=None)
        .exclude(reason="")
        .values("tax_receiver_id", "date", "context_id", "reason", "amount")
    )

    grouped = defaultdict(float)
    for entry in entries:
        moment = entry["date"].replace(second=0, microsecond=0)
        key = (
            entry["tax_receiver_id"],
            moment,
            entry["context_id"],
            entry["reason"],
        )
        grouped[key] += float(entry["amount"] or 0)

    ratios = defaultdict(list)
    for (corp_id, moment, system, reason), share in grouped.items():
        full = _full_bounty(reason, bounties)

        if full > 0 and share > 0:
            ratios[corp_id].append((moment.date(), system, share / full))

    return ratios


def _daily_rates(payouts):
    """One robust rate per day, plus what stands behind it.

    The median, not the mean: a fleet payout that lands either side of a minute
    boundary produces a halved ratio, and a mean would carry that into the day.
    """
    per_day = defaultdict(list)
    for day, system, ratio in payouts:
        per_day[day].append((system, ratio))

    days = []
    for day in sorted(per_day):
        measured = per_day[day]

        if len(measured) < RATE_MIN_PAYOUTS_PER_DAY:
            continue

        days.append({
            "day": day,
            "rate": median(ratio for _, ratio in measured),
            "payouts": len(measured),
            "systems": len({system for system, _ in measured}),
        })

    return days


def _smoothed(days):
    """A three day rolling median over the daily rates.

    A fleet payout whose members land either side of a minute boundary halves
    that day's ratio. Left alone such a day splits a flat run into two plateaus
    that then report a transition between two identical rates. A rolling median
    removes a single day of that and leaves a real switch untouched.
    """
    if len(days) < SMOOTHING_WINDOW:
        return list(days)

    smoothed = []
    reach = SMOOTHING_WINDOW // 2

    for index, day in enumerate(days):
        # at the edges the window reaches inward instead of shrinking: a median
        # of two is their mean, which lets an outlier on the first day survive
        start = min(max(0, index - reach), len(days) - SMOOTHING_WINDOW)
        window = days[start:start + SMOOTHING_WINDOW]
        smoothed.append({**day, "rate": median(entry["rate"] for entry in window)})

    return smoothed


def _plateaus(days, tolerance=RATE_STEP_TOLERANCE):
    """Runs of days that agree on a rate, within the tolerance."""
    found = []

    for day in _smoothed(days):
        if found:
            current = found[-1]
            reference = current["rate"]

            if abs(day["rate"] - reference) <= tolerance:
                current["days"].append(day)
                current["rate"] = median(entry["rate"] for entry in current["days"])
                continue

        found.append({"days": [day], "rate": day["rate"]})

    kept = [
        plateau for plateau in found
        if len(plateau["days"]) >= RATE_MIN_DAYS_PER_PLATEAU
    ]

    for plateau in kept:
        plateau["first_day"] = plateau["days"][0]["day"]
        plateau["last_day"] = plateau["days"][-1]["day"]
        # templates cannot multiply, and a ratio does not read at a glance
        plateau["percent"] = plateau["rate"] * 100

    return kept


def _steps(plateaus, tolerance=RATE_STEP_TOLERANCE):
    """The transitions between plateaus, which is what a change looks like."""
    steps = []

    for before, after in zip(plateaus, plateaus[1:]):
        change = after["rate"] - before["rate"]

        # two plateaus at the same level are one plateau with a gap in it, not
        # a change - it has to clear the tolerance that defines a plateau
        if abs(change) <= tolerance:
            continue

        steps.append({
            "from_rate": before["rate"],
            "to_rate": after["rate"],
            "from_percent": before["rate"] * 100,
            "to_percent": after["rate"] * 100,
            # how far the level moved, in points of the share - what the list
            # sorts by, and what nine to ten means
            "change_points": change * 100,
            "on": after["days"][0]["day"],
            "change": change,
            # a rate change moves every system at once; a bounty modifier
            # moves one, so this is what tells them apart
            "systems": max(entry["systems"] for entry in after["days"]),
        })

    return steps


def get_corp_tax_changes(year: int, tolerance: float = None):
    """Corporations whose effective ingame rate stepped during the year."""
    started = time.perf_counter()
    tolerance = tolerance if tolerance else _configured_tolerance()
    config = get_config()
    corp_ids = _taxed_corporation_ids(config)
    payouts = _payouts(year, corp_ids)
    infos = _corporation_infos(list(payouts))

    rows = []
    for corp_id, measured in payouts.items():
        days = _daily_rates(measured)
        plateaus = _plateaus(days, tolerance)
        steps = _steps(plateaus, tolerance)

        if not steps:
            continue

        info = infos.get(corp_id)
        name = info.corporation_name if info else str(corp_id)

        # one row per change: a Corporation that switched three times has three
        # rows, and sorting by name puts them together
        for step in steps:
            rows.append({
                "corp_id": corp_id,
                "corp_name": name,
                "step": step,
                # how often this Corporation switched in total, so a single row
                # still says whether it stands alone
                "changes": len(steps),
                "payouts": len(measured),
            })

    rows.sort(key=lambda row: -abs(row["step"]["change"]))

    return {
        "rows": rows,
        "stats": {
            "corporations": len(payouts),
            "flagged": len({row["corp_id"] for row in rows}),
            "changes": len(rows),
            "payouts": sum(len(measured) for measured in payouts.values()),
            "seconds": time.perf_counter() - started,
            "sde": bool(_npc_bounties()),
            # in points, for the sentence above the table
            "minimum": round(tolerance * 100, 2),
        },
    }


def get_corp_tax_detail(corp_id: int, year: int, tolerance: float = None):
    """The daily curve for one corporation, and the steps found in it."""
    started = time.perf_counter()
    tolerance = tolerance if tolerance else _configured_tolerance()
    payouts = _payouts(year, [corp_id])
    measured = payouts.get(corp_id, [])
    days = _daily_rates(measured)
    plateaus = _plateaus(days, tolerance)
    info = _corporation_infos([corp_id]).get(corp_id)

    return {
        "corp_id": corp_id,
        "corp_name": info.corporation_name if info else str(corp_id),
        "days": days,
        "plateaus": plateaus,
        "steps": _steps(plateaus, tolerance),
        "payouts": len(measured),
        "seconds": time.perf_counter() - started,
        "sde": bool(_npc_bounties()),
        "minimum": round(tolerance * 100, 2),
    }


def find_characters(name: str, limit: int = 10):
    """Characters whose name matches, for the jump box on the bots page.

    An exact name wins outright - a character called "Tux" must not be buried
    by "Tux Tuxel" and "Tuxel". Only when nothing matches exactly does the
    search widen, and then it is capped, because a single letter would
    otherwise return the whole name table.
    """
    name = (name or "").strip()

    if not name:
        return []

    characters = EveName.objects.filter(category="character")

    exact = list(characters.filter(name__iexact=name).values("eve_id", "name")[:2])
    if len(exact) == 1:
        return exact

    return list(
        characters.filter(name__icontains=name)
        .order_by("name")
        .values("eve_id", "name")[:limit]
    )


def get_character_month(character_id: int, year: int, month: int):
    """Active hours per day for one character, as a week by weekday matrix.

    Same definition of an active hour as the list, so the two agree: the same
    taxed ref_type twice within the hour.

    The grid always starts on a Monday and ends on a Sunday, so the first and
    last row carry days of the neighbouring months - those are marked and left
    empty rather than dropped, or the weekdays would not line up.
    """
    started = time.perf_counter()
    config = get_config()
    corp_ids = _taxed_corporation_ids(config)
    start, end = _month_range(year, month)

    hours_per_day = defaultdict(set)
    total_entries = 0

    if corp_ids and config.tax_types:
        groups = (
            CorporationWalletJournalEntry.objects.filter(
                ref_type__in=config.tax_types,
                tax_receiver_id__in=corp_ids,
                second_party_id=character_id,
                date__gte=start,
                date__lt=end,
            )
            .annotate(
                day=TruncDate("date", tzinfo=timezone.utc),
                hour=ExtractHour("date", tzinfo=timezone.utc),
            )
            .values("day", "hour", "ref_type")
            .annotate(seen=Count("id"))
            .filter(seen__gte=ACTIVE_HOUR_MIN_ENTRIES)
        )

        for row in groups:
            hours_per_day[row["day"]].add(row["hour"])
            total_entries += row["seen"]

    first = date(year, month, 1)
    last = (end - timedelta(days=1)).date()
    busiest = max((len(hours) for hours in hours_per_day.values()), default=0)

    weeks = []
    cursor = first - timedelta(days=first.weekday())
    while cursor <= last:
        days = []
        for offset in range(7):
            current = cursor + timedelta(days=offset)
            hours = sorted(hours_per_day.get(current, ()))

            days.append({
                "date": current,
                "day": current.day,
                "in_month": current.month == month and current.year == year,
                "hours": len(hours),
                # the reading is "which hours", so the tooltip spells them out
                "hour_list": ", ".join(f"{hour:02d}" for hour in hours),
                # One hue, light to dark, as a share of the busiest day. The
                # ceiling stays low so the number in the cell keeps its normal
                # ink on both the light and the dark themes - Alliance Auth has
                # twenty of them, so the theme's own primary does the work
                # rather than a palette that would suit exactly one.
                "alpha": _matrix_alpha(len(hours), busiest),
            })

        weeks.append({"week": cursor.isocalendar().week, "days": days})
        cursor += timedelta(days=7)

    names = dict(
        EveName.objects.filter(eve_id=character_id).values_list("eve_id", "name")
    )

    return {
        "character_id": character_id,
        "character_name": names.get(character_id) or str(character_id),
        "weeks": weeks,
        "busiest": busiest,
        # the legend explains the cells, so it is stepped by the same function
        "legend": [
            {
                "alpha": _matrix_alpha(step, MATRIX_LEGEND_STEPS),
                "hours": round(busiest * step / MATRIX_LEGEND_STEPS),
            }
            for step in range(1, MATRIX_LEGEND_STEPS + 1)
        ],
        "active_days": len(hours_per_day),
        "active_hours": sum(len(hours) for hours in hours_per_day.values()),
        "entries": total_entries,
        "seconds": time.perf_counter() - started,
    }


def get_bot_candidates(year: int, month: int):
    """Just the candidates, for callers that do not care what the run cost."""
    return get_bot_report(year, month)["candidates"]
