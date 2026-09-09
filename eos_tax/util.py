from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from django.db.models import Q

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry

from eos_tax.models import MonthlyTax
from eos_tax.app_settings import get_config

from allianceauth.services.hooks import get_extension_logger

DONATION_TYPES = ["player_donation", "corporation_account_withdrawal"]
logger = get_extension_logger(__name__)

def get_dates():

    config = get_config()
    dates = []

    if config.last_month:
        previous = datetime.now() - relativedelta(months=1)
        dates.append((previous.month, previous.year))

    if config.current_month:
        now = datetime.now()
        dates.append((now.month, now.year))

    return dates

def format_isk(isk):
    return str(f'{int(isk):,}').replace(',','.')

def get_corp_name(corp_id:int):
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if corp_info:
        return corp_info.corporation_name

def get_alliance_name(corp_id:int):
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if not corp_info:
        return

    alliance_info = EveAllianceInfo.objects.filter(id=corp_info.alliance_id).first()
    if alliance_info:
        return alliance_info.alliance_name

def get_eve_alliance_id(id:int):
    alliance = EveAllianceInfo.objects.filter(id=id).first()
    if alliance:
        return alliance.alliance_id

def get_pve_income(tax_value:int, corp_tax:float):
    """Gross bounty income the ingame corp tax was skimmed from."""
    if corp_tax == 0:
        return float(tax_value)

    return float(tax_value / (corp_tax / 100))

def get_amount_to_pay(tax_value:int, corp_tax:float, tax_rate:float = None):
    """Share of the gross income the corp owes the alliance.

    Pass the rate stored on the MonthlyTax row when showing a figure that was
    already calculated - only a fresh calculation should reach for the current
    configuration, or changing the rate would rewrite the past.
    """
    if tax_rate is None:
        tax_rate = float(get_config().tax_rate)

    return get_pve_income(tax_value, corp_tax) * tax_rate

def corp_has_payed(corp_id:int, month:int, year:int, config=None, corp_name:str = None):
    """Whether the corporation already paid what it owed for that month.

    Pass config and corp_name when the caller already holds them: both used to
    cost their own query, once per corporation and month.
    """
    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data:
        return False

    # dont check, if payed was set before
    if tax_data.payed:
        return True

    config = config or get_config()
    holding_corp_id = config.holding_corporation_id()

    if not holding_corp_id:
        # nothing configured that a payment could have gone to
        return False

    # rows written before the rate was stored fall back to whatever the
    # schedule says for that month, not to today's rate
    applied_rate = tax_data.alliance_tax_rate or config.rate_for(year, month)
    amount_to_pay = int(
        get_amount_to_pay(tax_data.tax_value, tax_data.tax_percentage, applied_rate)
    )

    payments = CorporationWalletJournalEntry.objects.filter(
        second_party_id=holding_corp_id,
        ref_type__in=DONATION_TYPES,
        # a payment for a month cannot predate that month, and the bound lets
        # the database use its index on date instead of reading the whole
        # journal - the reason filter below never can, LIKE %...% is unindexable
        date__gte=datetime(year, month, 1, tzinfo=timezone.utc),
    )

    if config.use_reason:
        payments = payments.filter(
            reason__icontains=f"{corp_id}/{month}/{year}"
        ).filter(Q(amount__lte=-amount_to_pay) | Q(amount__gte=amount_to_pay))
    else:
        payments = payments.filter(Q(amount=-amount_to_pay) | Q(amount=amount_to_pay))

    # both signs in one pass; this used to be two scans in sequence.
    # exists() stops at the first hit instead of fetching every match
    payed = payments.exists()
    name = corp_name or get_corp_name(corp_id)
    owed = format_isk(amount_to_pay)
    found = "Payment found" if payed else "No Payment found"

    logger.info(
        f"corp_has_payed: {found} (to pay: {owed}): from {name} to holding corp "
        f"{holding_corp_id} for >{corp_id}/{month}/{year}<"
    )

    return payed
