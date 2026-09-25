"""The statistics page: monthly tax and PvE income per corporation.

The colour science itself lives in eos_tax.db.palette, which does no queries
at all - this module only decides which corporation gets which palette slot.
"""

from eos_tax.app_settings import get_config
from eos_tax.models import MonthlyTax
from eos_tax.util import get_pve_income

from eos_tax.db.palette import _chart_palette
from eos_tax.db.shared import _corporation_infos


# Line styles still carry part of the identity past the first few
# corporations, so hue never has to do the job alone.
CHART_DASHES = [[], [7, 4], [2, 3]]

# How many colours a chart uses before the next corporation gets a line style
# instead of yet another hue. Past about eight, colours stop being told apart
# on a line; the palette only grows beyond this once every style is used up,
# so no two corporations ever share both colour and style.
CHART_COLOURS = 8


def _colour_count(corporations: int) -> int:
    """How many colours the palette needs for that many corporations."""
    return max(CHART_COLOURS, -(-corporations // len(CHART_DASHES)))


def get_statistics_years():
    """Years that carry data. There is no backfill, so this grows month by month."""
    return sorted(MonthlyTax.objects.values_list("year", flat=True).distinct(), reverse=True)


def _colour_slots():
    """One stable palette slot per corporation, derived from every corporation
    that has data - not from the filtered result. Switching year or alliance
    therefore never repaints the corporations that stay on screen."""
    corp_ids = sorted(set(MonthlyTax.objects.values_list("corp_id", flat=True)))
    return {corp_id: slot for slot, corp_id in enumerate(corp_ids)}


def get_statistics_alliances():
    """Configured alliances that have at least one taxed corporation."""
    corp_ids = MonthlyTax.objects.values_list("corp_id", flat=True).distinct()
    alliance_ids = get_config().alliance_ids()

    alliances = {}
    for info in _corporation_infos(corp_ids).values():
        alliance = info.alliance
        if alliance and alliance.alliance_id in alliance_ids:
            alliances[alliance.alliance_id] = alliance.alliance_name

    return [
        {"alliance_id": alliance_id, "alliance_name": name}
        for alliance_id, name in sorted(alliances.items(), key=lambda item: item[1].lower())
    ]


def get_statistics_series(year: int, alliance_id: int = None):
    """Monthly tax and gross PvE income per corporation for one year."""
    config = get_config()
    alliance_ids = config.alliance_ids()
    rows = MonthlyTax.objects.filter(year=year).exclude(
        corp_id__in=config.blacklisted_corporation_ids()
    )
    infos = _corporation_infos({row.corp_id for row in rows})
    slots = _colour_slots()
    # sized for every corporation with data, not the filtered few, for the
    # same reason the slots are
    palette = _chart_palette(_colour_count(len(slots)))

    corps = {}
    for row in rows:
        info = infos.get(row.corp_id)
        alliance = info.alliance if info else None

        if not alliance or alliance.alliance_id not in alliance_ids:
            continue
        if alliance_id and alliance.alliance_id != alliance_id:
            continue
        if not 1 <= row.month <= 12:
            continue

        corp = corps.setdefault(row.corp_id, {
            "corp_id": row.corp_id,
            "name": row.corp_name or info.corporation_name,
            "alliance_name": alliance.alliance_name,
            # Alliance Auth keeps this from ESI, the same source Dotlan reads
            "members": info.member_count or 0,
            "tax": [0.0] * 12,
            "income": [0.0] * 12,
        })
        # the figure the overview shows for this month, so the chart and the
        # page cannot disagree about what a corporation owed
        corp["tax"][row.month - 1] += row.amount_to_pay
        corp["income"][row.month - 1] += get_pve_income(row.tax_value, row.tax_percentage)

    series = sorted(corps.values(), key=lambda corp: corp["name"].lower())
    for corp in series:
        slot = slots.get(corp["corp_id"], 0)
        # the palette is built for every corporation that has data, so a
        # corporation keeps its colour when the filter changes and when the
        # display switches between the line chart and the pie
        #
        # A palette of one colour per corporation used to make the dash index
        # below always 0, so the line styles the README promises past eight
        # corporations never appeared.
        corp["color"] = palette[slot % len(palette)]
        corp["dash"] = CHART_DASHES[(slot // len(palette)) % len(CHART_DASHES)]
        corp["tax_total"] = round(sum(corp["tax"]))
        corp["income_total"] = round(sum(corp["income"]))
        corp["tax"] = [round(value) for value in corp["tax"]]
        corp["income"] = [round(value) for value in corp["income"]]

    return series
