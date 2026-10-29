"""Characters a GM moved ISK for, and characters whose wallet is below zero.

A GM booking reads "GM [16519715] issued transaction between <character>
and GM X" (or "... and EVE Central Bank") in the character's own wallet
journal. Finding those means reading every description of every journal,
so a job does it (`store_gm_report`) and the page joins what it left with
what is cheap to read now: balances, mains, Corporations.
"""

import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal

from corptools.models import (
    CharacterAudit,
    CharacterWalletJournalEntry,
    CorporationHistory,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from eos_tax import progress
from eos_tax.app_settings import get_config
from eos_tax.db.payments import _corporation_at
from eos_tax.db.shared import character_ages, main_characters
from eos_tax.models import GM_NOTE_LENGTH, GmNote, GmReport, MonthlyTax
from eos_tax.util import format_age_days


GM_PREFIX = "GM ["

# The counterparty the page opens on: red in the filter, and when it is on
# the page the only box ticked - the user's choice, by its exact name.
FLAGGED_PARTY = "GM X"

# The job's steps on the progress bar. The journal search is one query and
# nearly all of the time; the rest is cheap, but it is where a failure
# after the search would show.
GM_STEPS = ("transactions", "characters")


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


def find_in_alliance(character_ids, config):
    """Whether each character is in a configured alliance, as
    {character_id: bool}; a character neither source knows is absent.

    Alliance Auth's character is as new as its last affiliation update,
    corptools' history as its last record - each misses a move the other
    has seen, so the newer one wins. A tie goes to Alliance Auth: it looked
    at or after the moment the record starts.
    """
    alliance_ids = set(config.alliance_ids())
    # the alliance of today, not `_alliance_corporation_ids`: a Corporation
    # that left keeps its tax rows, and its members are out all the same
    corp_ids = set(
        EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=alliance_ids
        ).values_list("corporation_id", flat=True)
    )

    latest_records = {}
    for character_id, start_date, corporation_id in (
        CorporationHistory.objects.filter(
            character__character__character_id__in=character_ids
        )
        # the last one stands; the same second goes to the higher record_id,
        # as in `_corporation_at`
        .order_by("start_date", "record_id")
        .values_list(
            "character__character__character_id", "start_date", "corporation_id"
        )
    ):
        latest_records[character_id] = (start_date, corporation_id)

    in_alliance = {}
    for character_id, alliance_id, updated in EveCharacter.objects.filter(
        character_id__in=character_ids
    ).values_list("character_id", "alliance_id", "last_updated_affiliations"):
        in_alliance[character_id] = alliance_id in alliance_ids

        # a history always has its character - corptools' audit hangs off it
        record = latest_records.get(character_id)
        # never updated: no moment to weigh the history against
        if record and (updated is None or record[0] > updated):
            in_alliance[character_id] = record[1] in corp_ids

    return in_alliance


def find_account_in_alliance(character_ids, config):
    """Whether each character or another character on its account is in a
    configured alliance, as {character_id: bool}; a character whose whole
    account neither source knows is absent.

    A GM booking or a wallet below zero matters while the player is still
    with us on any of their characters - the user's choice.
    """
    owners = dict(
        CharacterOwnership.objects.filter(
            character__character_id__in=character_ids
        ).values_list("character__character_id", "user_id")
    )
    accounts = defaultdict(set)
    for character_id, user_id in CharacterOwnership.objects.filter(
        user_id__in=set(owners.values())
    ).values_list("character__character_id", "user_id"):
        accounts[user_id].add(character_id)

    # a character nobody registered is an account of its own
    account_of = {
        character_id: accounts[owners[character_id]] if character_id in owners else {character_id}
        for character_id in character_ids
    }
    members = find_in_alliance(set().union(*account_of.values()), config)

    in_alliance = {}
    for character_id, account in account_of.items():
        known = [members[eve_id] for eve_id in account if eve_id in members]
        # one known character out and the rest unknown is "out", not a dash
        if known:
            in_alliance[character_id] = any(known)

    return in_alliance


def store_gm_report(run_id=None):
    """run_id: the progress bar's run, with the steps of GM_STEPS."""
    try:
        with progress.tracked_job(run_id, "transactions"):
            transactions = find_gm_transactions()

        with progress.tracked_job(run_id, "characters"):
            # every character the page can list: the wallets below zero now
            # too, not only those with a transaction
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
                        # as of this run, like the ages - the user's choice;
                        # the whole account, not the character alone
                        "in_alliance": {
                            str(character_id): member
                            for character_id, member in find_account_in_alliance(
                                character_ids, get_config()
                            ).items()
                        },
                    },
                    "computed_at": timezone.now(),
                },
            )
    except Exception:
        progress.skip_unstarted(run_id)
        raise


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
        # nor one stored before it looked at the alliance
        "in_alliance": {
            int(character_id): member
            for character_id, member in stored.report.get("in_alliance", {}).items()
        },
        "computed_at": stored.computed_at,
    }


def clean_note(text):
    """The note as stored: trimmed, line breaks kept, every other control
    or format character dropped.

    The template escapes it and the script only ever sets it as text, so
    markup in a note stays text. What escaping does not catch is a
    character that changes how the rest reads - a right-to-left override
    turns "paid 5" into "5 diap" in the tooltip, a zero-width space hides
    in a name. Those go here.
    """
    kept = "".join(
        char for char in text.replace("\r\n", "\n")
        if char == "\n" or unicodedata.category(char) not in ("Cc", "Cf")
    ).strip()

    if len(kept) > GM_NOTE_LENGTH:
        raise ValueError(f"a note holds at most {GM_NOTE_LENGTH} characters")

    return kept


def _is_listed(character_id, entry_id):
    """Whether the page can show this row - a note nobody can see is only
    a way to fill the table."""
    if entry_id:
        stored = GmReport.objects.filter(pk=1).first()

        return stored is not None and any(
            row["character_id"] == character_id and row["entry_id"] == entry_id
            for row in stored.report["transactions"]
        )

    # the wallet row: below zero now, as the page reads it
    return character_id in _negative_balances()


def save_gm_note(character_id, entry_id, text, user):
    """Stores the note of one row and returns it as stored; an empty note
    removes it. ValueError for a row the page does not list or a note too
    long."""
    if not _is_listed(character_id, entry_id):
        raise ValueError("no such row on the page")

    text = clean_note(text)

    if not text:
        GmNote.objects.filter(character_id=character_id, entry_id=entry_id).delete()
        return ""

    GmNote.objects.update_or_create(
        character_id=character_id,
        entry_id=entry_id,
        defaults={"text": text, "updated_by": user},
    )

    return text


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
    Every box is ticked unless FLAGGED_PARTY is among them; then only its.
    """
    counts = Counter(row["counterparty"] for row in rows)
    flagged = FLAGGED_PARTY in counts

    return [
        {
            "name": name,
            "count": counts[name],
            "flagged": name == FLAGGED_PARTY,
            "checked": name == FLAGGED_PARTY or not flagged,
        }
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
    in_alliance = stored["in_alliance"]
    # only a transaction has a moment to look the Corporation up at
    periods, corporation_names = _corporation_periods(with_transaction)
    player_names = _player_names(transactions)
    notes = {
        (character_id, entry_id): text
        for character_id, entry_id, text in GmNote.objects.filter(
            character_id__in=character_ids
        ).values_list("character_id", "entry_id", "text")
    }

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
            # 0 for the wallet row - see GmNote
            "entry_id": transaction["entry_id"] if transaction else 0,
            # as of the job's run; None for a character it did not know or
            # did not see, which is not the same as "left"
            "in_alliance": in_alliance.get(character_id),
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
            "note": notes.get(
                (character_id, transaction["entry_id"] if transaction else 0), ""
            ),
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
        "note_length": GM_NOTE_LENGTH,
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
