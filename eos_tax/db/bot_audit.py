"""The mains behind the bots page whose listed characters corptools no longer watches."""

from corptools.models import CharacterAudit

from eos_tax.db.shared import grouped


LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}

AUDIT_MISSING = "missing"
AUDIT_INACTIVE = "inactive"


def get_unaudited_mains(reports):
    """Characters listed on any of the four tabs without a current corptools audit,
    grouped by main.

    `reports` are the four stored lists, {signal: report} - picked from, not
    computed again. "Listed" is what the tabs show - their first ten mains,
    or the fallback list when nobody crossed a threshold - because that is
    the list a reader acts on. Only those characters are checked, not the
    rest of the account: an alt that never ratted says nothing about the
    month in question.

    Current is corptools' own `active` flag, read now rather than stored with
    the lists, so a token renewed since the job ran is seen at once. A
    character Alliance Auth never saw has no audit at all and is listed as a
    group of its own, the way the tabs list it.
    """
    listed = {}
    for signal, report in reports.items():
        for group in report["groups"]:
            for row in group["characters"]:
                entry = listed.setdefault(row["character_id"], {
                    "character_id": row["character_id"],
                    "character_name": row["character_name"],
                    "corporation_name": row["corporation_name"],
                    "level": row["level"],
                    "signals": [],
                })
                entry["signals"].append(signal)
                # the strongest reading speaks for the character, the way
                # the worst member speaks for its group
                if LEVEL_ORDER[row["level"]] < LEVEL_ORDER[entry["level"]]:
                    entry["level"] = row["level"]

    active = dict(
        CharacterAudit.objects.filter(
            character__character_id__in=listed
        ).values_list("character__character_id", "active")
    )

    rows = []
    for character_id, entry in listed.items():
        if active.get(character_id):
            continue

        entry["audit"] = AUDIT_INACTIVE if character_id in active else AUDIT_MISSING
        rows.append(entry)

    rows.sort(key=lambda row: (
        LEVEL_ORDER[row["level"]], -len(row["signals"]), row["character_name"]
    ))

    # every main, not the first ten: this list is already the cut of four
    # cut lists, and a main left off it is a missing audit nobody chases
    groups, total = grouped(rows, limit=None)
    # by name, not by the strongest member like the four lists: this one is
    # worked through main by main, and a name is where a reader looks one up.
    # The rows inside keep their order, and the columns sort them in place
    groups.sort(key=lambda group: group["main_name"].casefold())

    return {
        "listed": bool(rows),
        "groups": groups,
        "stats": {
            "listed_characters": len(listed),
            "unaudited_characters": len(rows),
            "groups_total": total,
        },
        # the oldest of the four, since this list is only as fresh as that
        "computed_at": min(
            (report["computed_at"] for report in reports.values()), default=None
        ),
    }
