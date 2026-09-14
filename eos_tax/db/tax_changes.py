"""Corp Tax Changes: recovering the ingame rate from the kills behind each bounty."""

import time
import re
from collections import defaultdict
from functools import lru_cache
from statistics import median
from datetime import datetime, timezone

from corptools.models import CorporationWalletJournalEntry
from allianceauth.services.hooks import get_extension_logger

from eos_tax.app_settings import get_config

from eos_tax.db.shared import _corporation_infos, _taxed_corporation_ids

logger = get_extension_logger(__name__)


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


# a day with fewer payouts than this says too little to stand on its own
RATE_MIN_PAYOUTS_PER_DAY = 3


# a plateau shorter than this is noise, not a rate that was in force
RATE_MIN_DAYS_PER_PLATEAU = 2


# days per rolling median. Three is enough to drop a single day where a fleet
# payout landed either side of a minute boundary.
SMOOTHING_WINDOW = 3


# Hidden tokens the quick filters search for. A plain "0" would also match 10,
# 20 and 30, so the extremes need something of their own.
EXTREME_MARKERS = {0.0: "eostax-zero", 100.0: "eostax-full"}


def _configured_tolerance():
    """The smallest move worth listing, as a fraction of the share."""
    points = get_config().tax_change_min_points

    return float(points) / 100 if points else RATE_STEP_TOLERANCE


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
    """What the kills in that reason were worth before the corporation's cut.

    None when the static data export does not know one of the NPCs. Counting
    it as nothing would shrink the bounty rather than the payout, and the
    ratio comes out too high - a missing expensive rat reads as a Corporation
    that switched to a hundred percent, which is exactly the row the quick
    filter is meant to surface. A new rat after an expansion, or an export
    that was not pulled again, is enough to produce that.
    """
    total = 0.0

    for type_id, count in KILL_PAIR.findall(reason or ""):
        value = bounties.get(int(type_id))

        if value is None:
            return None

        total += value * int(count)

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

        # a Corporation cannot receive more than the whole bounty, so a ratio
        # past one is not a rate. It means the grouping above put two payouts
        # together that only looked like one fleet - same tick, same system,
        # same kill list, but two ratters who each killed their own rat. On
        # the current data that never happens; the guard is here because the
        # summed value is the one thing that can go wrong silently.
        if not full or share <= 0 or share > full:
            continue

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

    _round_to_halves(kept)

    return kept


def _extremes(*values):
    """Markers for the ends of a move that sit at nothing or at everything."""
    return " ".join(
        sorted({EXTREME_MARKERS[value] for value in values if value in EXTREME_MARKERS})
    )


def _round_to_halves(plateaus):
    """Put each level on a half point, unless that would hide a change.

    An ingame rate is set in whole or half percent and the measurement lands a
    hair beside it, so 0.02 becomes 0 and 99.8 becomes 100 - which is what
    makes those two searchable at all.

    Two levels 0.45 apart can round onto the same half, and "9.5 to 9.5" reads
    as nothing having happened. Where that would occur the whole Corporation
    keeps its exact values rather than one row silently disagreeing with the
    rest.
    """
    rounded = [round(plateau["percent"] * 2) / 2 for plateau in plateaus]

    collapses = any(
        before == after and plateaus[index]["percent"] != plateaus[index + 1]["percent"]
        for index, (before, after) in enumerate(zip(rounded, rounded[1:]))
    )

    if collapses:
        return

    for plateau, value in zip(plateaus, rounded):
        plateau["percent"] = value


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
            # the levels as the plateaus report them, rounded to halves where
            # that does not hide anything, so the row and the level table agree
            "from_percent": before["percent"],
            "to_percent": after["percent"],
            # how far the level moved, in points of the share - taken from the
            # shown values so the row adds up, and what the list sorts by
            "change_points": after["percent"] - before["percent"],
            # what the quick filters look for, either end of the move
            "extremes": _extremes(before["percent"], after["percent"]),
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
