"""Characters a GM moved ISK for, and characters whose wallet is below zero.

A GM booking reads "GM [16519715] issued transaction between <character>
and GM X" (or "... and EVE Central Bank") in the character's own wallet
journal. Finding those means reading every description of every journal,
so a job does it (`store_gm_report`) and the page joins what it left with
what is cheap to read now: balances, mains, Corporations.
"""

from collections import Counter, defaultdict
from decimal import Decimal

from corptools.models import (
    CharacterAudit,
    CharacterWalletJournalEntry,
    CorporationHistory,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from eos_tax.app_settings import get_config
from eos_tax.db.payments import _corporation_at
from eos_tax.db.shared import character_ages, main_characters
from eos_tax.models import GmReport, MonthlyTax
from eos_tax.util import format_age_days


GM_PREFIX = "GM ["


def _parties(description):
    """The two parties of a GM transaction, ("", "") without the pattern.

    rpartition rather than partition: the second party is "GM X" or "EVE
    Central Bank", neither with an " and " in it, while a character name
    may have one.
    """
    _before, found, rest = description.partition(" between ")
    if not found:
        return "", ""

    name, found, other = rest.rpartition(" and ")

    return (name, other) if found else ("", "")


def sides(description, player_names):
    """(the character a GM transaction is about, where the ISK came from or
    went to), ("", "") without the pattern.

    The order of the two parties says nothing: a GM taking ISK back books
    "between GM X and <character>". So the side that is a known character
    (`player_names`, casefolded) is the character's, the other one the
    counterparty - and with both sides players there is no counterparty,
    because the filter offers only the GM side.
    """
    first, second = _parties(description)

    if second.casefold() not in player_names:
        return first, second

    if first.casefold() not in player_names:
        return second, first

    return first, ""


def _player_names(transactions):
    """The parties of the transactions that are characters Alliance Auth knows.

    Every wallet owner is one, so a booking naming the owner second is caught
    even when nobody else is registered.
    """
    names = {
        party
        for row in transactions
        for party in _parties(row["description"])
        if party
    }

    # casefolded: the database matches the names regardless of case, so the
    # comparison afterwards has to as well
    return {
        name.casefold()
        for name in EveCharacter.objects.filter(character_name__in=names).values_list(
            "character_name", flat=True
        )
    }


def find_gm_transactions():
    """Every GM transaction in the character wallet journals, newest first."""
    return [
        {
            "character_id": character_id,
            "entry_id": entry_id,
            "date": date,
            "amount": amount,
            "description": description,
        }
        for character_id, entry_id, date, amount, description in (
            CharacterWalletJournalEntry.objects.filter(
                description__startswith=GM_PREFIX
            )
            .order_by("-date", "-entry_id")
            .values_list(
                "character__character__character_id",
                "entry_id",
                "date",
                "amount",
                "description",
            )
        )
    ]


def _negative_balances():
    return dict(
        CharacterAudit.objects.filter(balance__lt=0).values_list(
            "character__character_id", "balance"
        )
    )


def find_age_days(character_ids):
    """Each character's age in days, as {character_id: days}; a character
    without a known birthday is absent."""
    today = timezone.now().date()

    return {
        character_id: (today - birthday).days
        for character_id, birthday in character_ages(character_ids).items()
    }


def store_gm_report():
    transactions = find_gm_transactions()
    # every character the page can list: the wallets below zero now too, not
    # only those with a transaction
    character_ids = {row["character_id"] for row in transactions} | set(
        _negative_balances()
    )

    GmReport.objects.update_or_create(
        pk=1,
        defaults={
            "report": {
                "transactions": transactions,
                # JSON object keys are text
                "age_days": {
                    str(character_id): days
                    for character_id, days in find_age_days(character_ids).items()
                },
            },
            "computed_at": timezone.now(),
        },
    )


def get_stored_gm_report():
    """What the job last stored, or None before its first run."""
    stored = GmReport.objects.filter(pk=1).first()

    if stored is None:
        return None

    # JSON keeps both as text: the date filter prints nothing for a string,
    # and a Decimal is what the amount was
    transactions = [
        {
            **row,
            "date": parse_datetime(row["date"]),
            "amount": Decimal(row["amount"]) if row["amount"] is not None else None,
        }
        for row in stored.report["transactions"]
    ]

    return {
        "transactions": transactions,
        # a report stored before the job counted ages has none
        "age_days": {
            int(character_id): days
            for character_id, days in stored.report.get("age_days", {}).items()
        },
        "computed_at": stored.computed_at,
    }


def _alliance_corporation_ids(config):
    """Corporations of the configured alliances, now or in any taxed month.

    Alliance Auth only knows a Corporation's alliance of today; one that
    left since still has its tax rows, and a character's time there is
    still time inside the alliance.
    """
    return set(
        EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=config.alliance_ids()
        ).values_list("corporation_id", flat=True)
    ) | set(MonthlyTax.objects.values_list("corp_id", flat=True))


def _alliance_history(character_ids, corp_ids):
    """Each character's Corporations inside the alliance, in the order joined."""
    history = {}
    for character_id, corporation_name in (
        CorporationHistory.objects.filter(
            character__character__character_id__in=character_ids,
            corporation_id__in=corp_ids,
        )
        .order_by("start_date")
        .values_list("character__character__character_id", "corporation_name__name")
    ):
        names = history.setdefault(character_id, [])
        # a return to an earlier Corporation is a second record, not news
        if corporation_name not in names:
            names.append(corporation_name)

    return history


def _corporation_periods(character_ids):
    """Each character's whole corporation history, oldest first, and the
    names of the Corporations in it.

    (start, corporation_id) pairs, the shape `_corporation_at` searches -
    not the name: two records starting the same second would make bisect
    compare a name with its float sentinel.
    """
    periods = defaultdict(list)
    names = {}
    for character_id, start_date, corporation_id, corporation_name in (
        CorporationHistory.objects.filter(
            character__character__character_id__in=character_ids
        )
        .order_by("start_date", "record_id")
        .values_list(
            "character__character__character_id",
            "start_date",
            "corporation_id",
            "corporation_name__name",
        )
    ):
        periods[character_id].append((start_date, corporation_id))
        names[corporation_id] = corporation_name

    return periods, names


def _parties_of(rows):
    """One filter entry per counterparty on the page, with its row count.

    Read off the rows rather than a fixed list: a GM may book against any
    name, and a box nobody can tick is no use. By name, the rows without
    one - a wallet below zero, a description of another shape - last.
    """
    counts = Counter(row["counterparty"] for row in rows)

    return [
        {"name": name, "count": counts[name]}
        for name in sorted(counts, key=lambda name: (name == "", name.casefold()))
    ]


def get_gm_page(stored):
    """One row per GM transaction, and one per character below zero without one."""
    transactions = stored["transactions"]

    balances = _negative_balances()
    with_transaction = {row["character_id"] for row in transactions}
    negative_only = set(balances) - with_transaction
    character_ids = with_transaction | negative_only

    # the balance of every listed character, not only the negative ones
    balances.update(
        CharacterAudit.objects.filter(
            character__character_id__in=with_transaction
        ).values_list("character__character_id", "balance")
    )
    characters = {
        character.character_id: character
        for character in EveCharacter.objects.filter(character_id__in=character_ids)
    }
    mains = main_characters(character_ids)
    history = _alliance_history(
        character_ids, _alliance_corporation_ids(get_config())
    )
    age_days = stored["age_days"]
    # only a transaction has a moment to look the Corporation up at
    periods, corporation_names = _corporation_periods(with_transaction)
    player_names = _player_names(transactions)

    def corporation_then(character_id, transaction):
        if not transaction:
            return ""

        return corporation_names.get(
            _corporation_at(periods.get(character_id), transaction["date"]), ""
        )

    def row_for(character_id, transaction=None):
        character = characters.get(character_id)
        main = mains.get(character_id)
        named, other = (
            sides(transaction["description"], player_names) if transaction else ("", "")
        )

        return {
            "character_id": character_id,
            "character_name": character.character_name if character else str(character_id),
            "corporation_name": character.corporation_name if character else "",
            # empty without a history reaching back that far
            "corporation_then": corporation_then(character_id, transaction),
            "alliance_name": (character.alliance_name or "") if character else "",
            "alliance_corporations": history.get(character_id, []),
            "main_name": main[1] if main else "",
            # as of the job's run, like the bots lists. Gone below zero since:
            # no age until the next run
            "age": format_age_days(age_days.get(character_id)),
            # what the Age column sorts by - "2 y" and "5 mo" do not sort as text
            "age_days": age_days.get(character_id),
            "balance": balances.get(character_id),
            "date": transaction["date"] if transaction else None,
            "amount": transaction["amount"] if transaction else None,
            "named_character": named,
            "counterparty": other,
            "description": transaction["description"] if transaction else "",
        }

    rows = [row_for(row["character_id"], row) for row in transactions]
    # after the dated rows, the deepest wallet first
    rows += [
        row_for(character_id)
        for character_id in sorted(negative_only, key=lambda eve_id: balances[eve_id])
    ]

    return {
        "rows": rows,
        "parties": _parties_of(rows),
        "stats": {
            "transactions": len(transactions),
            "characters": len({row["character_id"] for row in rows}),
            "negative": sum(
                1 for balance in balances.values()
                if balance is not None and balance < 0
            ),
        },
        "computed_at": stored["computed_at"],
    }
