"""Bots, looked at three more ways than the hour thresholds allow.

The thresholds on the first tab count how many different hours of a day a
character earned in, and on how many days. That aggregates to hour buckets and
throws away the minute, which is where most of the evidence is: the game pays
a ratter about every twenty minutes, so an uninterrupted stretch shows up as a
chain of twenty minute gaps and nothing else does.

The other two compare a character against their own Corporation rather than
against an absolute. The alliance spans several timezones and its own profile
is therefore flat, which would make a round the clock script look ordinary; a
Corporation usually sits in one timezone, and in the journal one of them puts
76 percent of its payouts into eight hours of the day.
"""

import time
from collections import Counter, defaultdict
from math import atan2, cos, pi, sin

from allianceauth.eveonline.models import EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry, EveName
from allianceauth.services.hooks import get_extension_logger

from eos_tax.app_settings import get_config
from eos_tax.db.shared import (
    _month_range,
    _taxed_corporation_ids,
    group_limited_rows,
    grouped,
    level_for,
)

# the two helpers live in shared now, because the hour thresholds group and
# band their rows the same way; the local names stay so nothing else moves
_grouped = grouped
_level = level_for
from eos_tax.util import format_clock, format_duration

logger = get_extension_logger(__name__)


# The game pays a character about every twenty minutes. Everything else that
# used to sit here is a setting now - one set per reading, because the four
# readings are meant to disagree and a shared threshold would tie them
# together again. This one is not: it is what the game does, not a choice.
TICK_MINUTES = 20


def _flat_share(busy_hours: int) -> float:
    """The share of the day a window that size holds when nothing stands out.

    A character spread evenly over the clock lands here whatever window they
    are measured against, so it is the floor the rhythm score measures down to.
    """
    return busy_hours / 24


def _payouts(year: int, month: int):
    """Every taxed payout of the month, by character.

    Returns {character_id: {"corp_id": int, "moments": [datetime, ...]}} with
    the moments sorted. One query; the three signals each run their own,
    because the page loads one tab at a time.
    """
    config = get_config()
    corp_ids = _taxed_corporation_ids(config)

    if not corp_ids:
        return {}

    start, end = _month_range(year, month)
    rows = CorporationWalletJournalEntry.objects.filter(
        ref_type__in=config.tax_types,
        tax_receiver_id__in=corp_ids,
        date__gte=start,
        date__lt=end,
    ).values("second_party_id", "tax_receiver_id", "date")

    characters = {}
    for row in rows:
        character = characters.setdefault(
            row["second_party_id"],
            {"corp_id": row["tax_receiver_id"], "moments": []},
        )
        character["moments"].append(row["date"])

    for character in characters.values():
        character["moments"].sort()

    return characters


def _names(character_ids, corp_ids):
    """What to call the rows, resolved in one query each."""
    return (
        dict(
            EveName.objects.filter(
                eve_id__in=character_ids, category="character"
            ).values_list("eve_id", "name")
        ),
        dict(
            EveCorporationInfo.objects.filter(corporation_id__in=corp_ids)
            .values_list("corporation_id", "corporation_name")
        ),
    )


def _longest_run(moments, max_gaps: int, tolerance: int, ceiling: int):
    """The longest stretch of consecutive ticks, and what it cost to keep it.

    A gap up to the tolerance continues the stretch. A longer one - up to the
    ceiling - is an interruption the stretch survives while it has allowance
    left; that is what keeps a daily downtime from cutting a night in half.
    Anything past the ceiling ends it regardless.
    """
    if not moments:
        return {"ticks": 0, "gaps": 0, "start": None, "end": None}

    best = {"ticks": 0, "gaps": 0, "start": None, "end": None}
    start = 0
    gaps = 0

    def remember(first, last, used):
        if last - first + 1 > best["ticks"]:
            best.update({
                "ticks": last - first + 1,
                "gaps": used,
                "start": moments[first],
                "end": moments[last],
            })

    for index in range(1, len(moments)):
        minutes = (moments[index] - moments[index - 1]).total_seconds() / 60

        if minutes <= tolerance:
            continue

        if minutes <= ceiling and gaps < max_gaps:
            gaps += 1
            continue

        remember(start, index - 1, gaps)
        start = index
        gaps = 0

    remember(start, len(moments) - 1, gaps)

    return best


def _character(year: int, month: int, character_id: int):
    """That character's payouts and their Corporation's, or nothing.

    Returns (own moments, the Corporation's hours) so the callers below can
    build a baseline that leaves the character out of it - the same rule the
    lists follow, because a detail page that disagreed with the list it was
    opened from would be worse than no detail page.
    """
    characters = _payouts(year, month)
    entry = characters.get(character_id)

    if not entry:
        return None, None, None

    # every Corporation, not only this character's: the first pass that finds
    # who to leave out of a baseline scores the whole month, the same way the
    # list does, because a detail page that disagreed with the list it was
    # opened from would be worse than no detail page
    return entry, _corp_hours(characters), characters


def get_run_detail(character_id: int, year: int, month: int,
                   max_gaps: int = None):
    """Every payout of the month, and which of them form the longest run.

    Drawn as a point per payout - day across, hour up - the shape of somebody
    who plays evenings is a band, and the shape of an uninterrupted stretch is
    a diagonal line. The run itself is marked rather than described.
    """
    config = get_config()

    if max_gaps is None:
        max_gaps = config.bot_run_max_gaps

    entry, _, _ = _character(year, month, character_id)

    if not entry:
        return {"points": [], "run": None}

    moments = entry["moments"]
    run = _longest_run(
        moments,
        max_gaps,
        config.bot_run_tick_tolerance,
        config.bot_run_gap_minutes,
    )
    inside = set()

    if run["start"] is not None:
        inside = {
            moment for moment in moments
            if run["start"] <= moment <= run["end"]
        }

    return {
        "points": [
            {
                "day": moment.day,
                "hour": round(moment.hour + moment.minute / 60, 2),
                "in_run": moment in inside,
            }
            for moment in moments
        ],
        "run": {
            "ticks": run["ticks"],
            "gaps": run["gaps"],
            "started_at": run["start"],
            "ended_at": run["end"],
            "duration": format_duration(
                (run["end"] - run["start"]).total_seconds() / 3600
            ) if run["start"] else "",
            "same_day": (
                run["start"].date() == run["end"].date() if run["start"] else True
            ),
            "level": level_for(
                run["ticks"] / config.bot_run_min_ticks
                if config.bot_run_min_ticks else 0,
                top=1.0,
            ),
        },
        "payouts": len(moments),
        "threshold": config.bot_run_min_ticks,
    }


def _hour_series(own_hours, corp_hours):
    """Both days as a share per hour, so a big Corporation and one character
    can be drawn on the same axis.

    corp_hours is None when nothing is left of the Corporation to compare
    against, and then the Corporation reads None rather than a copy of the
    character - two identical lines are a claim of perfect agreement, and the
    absence of a yardstick is not agreement with it.
    """
    own_total = sum(own_hours.values()) or 1
    corp_total = sum(corp_hours.values()) or 1 if corp_hours else 0

    return [
        {
            "hour": hour,
            "character": round(own_hours.get(hour, 0) / own_total * 100, 2),
            "corporation": (
                round(corp_hours.get(hour, 0) / corp_total * 100, 2)
                if corp_total else None
            ),
        }
        for hour in range(24)
    ]


def get_rhythm_detail(character_id: int, year: int, month: int):
    """The character's day against the Corporation's, hour by hour.

    Shares rather than counts: one character never has the volume of their
    Corporation, and drawn as counts the character's own day would be a flat
    line along the bottom.
    """
    config = get_config()
    entry, corp_hours, characters = _character(year, month, character_id)

    if not entry:
        return {"series": [], "window": []}

    corp_min = config.bot_rhythm_corp_min_payouts
    own = Counter(moment.hour for moment in entry["moments"])

    # the same yardstick the list built, worked out the same way - a detail
    # page contradicting the list it was opened from would be worse than none
    purge = _rhythm_purge(characters, corp_hours, config)
    corp = corp_hours[entry["corp_id"]]
    rest = None

    if purge:
        rest = _rest_of_corp(
            corp, own, corp_min,
            _purged_for(purge, entry["corp_id"], character_id, own),
        )

    if not rest:
        rest = _rest_of_corp(corp, own, corp_min)

    if not rest:
        return {
            "series": _hour_series(own, None),
            "window": [],
            "share": None,
            "payouts": len(entry["moments"]),
        }

    window = _window(rest, config.bot_rhythm_busy_hours)
    share = _busy_share(own, window["hours"])
    flat = _flat_share(config.bot_rhythm_busy_hours)

    return {
        "series": _hour_series(own, rest),
        "window": sorted(window["hours"]),
        "share": round(share * 100),
        "corp_share": round(window["share"] * 100),
        "difference": round((window["share"] - share) * 100),
        "payouts": len(entry["moments"]),
        "level": level_for(
            max(0.0, min(1.0, (window["share"] - share) / (window["share"] - flat)))
            if window["share"] > flat else 0
        ),
    }


def get_clock_detail(character_id: int, year: int, month: int):
    """Where the character's day sits against their Corporation's, round the clock.

    The same two distributions as the rhythm reading, but what matters here is
    the two centres rather than the shape - so both are handed over as times
    and as the hours between them.
    """
    config = get_config()
    entry, corp_hours, characters = _character(year, month, character_id)

    if not entry:
        return {"series": [], "middle": None}

    corp_min = config.bot_clock_corp_min_payouts
    own = Counter(moment.hour for moment in entry["moments"])

    purge = _clock_purge(characters, corp_hours, config)
    corp = corp_hours[entry["corp_id"]]
    rest = None

    if purge:
        rest = _rest_of_corp(
            corp, own, corp_min,
            _purged_for(purge, entry["corp_id"], character_id, own),
        )

    if not rest:
        rest = _rest_of_corp(corp, own, corp_min)

    if not rest:
        return {
            "series": _hour_series(own, None),
            "middle": None,
            "payouts": len(entry["moments"]),
        }

    middle = _typical_hour(own)
    corp_middle = _typical_hour(rest)
    apart = _clock_distance(middle, corp_middle)

    return {
        "series": _hour_series(own, rest),
        "middle": round(middle, 2),
        "corp_middle": round(corp_middle, 2),
        "middle_at": format_clock(middle),
        "corp_middle_at": format_clock(corp_middle),
        "apart": round(apart, 1),
        "apart_for": format_duration(apart),
        "payouts": len(entry["moments"]),
        "level": level_for(min(1.0, apart / config.bot_clock_max_apart)),
    }


def get_unbroken_runs(year: int, month: int, min_ticks: int = None,
                      max_gaps: int = None):
    """Characters whose payouts form a long uninterrupted chain.

    Timezone neutral by construction: twenty minutes is twenty minutes in
    every one of the alliance's timezones, so this is the one signal that
    treats a Chinese and a European Corporation alike.
    """
    started = time.perf_counter()
    config = get_config()

    if min_ticks is None:
        min_ticks = config.bot_run_min_ticks
    if max_gaps is None:
        max_gaps = config.bot_run_max_gaps

    characters = _payouts(year, month)
    names, corp_names = _names(
        characters, {entry["corp_id"] for entry in characters.values()}
    )

    tolerance = config.bot_run_tick_tolerance
    ceiling = config.bot_run_gap_minutes

    rows = []
    longest = []
    for character_id, entry in characters.items():
        run = _longest_run(entry["moments"], max_gaps, tolerance, ceiling)

        hours = (run["end"] - run["start"]).total_seconds() / 3600

        row = {
            "character_id": character_id,
            "character_name": names.get(character_id, str(character_id)),
            "corporation_name": corp_names.get(entry["corp_id"], "-"),
            "ticks": run["ticks"],
            "gaps": run["gaps"],
            "hours": round(hours, 1),
            "started_at": run["start"],
            "ended_at": run["end"],
            # the span as well as the length, so the reader sees when it
            # happened without subtracting one from the other
            "duration": format_duration(hours),
            "same_day": run["start"].date() == run["end"].date(),
            "payouts": len(entry["moments"]),
            # against the threshold rather than against a number I
            # invented, and only reaching it counts as strong - the fallback
            # list is made of runs that did not
            "level": _level(
                run["ticks"] / min_ticks if min_ticks else 0, top=1.0
            ),
        }

        longest.append(row)

        if run["ticks"] >= min_ticks:
            rows.append(row)

    rows.sort(key=lambda row: (-row["ticks"], row["character_name"]))

    # nothing over the threshold says nothing about how close anyone came, so
    # the longest runs are shown instead - the same fallback the hour
    # thresholds use, and for the same reason
    fallback = []
    if not rows:
        # cut to ten mains, not ten rows - see group_limited_rows
        fallback = group_limited_rows(sorted(
            longest, key=lambda row: (-row["ticks"], row["character_name"])
        ))

    groups, total = _grouped(rows or fallback)

    return {
        "rows": rows,
        "longest": fallback,
        "groups": groups,
        "stats": {
            "groups_shown": len(groups),
            "groups_total": total,
            "characters": len(characters),
            "min_ticks": min_ticks,
            "max_gaps": max_gaps,
            "tick_minutes": TICK_MINUTES,
            "tolerance": tolerance,
            "ceiling": ceiling,
            "seconds": round(time.perf_counter() - started, 2),
        },
    }


def _busy_share(hours, window):
    """How much of the activity falls into that set of hours."""
    total = sum(hours.values())

    return sum(hours.get(hour, 0) for hour in window) / total if total else 0


def _corp_hours(characters):
    """Every Corporation's day, as payouts per hour.

    The Corporation is the yardstick rather than the alliance: the alliance
    holds Chinese, American, European and Russian groups at once, so its own
    day is flat and every script would look ordinary against it.
    """
    per_corp = defaultdict(Counter)

    for entry in characters.values():
        for moment in entry["moments"]:
            per_corp[entry["corp_id"]][moment.hour] += 1

    return per_corp


def _window(hours, busy_hours: int):
    """The busiest hours of a day, and how much of it they hold."""
    busiest = [
        hour for hour, _ in sorted(hours.items(), key=lambda item: -item[1])
    ][:busy_hours]

    return {
        "hours": set(busiest),
        "share": _busy_share(hours, busiest),
        "middle": _typical_hour(hours),
        "payouts": sum(hours.values()),
    }


def _rest_of_corp(corp_hours, own_hours, min_payouts: int, purged=None):
    """The Corporation's day with one character's own payouts taken out.

    Nobody is measured against a yardstick they helped define. A character
    contributing a third of a Corporation's payouts pulls the baseline a third
    of the way towards themselves, which hides a third of their own deviation;
    the only ratter in a Corporation would be compared against nothing but
    themselves and always come out ordinary.

    `purged` goes the same way and for the same reason, one step further out:
    the hours of the other characters this reading already calls bots, who
    would otherwise drag the yardstick towards themselves for everybody else.

    None when too little is left to say anything with - a Corporation that is
    one person offers no yardstick rather than a shadow of one.
    """
    rest = Counter(corp_hours)
    rest.subtract(own_hours)

    if purged:
        rest.subtract(purged)

    rest = Counter({hour: count for hour, count in rest.items() if count > 0})

    if sum(rest.values()) < min_payouts:
        return None

    return rest


def _window_without(corp_hours, own_hours, busy_hours: int, min_payouts: int,
                    purged=None):
    """The busy window of the Corporation minus one character."""
    rest = _rest_of_corp(corp_hours, own_hours, min_payouts, purged)

    return _window(rest, busy_hours) if rest else None


def _flagged(rows):
    """Who a first pass came out calling a bot."""
    return {row["character_id"] for row in rows if row["level"] == "high"}


def _purge_index(characters, flagged):
    """Per Corporation: the flagged characters together, and who they are.

    Summed once here rather than per measured character, because the same
    Corporation is the yardstick for everybody in it.
    """
    index = {}

    for character_id in flagged:
        entry = characters[character_id]
        slot = index.setdefault(
            entry["corp_id"], {"hours": Counter(), "ids": set()}
        )
        slot["hours"].update(moment.hour for moment in entry["moments"])
        slot["ids"].add(character_id)

    return index


def _purged_for(index, corp_id, character_id, own_hours):
    """What to take out of this baseline besides the character themselves.

    Their own hours come out separately, so a character who is flagged must
    not be subtracted twice - the Counter difference drops what that would
    turn negative.
    """
    slot = (index or {}).get(corp_id)

    if not slot:
        return None

    if character_id in slot["ids"]:
        return slot["hours"] - own_hours

    return slot["hours"]


def _profile_rows(characters, corp_hours, names, corp_names, config,
                  purge=None):
    """One scored row per character with enough of a day to describe.

    `purge` holds, per Corporation, the characters this reading already calls
    bots. They come out of the baseline as well as the measured character -
    but only while enough is left: a Corporation that would fall under its own
    floor keeps the plain baseline rather than losing its members from the
    reading altogether.
    """
    busy_hours = config.bot_rhythm_busy_hours
    min_payouts = config.bot_rhythm_min_payouts
    corp_min = config.bot_rhythm_corp_min_payouts
    flat = _flat_share(busy_hours)

    rows = []
    corporations = set()

    for character_id, entry in characters.items():
        if len(entry["moments"]) < min_payouts:
            continue

        corp_id = entry["corp_id"]
        hours = Counter(moment.hour for moment in entry["moments"])
        window = None

        if purge:
            window = _window_without(
                corp_hours[corp_id], hours, busy_hours, corp_min,
                _purged_for(purge, corp_id, character_id, hours),
            )

        if not window:
            window = _window_without(
                corp_hours[corp_id], hours, busy_hours, corp_min
            )

        if not window:
            continue

        corporations.add(corp_id)
        share = _busy_share(hours, window["hours"])

        # how far along the way from "like my Corporation" to "spread over
        # the whole clock" this character sits. The room to move shrinks as a
        # Corporation's own day flattens, which is why it is a ratio and not
        # a difference in points
        room = window["share"] - flat
        score = (window["share"] - share) / room if room > 0 else 0

        rows.append({
            "character_id": character_id,
            "character_name": names.get(character_id, str(character_id)),
            "corporation_name": corp_names.get(corp_id, "-"),
            "share": round(share * 100),
            "corp_share": round(window["share"] * 100),
            "difference": round((window["share"] - share) * 100),
            "payouts": len(entry["moments"]),
            "hours_used": len(hours),
            "level": _level(max(0.0, min(1.0, score))),
        })

    rows.sort(key=lambda row: (-row["difference"], row["character_name"]))

    return rows, corporations


def _rhythm_purge(characters, corp_hours, config):
    """Who this reading calls a bot when nobody has been taken out yet."""
    if not config.bot_rhythm_purge_strong:
        return None

    rows, _ = _profile_rows(characters, corp_hours, {}, {}, config)
    flagged = _flagged(rows)

    return _purge_index(characters, flagged) if flagged else None


def get_daily_profile(year: int, month: int):
    """Characters spread flatter over the day than their own Corporation.

    A ranking, not a verdict. There is no number that separates a night shift
    worker from a script, so the list is ordered and the Corporation's own
    figure sits next to each row for comparison.
    """
    started = time.perf_counter()
    config = get_config()
    min_difference = config.bot_rhythm_min_difference

    characters = _payouts(year, month)
    corp_hours = _corp_hours(characters)
    names, corp_names = _names(
        characters, {entry["corp_id"] for entry in characters.values()}
    )

    rows, corporations = _profile_rows(
        characters, corp_hours, names, corp_names, config
    )

    # a bot loud enough to be listed is also part of its Corporation's day,
    # and drags the yardstick flat with it - so the second pass measures
    # everybody, the bots included, against what is left without them
    purged = set()
    if config.bot_rhythm_purge_strong:
        purged = _flagged(rows)

        if purged:
            rows, corporations = _profile_rows(
                characters, corp_hours, names, corp_names, config,
                _purge_index(characters, purged),
            )

    # ranked and then cut. Without the cut the table filled up with characters
    # more concentrated than their own Corporation - the opposite of what this
    # looks for - and the reader had to find the handful that were not
    listed = [row for row in rows if row["difference"] >= min_difference]

    # nothing over the threshold says nothing about how close anyone came, so
    # the largest differences are shown instead, the same way the runs tab
    # falls back. Cut to ten mains, not ten rows - see group_limited_rows
    fallback = group_limited_rows(rows) if not listed else []

    groups, total = _grouped(listed or fallback)

    return {
        "rows": listed,
        "longest": fallback,
        # every character the reading could score, listed or not. The page
        # shows what crossed the line; a caller asking how the line was drawn
        # needs the ones that did not.
        "measured": rows,
        "groups": groups,
        "stats": {
            "groups_shown": len(groups),
            "groups_total": total,
            "characters": len(characters),
            "corporations": len(corporations),
            "measured_characters": len(rows),
            "busy_hours": config.bot_rhythm_busy_hours,
            "min_payouts": config.bot_rhythm_min_payouts,
            "corp_min_payouts": config.bot_rhythm_corp_min_payouts,
            "min_difference": min_difference,
            "purged": len(purged),
            "seconds": round(time.perf_counter() - started, 2),
        },
    }


def _typical_hour(hours):
    """The middle of someone's day, averaged the way a clock wraps.

    Not the busiest hour: out of a dozen payouts the busiest hour is wherever
    the noise landed, and it flips on a single tick. This uses every payout,
    and it treats 23:00 and 01:00 as two hours apart rather than twenty-two.
    """
    total = sum(hours.values())

    if not total:
        return None

    angle = 2 * pi / 24
    east = sum(count * cos(hour * angle) for hour, count in hours.items())
    north = sum(count * sin(hour * angle) for hour, count in hours.items())

    return (atan2(north, east) / angle) % 24


def _clock_distance(one: float, other: float):
    """Hours between two times of day, the short way round the clock."""
    apart = abs(one - other) % 24

    return min(apart, 24 - apart)


def _clock_rows(characters, corp_hours, names, corp_names, config,
                purge=None):
    """One scored row per character far enough described to place.

    `purge` works as it does on the rhythm reading: the characters this one
    already calls bots come out of the baseline too, and a Corporation that
    would fall under its floor keeps the plain one.
    """
    min_payouts = config.bot_clock_min_payouts
    corp_min = config.bot_clock_corp_min_payouts
    max_apart = config.bot_clock_max_apart

    rows = []
    corporations = set()

    for character_id, entry in characters.items():
        if len(entry["moments"]) < min_payouts:
            continue

        corp_id = entry["corp_id"]
        hours = Counter(moment.hour for moment in entry["moments"])
        # the middle of a day is an average over every hour of it, so this
        # reading needs the rest of the Corporation and not its busy window -
        # which is what keeps it independent of the rhythm settings
        rest = None

        if purge:
            rest = _rest_of_corp(
                corp_hours[corp_id], hours, corp_min,
                _purged_for(purge, corp_id, character_id, hours),
            )

        if not rest:
            rest = _rest_of_corp(corp_hours[corp_id], hours, corp_min)

        if not rest:
            continue

        corporations.add(corp_id)
        middle = _typical_hour(hours)
        corp_middle = _typical_hour(rest)

        apart = _clock_distance(middle, corp_middle)

        rows.append({
            "character_id": character_id,
            "character_name": names.get(character_id, str(character_id)),
            "corporation_name": corp_names.get(corp_id, "-"),
            "middle": round(middle, 1),
            "corp_middle": round(corp_middle, 1),
            "apart": round(apart, 1),
            # the same three numbers as a clock and a stopwatch write them
            "middle_at": format_clock(middle),
            "corp_middle_at": format_clock(corp_middle),
            "apart_for": format_duration(apart),
            "payouts": len(entry["moments"]),
            # a smaller scale than the full twelve hours makes the top of it
            # reachable, so the ratio is capped rather than allowed past one
            "level": _level(min(1.0, apart / max_apart)),
        })

    # a wider gap first, and among equal gaps the better evidenced row - the
    # thin ones would otherwise crowd the top, since noise moves further
    rows.sort(key=lambda row: (-row["apart"], -row["payouts"],
                               row["character_name"]))

    return rows, corporations


def _clock_purge(characters, corp_hours, config):
    """Who this reading calls a bot when nobody has been taken out yet."""
    if not config.bot_clock_purge_strong:
        return None

    rows, _ = _clock_rows(characters, corp_hours, {}, {}, config)
    flagged = _flagged(rows)

    return _purge_index(characters, flagged) if flagged else None


def get_clock_offset(year: int, month: int):
    """Characters whose day peaks far from their Corporation's.

    A Corporation usually shares a timezone, so a member peaking twelve hours
    away from the rest is either genuinely somewhere else - which happens -
    or the account is not being played by the person it belongs to. A hint,
    never an accusation.
    """
    started = time.perf_counter()
    config = get_config()
    min_apart = config.bot_clock_min_apart

    characters = _payouts(year, month)
    corp_hours = _corp_hours(characters)
    names, corp_names = _names(
        characters, {entry["corp_id"] for entry in characters.values()}
    )

    rows, corporations = _clock_rows(
        characters, corp_hours, names, corp_names, config
    )

    # somebody far enough from their Corporation to be listed also pulls that
    # Corporation's own middle of the day towards themselves, which shortens
    # the distance for everybody else
    purged = set()
    if config.bot_clock_purge_strong:
        purged = _flagged(rows)

        if purged:
            rows, corporations = _clock_rows(
                characters, corp_hours, names, corp_names, config,
                _purge_index(characters, purged),
            )

    # everybody sits some distance from their Corporation; most of it is the
    # difference between playing after work and playing after dinner
    listed = [row for row in rows if row["apart"] >= min_apart]
    # cut to ten mains, not ten rows - see group_limited_rows
    fallback = group_limited_rows(rows) if not listed else []

    groups, total = _grouped(listed or fallback)

    return {
        "rows": listed,
        "longest": fallback,
        # every character the reading could score, listed or not. The page
        # shows what crossed the line; a caller asking how the line was drawn
        # needs the ones that did not.
        "measured": rows,
        "groups": groups,
        "stats": {
            "groups_shown": len(groups),
            "groups_total": total,
            "characters": len(characters),
            "corporations": len(corporations),
            "measured_characters": len(rows),
            "min_payouts": config.bot_clock_min_payouts,
            "corp_min_payouts": config.bot_clock_corp_min_payouts,
            "max_apart": config.bot_clock_max_apart,
            "min_apart": min_apart,
            "purged": len(purged),
            "seconds": round(time.perf_counter() - started, 2),
        },
    }
