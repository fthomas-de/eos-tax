"""The characters the bots lists once showed who have not logged in since."""

from datetime import timedelta

from corptools.models import CharacterAudit
from django.utils import timezone

from allianceauth.eveonline.models import EveCharacter

from eos_tax.db.bot_store import READINGS
from eos_tax.db.gm_transactions import gm_x_months
from eos_tax.db.shared import grouped
from eos_tax.models import BotReport, GmReport


def get_possibly_banned(min_days: int):
    """Characters on any stored month of the four lists, or with a GM X
    booking in the stored GM report, whose last login is at least `min_days`
    ago, grouped by main.

    GM X only, not every GM counterparty and not a wallet below zero - the
    user's choice; a cleared GM row still counts.

    "On a list" is whatever a tab showed, the fallback list of a month where
    nobody crossed a threshold included - the user's choice. Every stored
    month counts, whatever settings it was computed under: it is what the
    list showed, and a ban follows what a reader saw, not today's thresholds.

    The login is corptools' `last_known_login`, read now. A character without
    one is left out - a missing audit is the audit tab's finding, not this one.

    "found" is the month of the finding: the newest GM X booking where there
    is one, else the newest month a list showed the character - GM before
    bot, months only, the user's choice. Newest first, a main by its newest.
    """
    flagged = {}
    computed_at = None
    for year, month, report, stored_at in (
        BotReport.objects.filter(signal__in=READINGS)
        .order_by("-year", "-month")
        .values_list("year", "month", "report", "computed_at")
    ):
        computed_at = max(computed_at or stored_at, stored_at)
        label = f"{year}-{month:02d}"
        for group in report["groups"]:
            for row in group["characters"]:
                entry = flagged.setdefault(row["character_id"], {
                    "character_id": row["character_id"],
                    "character_name": row["character_name"],
                    "corporation_name": row["corporation_name"],
                    # grouped() reads it; this list ranks nobody
                    "level": None,
                    "months": [],
                })
                # newest first by the query's order; four tabs of one month once
                if label not in entry["months"]:
                    entry["months"].append(label)
    on_lists = len(flagged)

    stored_gm = GmReport.objects.filter(pk=1).first()
    gm_months = gm_x_months(stored_gm)
    if gm_months:
        computed_at = max(computed_at or stored_gm.computed_at, stored_gm.computed_at)
    for character_id, gm_month in gm_months.items():
        flagged.setdefault(character_id, {
            "character_id": character_id,
            # the GM report stores no names; filled in from EveCharacter below
            "character_name": "",
            "corporation_name": "",
            "level": None,
            "months": [],
        }).update(gm=True, gm_month=gm_month)

    cutoff = timezone.now() - timedelta(days=min_days)
    logins = dict(
        CharacterAudit.objects.filter(
            character__character_id__in=flagged, last_known_login__lte=cutoff
        ).values_list("character__character_id", "last_known_login")
    )
    # the Corporation now, not when the list was stored: a banned character's
    # affiliation is still updated
    characters = {
        character_id: (name, corporation)
        for character_id, name, corporation in EveCharacter.objects.filter(
            character_id__in=logins
        ).values_list("character_id", "character_name", "corporation_name")
    }

    rows = sorted(
        (
            {
                **flagged[character_id],
                "last_login": login,
                "character_name": flagged[character_id]["character_name"]
                or characters.get(character_id, ("",))[0],
                "corporation_name": characters.get(
                    character_id, (None, flagged[character_id]["corporation_name"])
                )[1],
                "found": flagged[character_id].get("gm_month")
                or flagged[character_id]["months"][0],
            }
            for character_id, login in logins.items()
        ),
        key=lambda row: row["character_name"].casefold(),
    )
    # sort() is stable: a tie keeps the name order, here and for the groups
    rows.sort(key=lambda row: row["found"], reverse=True)

    groups, total = grouped(rows, limit=None)
    groups.sort(key=lambda group: group["main_name"].casefold())
    for group in groups:
        group["found"] = group["characters"][0]["found"]
    groups.sort(key=lambda group: group["found"], reverse=True)

    return {
        "listed": bool(rows),
        "groups": groups,
        "stats": {
            "flagged_characters": on_lists,
            "gm_characters": len(gm_months),
            "quiet_characters": len(rows),
            "groups_total": total,
        },
        "computed_at": computed_at,
        "min_days": min_days,
    }
