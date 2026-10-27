"""Characters a GM moved ISK for, and characters whose wallet is below zero.

A GM booking reads "GM [16519715] issued transaction between <character>
and GM X" (or "... and EVE Central Bank") in the character's own wallet
journal. Finding those means reading every description of every journal,
so a job does it (`store_gm_report`) and the page joins what it left with
what is cheap to read now: balances, mains, Corporations.
"""

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
from eos_tax.db.shared import main_characters
from eos_tax.models import GmReport, MonthlyTax


GM_PREFIX = "GM ["


def named_character(description):
    """The character a GM transaction is about - the first of the two.

    rpartition rather than partition: the second party is "GM X" or "EVE
    Central Bank", neither with an " and " in it, while a character name
    may have one.
    """
    _before, found, rest = description.partition(" between ")
    if not found:
        return ""

    name, found, _other = rest.rpartition(" and ")

    return name if found else ""


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


def store_gm_report():
    GmReport.objects.update_or_create(
        pk=1,
        defaults={
            "report": {"transactions": find_gm_transactions()},
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

    return {"transactions": transactions, "computed_at": stored.computed_at}


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


def get_gm_page(stored):
    """One row per GM transaction, and one per character below zero without one."""
    transactions = stored["transactions"]

    balances = dict(
        CharacterAudit.objects.filter(balance__lt=0).values_list(
            "character__character_id", "balance"
        )
    )
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

    def row_for(character_id, transaction=None):
        character = characters.get(character_id)
        main = mains.get(character_id)

        return {
            "character_id": character_id,
            "character_name": character.character_name if character else str(character_id),
            "corporation_name": character.corporation_name if character else "",
            "alliance_name": (character.alliance_name or "") if character else "",
            "alliance_corporations": history.get(character_id, []),
            "main_name": main[1] if main else "",
            "balance": balances.get(character_id),
            "date": transaction["date"] if transaction else None,
            "amount": transaction["amount"] if transaction else None,
            "named_character": named_character(transaction["description"]) if transaction else "",
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
