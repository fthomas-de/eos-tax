"""Helpers more than one page needs."""

from datetime import datetime, timezone

from django.core.exceptions import ObjectDoesNotExist

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import (
    get_main_character_from_evecharacter,
)


def _corporation_infos(corp_ids):
    return {
        info.corporation_id: info
        for info in EveCorporationInfo.objects.filter(
            corporation_id__in=corp_ids
        ).select_related("alliance")
    }


def _month_range(year: int, month: int):
    """Half open range for one month.

    date__month becomes EXTRACT(MONTH FROM date), which no index can serve;
    a range comparison can."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)

    return start, end


def _taxed_corporation_ids(config):
    """Corporations of the configured alliances, as far as Alliance Auth knows them.

    A blacklisted Corporation is never taxed and never listed, so it drops out
    here. The overview and the statistics start from stored rows instead and
    apply the same list to their own queries.
    """
    return list(
        EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=config.alliance_ids()
        )
        .exclude(corporation_id__in=config.blacklisted_corporation_ids())
        .values_list("corporation_id", flat=True)
    )


def alts_of(character_id: int):
    """Every character on the same account as this one, and the main's name.

    Alliance Auth alone, no journal: it knows who belongs together, which is
    all this answers. It does not know which of them is worth looking at -
    that takes a reading of the whole month for the whole alliance, so a
    caller holding a grouping from a list should prefer it over this.

    None when the character is unknown to Alliance Auth or owned by nobody,
    which on a test system is almost everyone in the journal.
    """
    character = (
        EveCharacter.objects.filter(character_id=character_id)
        .select_related("character_ownership__user__profile__main_character")
        .first()
    )

    if not character:
        return None

    # a one to one reverse accessor raises rather than returning None
    try:
        ownership = character.character_ownership
    except ObjectDoesNotExist:
        return None

    main = ownership.user.profile.main_character

    if not main:
        return None

    others = (
        EveCharacter.objects.filter(character_ownership__user=ownership.user)
        .exclude(character_id=character_id)
        .order_by("character_name")
        .values_list("character_id", "character_name")
    )

    return {
        "main": main.character_name,
        # no level: nothing here has been measured against anything
        "characters": [
            {"id": eve_id, "name": name, "level": None}
            for eve_id, name in others
        ],
    }


def main_characters(character_ids):
    """The main behind each character, as {character_id: (id, name)}.

    Characters Alliance Auth does not know are simply absent - on a test
    system that is all of them, and in production it is the ones who never
    registered. Callers decide what to do with those rather than being handed
    a guess.

    The relation chain is pre-loaded because Alliance Auth's helper walks
    ownership, user and profile, which is three more queries per character
    otherwise.
    """
    characters = EveCharacter.objects.filter(
        character_id__in=character_ids
    ).select_related("character_ownership__user__profile__main_character")

    mains = {}
    for character in characters:
        main = get_main_character_from_evecharacter(character)

        if main:
            mains[character.character_id] = (
                main.character_id, main.character_name
            )

    return mains


# How many groups a list shows. They are ordered by how far out of the
# ordinary a row is, and past the first handful the reader is looking at
# ordinary people. The count of what was left out is printed underneath.
GROUP_LIMIT = 10


def level_for(score: float, top: float = 2 / 3) -> str:
    """Three bands over a score already scaled to nought and one.

    Colour never carries this on its own - the templates put a word beside it
    - and the bands order a list rather than decide anything.

    `top` is where the strongest band starts. For a score measured against a
    configured threshold it has to be one: a list that falls back to the
    nearest misses would otherwise call them strong on a page whose first line
    says nobody reached the threshold.
    """
    if score >= top:
        return "high"

    return "medium" if score >= 1 / 3 else "low"


def grouped(rows, limit: int = GROUP_LIMIT):
    """One entry per main, in the order their most notable character came in.

    A character Alliance Auth does not know becomes a group of its own rather
    than joining an "unknown" bucket: on a test system that would be every
    row, and in production burying an unregistered character is the opposite
    of useful.

    The rows arrive sorted, so the first member of a group is also its most
    notable one and the group inherits its position. That keeps the grouped
    list in the same order as the flat one instead of inventing a second
    ranking nobody asked about.
    """
    mains = main_characters([row["character_id"] for row in rows])

    groups = {}
    for row in rows:
        main = mains.get(row["character_id"])
        key = main[0] if main else row["character_id"]

        group = groups.setdefault(key, {
            "main_id": key,
            "main_name": main[1] if main else row["character_name"],
            "has_main": bool(main),
            "characters": [],
        })
        # on the row as well, because a group of one is printed without a
        # heading and still belongs to somebody
        row["main_name"] = main[1] if main else ""
        group["characters"].append(row)

    for group in groups.values():
        group["count"] = len(group["characters"])
        # the group speaks with the voice of its worst member
        group["level"] = group["characters"][0]["level"]

    ordered = list(groups.values())

    return ordered[:limit], len(ordered)
