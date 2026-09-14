"""The bots page: characters whose taxed income looks automated."""

import time
from collections import defaultdict
from datetime import date, timedelta, timezone

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import (
    get_main_character_from_evecharacter,
)
from corptools.models import CorporationWalletJournalEntry, EveName
from django.db.models import Count, Sum
from django.db.models.functions import ExtractHour, TruncDate

from eos_tax.app_settings import get_config
from eos_tax.util import format_isk

from eos_tax.db.shared import (
    _month_range,
    _taxed_corporation_ids,
    group_limited_rows,
    grouped,
    level_for,
    main_characters,
)


# The matrix paints one hue at a share of the busiest day. The floor keeps a
# single active hour visible, the ceiling keeps the number on top of it
# readable - on the light themes and the dark ones alike, which is why this is
# an alpha over the theme's own primary and not a palette of fixed colours.
MATRIX_ALPHA_FLOOR = 0.10


MATRIX_ALPHA_CEILING = 0.55


MATRIX_LEGEND_STEPS = 5


def _main_characters(character_ids):
    """Main character name per character id, in one query.

    The lookup itself lives in shared.py, because the bot signals need the
    same thing with the id attached; this column only ever shows the name.
    """
    return {
        character_id: name
        for character_id, (_, name) in main_characters(character_ids).items()
    }


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
        # against the configured threshold, and only reaching it counts as
        # strong - the fallback list is made of characters who did not
        "level": level_for(
            len(suspicious) / config.bot_min_days_per_month
            if config.bot_min_days_per_month else 0,
            top=1.0,
        ),
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
    mains with the longest days of the month - an empty page says nothing
    about whether the thresholds are sensible, that list does.

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
        # the fallback list is grouped too, so the page reads the same way
        # whether or not anyone crossed the thresholds
        groups, total = grouped(candidates or longest_days)

        return {
            "candidates": candidates,
            "longest_days": longest_days,
            "groups": groups,
            "groups_shown": len(groups),
            "groups_total": total,
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
        .filter(seen__gte=config.bot_hours_min_entries)
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
        # cut to ten mains, not ten rows - see group_limited_rows
        longest_days = group_limited_rows(sorted(
            rows,
            key=lambda entry: (
                -entry["max_hours"],
                -entry["active_days"],
                -entry["contributed"],
            ),
        ))

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
            .filter(seen__gte=config.bot_hours_min_entries)
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
