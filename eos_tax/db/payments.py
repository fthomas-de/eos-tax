"""The overview: what each Corporation owes, and whether it paid."""

from datetime import datetime

from allianceauth.eveonline.models import EveCorporationInfo
from corptools.models import CorporationWalletJournalEntry
from django.db.models import Count, Q, Sum
from allianceauth.services.hooks import get_extension_logger

from eos_tax.app_settings import get_config
from eos_tax.models import MonthlyTax
from eos_tax.util import (
    corp_has_payed,
    format_isk,
    get_amount_to_pay,
    get_eve_alliance_id,
    get_pve_income,
)

from eos_tax.db.shared import _month_range

logger = get_extension_logger(__name__)


def set_corp_tax(corp_id: int, corp_name: str = '', tax_value: int = -1, tax_percentage: float = -1, month: int = -1, year: int = -1, payed: bool = False, alliance_tax_rate: float = 0):
    selected_corp = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    # worked out here from the three values this function writes anyway,
    # rather than handed in: a caller that forgot to pass it used to store a
    # silent 0 - every corporation "owing" nothing - and no test noticed
    # rounded, not cut off: the percentages are floats, 0.07 * 100 is
    # 7.000000000000001, and 7M ISK at 7 % corp tax and 10 % alliance tax came
    # out as 9,999,999 instead of the 10,000,000 anybody would work out
    amount_to_pay = round(get_amount_to_pay(tax_value, tax_percentage, alliance_tax_rate))
    # corp_name is handed in by the caller; looking it up again cost a query
    # per corporation and month, for a log line
    logger.info(f"set_corp_tax: {corp_name or corp_id} ({corp_id}), tax_value: {format_isk(tax_value)} tax_percentage {tax_percentage} {month}/{year}")

    if selected_corp:
        selected_corp.corp_name=corp_name
        selected_corp.tax_value=tax_value
        selected_corp.tax_percentage=tax_percentage
        # once paid, always paid: a recalculation after a rate correction
        # finds no payment of the new amount, and must not take back a
        # payment that was already recognised
        selected_corp.payed=selected_corp.payed or payed
        selected_corp.alliance_tax_rate=alliance_tax_rate
        selected_corp.amount_to_pay=amount_to_pay

        selected_corp.save()

    else:
        MonthlyTax.objects.create(
            corp_id=corp_id,
            corp_name=corp_name,
            tax_value=tax_value,
            tax_percentage=tax_percentage,
            month=month,
            year=year,
            payed=payed,
            alliance_tax_rate=alliance_tax_rate,
            amount_to_pay=amount_to_pay,
        )

    return amount_to_pay


def is_payable(month: int, year: int, today=None) -> bool:
    """Whether that month is over far enough to be transferred.

    The reason code appears from the second of the following month, which is
    when the last journal entries of the closed month have arrived. The badge
    and the overview both ask this, so they cannot disagree about what is due.
    """
    today = today or datetime.now()

    if today.day < 2:
        return False

    return year * 100 + month < today.year * 100 + today.month


def get_open_payment_count(dates: list, admin: bool = False, corps=None) -> int:
    """How many rows are waiting to be paid, for the menu badge.

    Rendered on every page of the site, so this counts in the database rather
    than building the overview and measuring it.
    """
    payable = [(month, year) for month, year in dates if is_payable(month, year)]

    if not payable or (not admin and not corps):
        return 0

    periods = Q()
    for month, year in payable:
        periods |= Q(month=month, year=year)

    rows = MonthlyTax.objects.filter(periods, payed=False)

    if not admin:
        rows = rows.filter(corp_id__in=corps)

    return rows.exclude(
        corp_id__in=get_config().blacklisted_corporation_ids()
    ).count()


def get_website_data(dates: list = [], admin: bool = False, corps=[]):
    config = get_config()
    blacklist = config.blacklisted_corporation_ids()
    website_data = []
    for month, year in dates:
        # resolved once per month; the per row fallback used to read the
        # configuration again for every single row
        fallback_rate = config.rate_for(year, month)
        selected_corps = []
        if not admin:
            if corps:
                selected_corps = MonthlyTax.objects.filter(month=month, year=year, corp_id__in=corps).all()
        else:
            selected_corps = MonthlyTax.objects.filter(month=month, year=year).all()

        for selected_corp in selected_corps:
            if selected_corp.corp_id in blacklist:
                continue

            reason_code = (
                f"{selected_corp.corp_id}/{selected_corp.month}/{selected_corp.year}"
                if is_payable(selected_corp.month, selected_corp.year)
                else ""
            )
        
            # rows written before the rate was stored per row carry a zero;
            # resolved once here so the displayed percentage cannot drift.
            # The amount needs no such fallback: migration 0019 worked it out
            # for those rows with this same rule, and set_corp_tax stores it
            # for every row written since.
            applied_rate = selected_corp.alliance_tax_rate or fallback_rate

            website_data.append({
                "corporation_id":selected_corp.corp_id,
                "corporation_name":selected_corp.corp_name,
                "isk_to_pay": format_isk(selected_corp.amount_to_pay),
                "isk_to_pay_value": selected_corp.amount_to_pay,
                "month":selected_corp.month,
                "year":selected_corp.year,
                "period": selected_corp.year * 100 + selected_corp.month,
                "corp_tax_rate":float("%.2f" % selected_corp.tax_percentage),
                # stored as a fraction, shown as a percentage like the corp tax
                "alliance_tax_rate":float("%.2f" % (applied_rate * 100)),
                "payed":selected_corp.payed,
                "reason":reason_code,
            })
    # the payable month first (it carries a reason code) - unpaid rows of it
    # ahead of paid ones - then the not yet payable follow-up month; corp
    # name breaks every tie, so a group never reorders itself by date
    website_data.sort(key=lambda x: (not x["reason"], x["payed"], x["corporation_name"]))

    return website_data


def update_corp(corp_id: int, month: int = -1, year: int = -1) -> dict:
    """Recalculate one Corporation's month and persist it.

    Returns every step the stored figures are built from - "ok": False and a
    machine readable "reason" when nothing could be calculated. The
    settings page's recalculate button renders this as a log; the periodic
    task, the only other caller, ignores it.
    """
    corp_info = EveCorporationInfo.objects.filter(corporation_id=corp_id).first()
    if not corp_info:
        logger.warning(f"dbcon update_corp: unknown corporation {corp_id} - skipped")
        return {
            "ok": False, "reason": "unknown_corp",
            "corp_id": corp_id, "month": month, "year": year,
        }

    if corp_info.tax_rate is None:
        # Alliance Auth leaves the rate empty for a corporation it never
        # pulled from ESI - a holding imported by hand is the usual one.
        # Formatting None raises, and the task runs one subtask per
        # corporation, so this would take that subtask down silently while
        # the page kept showing the month as uncalculated.
        logger.warning(
            f"dbcon update_corp: {corp_info.corporation_name} ({corp_id}) has "
            f"no ingame tax rate - skipped"
        )
        return {
            "ok": False, "reason": "no_tax_rate", "corp_id": corp_id,
            "corp_name": corp_info.corporation_name, "month": month, "year": year,
        }

    corp_tax_rate = float("%.4f" % corp_info.tax_rate)
    logger.info(f"dbcon update_corp1: {corp_info.corporation_name} ({corp_id}): tax_rate {corp_tax_rate} - {month}/{year}")

    config = get_config()
    alliance_tax_rate = config.rate_for(year, month)

    if not alliance_tax_rate:
        # a month the alliance does not tax owes nothing, and a row of 0 ISK
        # can never be matched by a payment - it sat in the menu badge as
        # outstanding for good. An existing row is left alone rather than
        # deleted: it may already carry a payment.
        logger.info(
            f"dbcon update_corp: {corp_info.corporation_name} ({corp_id}): "
            f"alliance tax rate 0 - no row for {month}/{year}"
        )
        return {
            "ok": False, "reason": "no_alliance_rate", "corp_id": corp_id,
            "corp_name": corp_info.corporation_name, "month": month, "year": year,
        }

    start, end = _month_range(year, month)

    # filter is on a single corp, so the whole month collapses into one sum
    entries = CorporationWalletJournalEntry.objects.filter(
        tax_receiver_id=corp_id,
        ref_type__in=config.tax_types,
        date__gte=start,
        date__lt=end,
    )
    # one sum per tax type, so the log can show what each contributed - the
    # total below is their sum, which is what the rest of the calculation
    # uses. Grouping this way costs one query, the same as the plain
    # aggregate it replaces.
    by_type = list(
        entries.values("ref_type")
        .annotate(sum=Sum("amount"), count=Count("id"))
        .order_by("ref_type")
    )
    tax_sum = sum(row["sum"] for row in by_type)

    if not tax_sum:
        logger.info(f"dbcon update_corp2: {corp_info.corporation_name} ({corp_id}): no journal entries - {month}/{year}")
        return {
            "ok": False, "reason": "no_entries", "corp_id": corp_id,
            "corp_name": corp_info.corporation_name, "corp_tax_percent": corp_tax_rate * 100,
            "tax_types": config.tax_types, "month": month, "year": year,
        }

    overall_ratted = int(tax_sum)
    payed = corp_has_payed(
        corp_id=corp_id,
        month=month,
        year=year,
        config=config,
        corp_name=corp_info.corporation_name,
    )
    logger.info(f"dbcon update_corp3: {corp_info.corporation_name} ({corp_id}): payed {payed} - {month}/{year}")

    # rounded to the precision the rate is stored with, so the float noise of
    # the multiplication neither reaches the amount nor the log
    corp_tax_percent = round(corp_tax_rate * 100, 2)
    gross_income = round(get_pve_income(overall_ratted, corp_tax_percent))

    amount_to_pay = set_corp_tax(
        corp_id=corp_id,
        corp_name=corp_info.corporation_name,
        tax_value=overall_ratted,
        tax_percentage=corp_tax_percent,
        month=month,
        year=year,
        payed=payed,
        alliance_tax_rate=alliance_tax_rate,
    )

    return {
        "ok": True,
        "corp_id": corp_id,
        "corp_name": corp_info.corporation_name,
        "month": month,
        "year": year,
        "tax_types": config.tax_types,
        "by_type": by_type,
        "entries_considered": sum(row["count"] for row in by_type),
        "tax_value": overall_ratted,
        "corp_tax_percent": corp_tax_percent,
        "gross_income": gross_income,
        "alliance_tax_rate": alliance_tax_rate,
        "alliance_tax_percent": float("%.2f" % (alliance_tax_rate * 100)),
        "amount_to_pay": amount_to_pay,
        "payed": payed,
    }


def get_all_corps_for_user(characters: list = []):
    corporation_ids = []
    for char in characters:
        if char.corporation_id:
            corporation_ids.append(char.corporation_id)
    return corporation_ids


def get_tax_corp(corps:list = []):
    # input: user corps
    logger.debug(corps)

    config = get_config()
    alliance_ids = config.alliance_ids()
    holding = config.tax_corporation

    # 1: get all tax_alliances, the user is in 
    tax_alliances = { 
        x.alliance_id for x in EveCorporationInfo.objects.filter(corporation_id__in=corps).all() 
            if get_eve_alliance_id(x.alliance_id) in alliance_ids}
    logger.debug(tax_alliances)

    if holding and holding.alliance_id in tax_alliances:
        return holding.corporation_name
