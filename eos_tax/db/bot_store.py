"""The four lists of the bots page, computed by a job and read by the page.

Each reading walks the whole month for the whole alliance; on the live
journal "Hours per day" takes about thirty seconds and "Unbroken runs" ten.
The tabs read what the job last stored here instead, and the fifth tab picks
its characters out of the same stored lists.
"""

import hashlib
import json

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from eos_tax.app_settings import get_config
from eos_tax.db.bot_signals import (
    get_clock_offset,
    get_daily_profile,
    get_unbroken_runs,
)
from eos_tax.db.bots import get_bot_report
from eos_tax.models import BotReport, TaxConfiguration


# By the name each tab travels under in the url.
READINGS = {
    "hours": get_bot_report,
    "runs": get_unbroken_runs,
    "rhythm": get_daily_profile,
    "clock": get_clock_offset,
}

# JSON keeps a datetime as text, and the runs tab formats these two with the
# date filter, which prints nothing for a string.
DATETIME_KEYS = ("started_at", "ended_at")


def settings_fingerprint(config=None):
    """The settings the four lists depend on, as one hash.

    Every bot threshold, plus what decides whose journal is read at all:
    the taxed types, the alliances and the blacklist. A list computed under
    other values is not this page's list any more.
    """
    config = config or get_config()

    values = {
        field.name: getattr(config, field.name)
        for field in TaxConfiguration._meta.concrete_fields
        if field.name.startswith("bot_")
    }
    values["tax_types"] = sorted(config.tax_types or [])
    values["alliances"] = sorted(config.alliance_ids())
    values["blacklist"] = sorted(config.blacklisted_corporation_ids())

    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def _for_storage(signal, report):
    """What a tab renders, and nothing it does not.

    The full row lists run to every character that crossed a threshold, and
    "measured" to every one the reading could score; the tab only shows the
    groups and asks whether anybody crossed the line at all.
    """
    listed = report["candidates"] if signal == "hours" else report["rows"]
    stats = dict(report["stats"])
    # the hour reading carries these beside its figures, the others inside
    stats.setdefault("groups_shown", report.get("groups_shown", len(report["groups"])))
    stats.setdefault("groups_total", report.get("groups_total", len(report["groups"])))

    return {
        "listed": bool(listed),
        "groups": report["groups"],
        "stats": stats,
    }


def store_bot_reports(year: int, month: int):
    """Compute the four lists of one month and keep them."""
    # read before the readings run: a setting saved meanwhile leaves these
    # rows marked with the old values, and the next visit computes them again
    fingerprint = settings_fingerprint()

    for signal, report_for in READINGS.items():
        BotReport.objects.update_or_create(
            year=year,
            month=month,
            signal=signal,
            defaults={
                "report": _for_storage(signal, report_for(year, month)),
                "fingerprint": fingerprint,
                "computed_at": timezone.now(),
            },
        )


def _restored(report):
    for group in report["groups"]:
        for row in group["characters"]:
            for key in DATETIME_KEYS:
                if isinstance(row.get(key), str):
                    row[key] = parse_datetime(row[key])

    return report


def get_stored_reports(year: int, month: int, signals=None):
    """The stored lists of one month, as {signal: report}, or None.

    None as soon as one of the asked for lists is missing or was computed
    under other settings - the caller queues the job and says so, rather
    than show a list nobody would get from the current settings.
    """
    signals = list(signals or READINGS)
    fingerprint = settings_fingerprint()

    stored = {
        row.signal: row
        for row in BotReport.objects.filter(
            year=year, month=month, signal__in=signals
        )
    }

    if any(
        signal not in stored or stored[signal].fingerprint != fingerprint
        for signal in signals
    ):
        return None

    return {
        signal: {
            **_restored(stored[signal].report),
            "computed_at": stored[signal].computed_at,
        }
        for signal in signals
    }
