from datetime import date, datetime, timezone

from dateutil.relativedelta import relativedelta

from django.db.models import Q
from django.utils.translation import gettext

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

def get_eve_alliance_id(id:int):
    alliance = EveAllianceInfo.objects.filter(id=id).first()
    if alliance:
        return alliance.alliance_id

def get_pve_income(tax_value:int, corp_tax:float):
    """Gross bounty income the ingame corp tax was skimmed from."""
    if corp_tax == 0:
        return float(tax_value)

    return float(tax_value / (corp_tax / 100))

def format_clock(hour: float) -> str:
    """A time of day from a fractional hour: 14.6 becomes 14:36.

    The circular mean of somebody's payouts lands between hours, and a reader
    should not have to work out what six tenths of an hour is.
    """
    if hour is None:
        return ""

    minutes = int(round(hour * 60)) % (24 * 60)

    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_duration(hours: float) -> str:
    """A length of time: 4.7 becomes 4 h 42 min.

    Both parts carry their unit, because the alternative - 4:42 - reads as a
    time of day on a page that also shows those.
    """
    if hours is None:
        return ""

    minutes = int(round(hours * 60))
    whole, rest = divmod(minutes, 60)

    # named here rather than inside the f-strings below: xgettext reads the
    # source instead of running it and does not descend into an
    # interpolation, so a gettext call in there is never extracted and the
    # unit would stay English in every language
    hour_unit = gettext("h")
    minute_unit = gettext("min")

    if not whole:
        return f"{rest} {minute_unit}"

    if not rest:
        return f"{whole} {hour_unit}"

    return f"{whole} {hour_unit} {rest} {minute_unit}"


def format_age(birthday: date, today: date = None) -> str:
    """How long ago a character was created: one unit, not a calendar.

    A column has no room for "3 years, 2 months", and the day this reads as
    a bot detection signal - a character ratting round the clock a week
    after creation - the remainder never matters, only the order of
    magnitude. None when Alliance Auth never had a birthday for the
    character at all, which is most of the journal on a test system.
    """
    if birthday is None:
        return ""

    today = today or datetime.now(timezone.utc).date()
    days = (today - birthday).days

    if days < 0:
        return ""

    # named here rather than inside the f-strings below: xgettext reads the
    # source instead of running it and does not descend into an
    # interpolation, so a gettext call in there is never extracted and the
    # unit would stay English in every language
    day_unit = gettext("d")
    month_unit = gettext("mo")
    year_unit = gettext("y")

    if days >= 365:
        return f"{days // 365} {year_unit}"

    if days >= 30:
        return f"{days // 30} {month_unit}"

    return f"{days} {day_unit}"


def get_amount_to_pay(tax_value:int, corp_tax:float, tax_rate:float = None):
    """Share of the gross income the corp owes the alliance.

    Pass the rate stored on the MonthlyTax row when showing a figure that was
    already calculated - only a fresh calculation should reach for the current
    configuration, or changing the rate would rewrite the past.
    """
    if tax_rate is None:
        tax_rate = float(get_config().tax_rate)

    return get_pve_income(tax_value, corp_tax) * tax_rate

def _one_side(rows: list) -> list:
    """The payments of one side of the journal, as positive amounts.

    corptools reads every wallet it has a token for, so a transfer can show up
    twice: as income in the holding's journal and as an expense in the
    payer's. Added up over both it counts double - a corporation paying
    exactly what it owed would read as having paid twice that. Either side on
    its own holds every transfer it saw once; the fuller one wins, because a
    holding without a token, or a payer without one, leaves its side empty.
    """
    # corptools allows an entry without an amount; it paid nothing either way
    received = [row for row in rows if (row["amount"] or 0) > 0]
    sent = [row for row in rows if (row["amount"] or 0) < 0]

    side = received if sum(row["amount"] for row in received) >= -sum(row["amount"] for row in sent) else sent

    # kept as the Decimal the journal holds: cut to whole ISK one by one,
    # three transfers of x.50 would add up to a whole ISK less than came in
    return sorted(
        ({"date": row["date"], "amount": abs(row["amount"])} for row in side),
        key=lambda payment: payment["date"],
    )


def find_payment(corp_id:int, month:int, year:int, config=None, corp_name:str = None) -> dict:
    """What came in for that month, and whether it settles what was owed.

    "payed" is the answer the row gets; "match" says how it was reached -
    "exact" for one payment of exactly the amount owed, "sum" for the
    payments added up, None for no match. "amount_paid" is what came in (None
    when nothing did), "payments" the transfers it is made of.

    A row already marked paid is still looked up: a second transfer can arrive
    after the first one settled it, and rows paid before the amount was
    stored get it on the next run that way. Its flag stays set whatever the
    journal says - see set_corp_tax.

    Pass config and corp_name when the caller already holds them: both used to
    cost their own query, once per corporation and month.
    """
    nothing = {"payed": False, "match": None, "amount_paid": None, "payments": [], "paid_at": None}

    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data:
        return nothing

    config = config or get_config()
    holding_corp_id = config.holding_corporation_id()

    if not holding_corp_id:
        # nothing configured that a payment could have gone to
        return {**nothing, "payed": tax_data.payed}

    # the figure the overview shows, read off the same row - worked out here
    # a second time it could disagree with the page by a rounding step, and
    # a payment of exactly what the page said would then not match
    amount_to_pay = tax_data.amount_to_pay

    journal = CorporationWalletJournalEntry.objects.filter(
        second_party_id=holding_corp_id,
        ref_type__in=DONATION_TYPES,
        # a payment for a month cannot predate that month, and the bound lets
        # the database use its index on date instead of reading the whole
        # journal - the reason filter below never can, LIKE %...% is unindexable
        date__gte=datetime(year, month, 1, tzinfo=timezone.utc),
    )

    if config.use_reason:
        payments = _one_side(list(
            journal.filter(reason__icontains=f"{corp_id}/{month}/{year}")
            .values("date", "amount")
        ))
        # whole ISK like amount_to_pay, cut rather than rounded: a transfer of
        # x.99 short of the amount owed must not round up to settling it
        total = int(sum(payment["amount"] for payment in payments))

        # the exact amount first, the sum only when no single payment fits:
        # either way the row is settled, but the log can then tell a transfer
        # of the right amount from several that only add up to it
        exact = next((payment for payment in payments if payment["amount"] == amount_to_pay), None)
        if exact:
            match = "exact"
            paid_at = exact["date"]
        elif payments and total >= amount_to_pay:
            match = "sum"
            # the transfer that reached the amount, not the last one: a second
            # transfer after the row was settled is overpaid, not the payment
            running = 0
            for payment in payments:
                running += payment["amount"]
                if int(running) >= amount_to_pay:
                    paid_at = payment["date"]
                    break
        else:
            match = None
            paid_at = None

        amount_paid = total if payments else None
    else:
        # the amount is all there is to go by, so only the exact one can be
        # told to belong to this row - a larger transfer could be anybody's.
        # Both signs in one pass; this used to be two scans in sequence
        payment = journal.filter(
            Q(amount=-amount_to_pay) | Q(amount=amount_to_pay)
        ).order_by("date").values("date", "amount").first()
        payments = [{"date": payment["date"], "amount": amount_to_pay}] if payment else []
        match = "exact" if payment else None
        amount_paid = amount_to_pay if payment else None
        paid_at = payment["date"] if payment else None

    payed = tax_data.payed or match is not None
    name = corp_name or get_corp_name(corp_id)
    owed = format_isk(amount_to_pay)
    found = f"Payment found ({match})" if match else "No Payment found"
    paid = format_isk(amount_paid) if amount_paid is not None else "-"

    logger.info(
        f"find_payment: {found} (to pay: {owed}, paid: {paid} in {len(payments)}): "
        f"from {name} to holding corp {holding_corp_id} for >{corp_id}/{month}/{year}<"
    )

    return {"payed": payed, "match": match, "amount_paid": amount_paid, "payments": payments, "paid_at": paid_at}
