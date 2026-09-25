"""Fixtures every test module builds.

Kept apart from base.py, which is about how a test runs, not about what it
runs against. Importing these from test_views - which is what five modules
used to do - made one test module a library for the others and tied their
fixtures to whatever that file happened to need.

The ids are shared too. They were declared four times over with the same
values, so a test reading Bravo Corp in one module and BRAVO_CORP_ID in
another was talking about the same corporation without saying so.
"""

import datetime
import itertools

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)
from corptools.models import (
    CorporationAudit,
    CorporationWalletDivision,
    CorporationWalletJournalEntry,
    EveName,
)
from django.contrib.auth.models import Permission, User

from django.db import models as django_models

from eos_tax.app_settings import get_config
from eos_tax.forms import TaxConfigurationForm
from eos_tax.models import MonthlyTax, TaxConfiguration
from eos_tax.util import get_amount_to_pay

def settings_numbers():
    """Every plain setting at its model default, as form input.

    Read off the model rather than listed here: the settings form rejects a
    POST that leaves a number out, and the failure surfaces as a redirect that
    did not happen rather than as a missing field. A new threshold would
    otherwise break every test that saves settings, none of which is about it.

    Switches are here for the opposite reason. An unchecked box is simply
    absent from a POST, so a payload that skipped them would quietly turn off
    everything that ships on - and the tests would then be asserting about a
    configuration nobody runs. Only the ones defaulting to on are sent, which
    is what "at its default" means for a checkbox.

    Decimals are left out on purpose - tax_rate is entered as a percentage and
    stored as a fraction, so its model default is not what a form takes.
    """
    payload = {}

    for name in TaxConfigurationForm.Meta.fields:
        field = TaxConfiguration._meta.get_field(name)

        if isinstance(field, django_models.PositiveSmallIntegerField):
            payload[name] = str(field.default)
        elif isinstance(field, django_models.BooleanField) and field.default:
            payload[name] = "on"

    return payload


# Enough entries in an hour to make it active. Read off the model rather
# than repeated here, so the fixtures cannot drift away from the rule the
# app applies.
ACTIVE_HOUR_MIN_ENTRIES = TaxConfiguration._meta.get_field(
    "bot_hours_min_entries"
).default

TAXED_ALLIANCE_ID = 99000001
OTHER_ALLIANCE_ID = 99000002

BRAVO_CORP_ID = 98000001
ALPHA_CORP_ID = 98000002
OUTSIDER_CORP_ID = 98000003

# the rate a real configuration carries, so income and tax are not one figure
TAX_RATE = 0.1

RATTER_ID = 2100000001
CASUAL_ID = 2100000002

YEAR = 2026
MONTH = 5

# small thresholds keep the fixtures readable: more than 2 hours on at least
# 2 days - the day threshold counts once it is reached, the hour one only
# once it is passed, the way the settings page words them
MIN_HOURS = 2
MIN_DAYS = 2

entry_ids = itertools.count(1)


def create_user(username, character_id, corporation_id, corporation_name,
                permissions=()):
    """Build a user AA will actually let through to an app view.

    Every url registered through a UrlHook is wrapped in
    ``main_character_required``, so a user without an owned main character is
    redirected to the dashboard regardless of their permissions.
    """
    user = User.objects.create_user(username, f"{username}@example.com", "password")

    character = EveCharacter.objects.create(
        character_id=character_id,
        character_name=f"{username} character",
        corporation_id=corporation_id,
        corporation_name=corporation_name,
        corporation_ticker=corporation_name[:5].upper(),
    )
    CharacterOwnership.objects.create(
        character=character, user=user, owner_hash=f"owner-hash-{character_id}"
    )
    user.profile.main_character = character
    user.profile.save()

    for codename in permissions:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="eos_tax", codename=codename
            )
        )

    return User.objects.get(pk=user.pk)  # drop the cached permissions


def create_alt(owner, character_id, name,
               corporation_id=BRAVO_CORP_ID, corporation_name="Bravo Corp"):
    """A second character on an account that already has a main.

    The journal names characters Alliance Auth may never have seen, so the
    grouping only finds a main where an ownership says so - which is what this
    writes.
    """
    alt = EveCharacter.objects.create(
        character_id=character_id,
        character_name=name,
        corporation_id=corporation_id,
        corporation_name=corporation_name,
        corporation_ticker=corporation_name[:5].upper(),
    )
    CharacterOwnership.objects.create(
        character=alt, user=owner, owner_hash=f"alt-owner-hash-{character_id}"
    )

    return alt


def create_alliance(alliance_id, name):
    return EveAllianceInfo.objects.create(
        alliance_id=alliance_id,
        alliance_name=name,
        alliance_ticker=name[:5].upper(),
    )


def create_corporation(corp_id, name, alliance, tax_rate=TAX_RATE, **fields):
    return EveCorporationInfo.objects.create(
        corporation_id=corp_id,
        corporation_name=name,
        corporation_ticker=name[:5].upper(),
        alliance=alliance,
        tax_rate=tax_rate,
        **fields,
    )


def enable_current_month():
    """The overview shows nothing unless at least one month is switched on."""
    config = TaxConfiguration.get_solo()
    config.current_month = True
    config.save()

    return config


def create_tax_row(corp_id, corp_name, payed=False, tax_value=1_000_000_000,
                   tax_percentage=10.0, month=None, year=None,
                   alliance_tax_rate=0):
    """One calculated month for one Corporation.

    Defaults to the running month, which is what the overview shows; the
    statistics pass a year and a month of their own. amount_to_pay is worked
    out the same way update_corp() works it out, so a row built here behaves
    like one a real task wrote - a test comparing against its own call to
    get_amount_to_pay() is comparing against what this factory already
    stored, not against a live recalculation.
    """
    now = datetime.datetime.now()
    month = now.month if month is None else month
    year = now.year if year is None else year
    applied_rate = alliance_tax_rate or get_config().rate_for(year, month)

    return MonthlyTax.objects.create(
        corp_id=corp_id,
        corp_name=corp_name,
        tax_value=tax_value,
        tax_percentage=tax_percentage,
        month=month,
        year=year,
        payed=payed,
        alliance_tax_rate=alliance_tax_rate,
        amount_to_pay=int(get_amount_to_pay(tax_value, tax_percentage, applied_rate)),
    )


def configure():
    config = TaxConfiguration.get_solo()
    config.tax_types = ["bounty_prizes"]
    config.bot_min_hours_per_day = MIN_HOURS
    config.bot_min_days_per_month = MIN_DAYS
    config.save()
    config.tax_alliances.set(
        EveAllianceInfo.objects.filter(alliance_id=TAXED_ALLIANCE_ID)
    )

    return config


def build_corporations():
    taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
    other = create_alliance(OTHER_ALLIANCE_ID, "Other Alliance")

    divisions = {}
    for corp_id, name, alliance in (
        (BRAVO_CORP_ID, "Bravo Corp", taxed),
        (OUTSIDER_CORP_ID, "Outsider Corp", other),
    ):
        corporation = create_corporation(corp_id, name, alliance)
        audit = CorporationAudit.objects.create(corporation=corporation)
        divisions[corp_id] = CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

    EveName.objects.create(eve_id=RATTER_ID, name="Busy Ratter", category="character")
    EveName.objects.create(eve_id=CASUAL_ID, name="Casual Pilot", category="character")

    return divisions


def add_entries(
    division,
    character_id,
    day,
    hours,
    ref_type="bounty_prizes",
    corp_id=BRAVO_CORP_ID,
    tax=1000,
    entries=ACTIVE_HOUR_MIN_ENTRIES,
):
    """Taxed journal entries in the given hours of the day, in EVE time.

    Enough entries per hour to make it active, because that is what a test
    saying "these hours" means. Pass entries=1 to write a lone one.
    """
    for hour in hours:
        for minute in range(entries):
            CorporationWalletJournalEntry.objects.create(
                division=division,
                # spread within the hour, so the entries are distinguishable
                date=datetime.datetime(
                    YEAR, MONTH, day, hour, minute, tzinfo=datetime.timezone.utc
                ),
                description="got bounty prizes for killing pirates",
                entry_id=next(entry_ids),
                ref_type=ref_type,
                first_party_id=1000125,
                second_party_id=character_id,
                second_party_name_id=character_id,
                tax_receiver_id=corp_id,
                amount=tax,
                tax=tax,
            )
