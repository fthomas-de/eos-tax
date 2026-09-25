"""The write path: update_corp turns a wallet journal into a number, and
corp_has_payed decides whether that number was settled.

update_corp is the only place in the app that produces the figures everything
else only displays or sums - it had no coverage before this file.
"""

import datetime
from decimal import Decimal
from importlib import import_module

from allianceauth.eveonline.models import EveCorporationInfo
from django.apps import apps as installed_apps
from corptools.models import (
    CorporationAudit,
    CorporationWalletDivision,
    CorporationWalletJournalEntry,
)
from dateutil.relativedelta import relativedelta

from eos_tax.db.payments import (
    get_open_payment_count,
    get_website_data,
    is_payable,
    set_corp_tax,
    update_corp,
)
from eos_tax.models import MonthlyTax, TaxConfiguration, TaxRate
from eos_tax.tests.base import EosTaxTestCase
from eos_tax.util import corp_has_payed, get_amount_to_pay

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    OUTSIDER_CORP_ID,
    create_alliance,
    create_corporation,
    create_tax_row,
)

ALLIANCE_ID = 99000001
CORP_ID = 98000001
OTHER_CORP_ID = 98000002
HOLDING_CORP_ID = 98000003
UNKNOWN_CORP_ID = 98099999
RATTER_ID = 2100000001

YEAR = 2026
MONTH = 6

# A payment's amount is only ever "no second party" in these tests when a
# case needs it explicitly - None doubles as "leave it unset" everywhere else.
_UNSET = object()


class PaymentsTestCase(EosTaxTestCase):
    """Shared fixture: one taxed corporation with a wallet division to fill."""

    def setUp(self):
        alliance = create_alliance(ALLIANCE_ID, "Taxed Alliance")
        self.corporation = create_corporation(CORP_ID, "Bravo Corp", alliance)
        audit = CorporationAudit.objects.create(corporation=self.corporation)
        self.division = CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

        self.config = TaxConfiguration.get_solo()
        self.config.tax_types = ["bounty_prizes"]
        self.config.save()
        self.config.tax_alliances.set([alliance])

        self.entry_id = 0

    def entry(self, amount, date, ref_type="bounty_prizes", tax_receiver_id=None,
              reason=None):
        """One wallet journal row, dated and typed by the caller."""
        self.entry_id += 1
        return CorporationWalletJournalEntry.objects.create(
            division=self.division,
            date=date,
            description="wallet entry",
            entry_id=self.entry_id,
            ref_type=ref_type,
            first_party_id=1000125,
            second_party_id=RATTER_ID,
            tax_receiver_id=CORP_ID if tax_receiver_id is None else tax_receiver_id,
            context_id=30000001,
            context_id_type="system_id",
            reason=reason,
            amount=amount,
            tax=amount,
        )

    def bounty(self, amount, day, month=MONTH, year=YEAR, hour=12, **kwargs):
        return self.entry(
            amount,
            datetime.datetime(year, month, day, hour, tzinfo=datetime.timezone.utc),
            **kwargs,
        )

    def row(self):
        return MonthlyTax.objects.get(corp_id=CORP_ID, month=MONTH, year=YEAR)


class TestUpdateCorpUnknownCorporation(PaymentsTestCase):
    def test_should_ignore_an_unknown_corporation(self):
        update_corp(UNKNOWN_CORP_ID, MONTH, YEAR)

        self.assertFalse(MonthlyTax.objects.filter(corp_id=UNKNOWN_CORP_ID).exists())


class TestUpdateCorpWithoutARate(PaymentsTestCase):
    def test_should_skip_a_corporation_without_an_ingame_rate(self):
        """Alliance Auth leaves tax_rate empty for a corporation it never
        pulled from ESI - a holding imported by hand is the usual one. The
        task runs one subtask per corporation, so formatting None would take
        that subtask down without anything showing on the page."""
        corporation = EveCorporationInfo.objects.get(corporation_id=CORP_ID)
        corporation.tax_rate = None
        corporation.save()
        self.bounty(1_000_000_000, day=15)

        update_corp(CORP_ID, MONTH, YEAR)

        self.assertFalse(
            MonthlyTax.objects.filter(corp_id=CORP_ID, month=MONTH, year=YEAR).exists()
        )


class TestUpdateCorpNoEntries(PaymentsTestCase):
    def test_should_not_create_a_row_without_journal_entries(self):
        """A month with no income must stay absent, not show up as a zero."""
        update_corp(CORP_ID, MONTH, YEAR)

        self.assertFalse(
            MonthlyTax.objects.filter(corp_id=CORP_ID, month=MONTH, year=YEAR).exists()
        )


class TestUpdateCorpCalculation(PaymentsTestCase):
    def test_should_calculate_the_row_fields(self):
        self.bounty(500_000_000, day=10)
        self.bounty(300_000_000, day=20)
        self.config.tax_rate = Decimal("0.15")
        self.config.save()

        update_corp(CORP_ID, MONTH, YEAR)

        row = self.row()
        self.assertEqual(row.tax_value, 800_000_000)
        self.assertEqual(row.tax_percentage, 10.0)  # corp tax_rate 0.1 -> 10.0
        self.assertEqual(row.alliance_tax_rate, 0.15)
        self.assertEqual(row.corp_name, "Bravo Corp")
        # 800M skimmed at 10% is 8,000M earned; 15% of that is owed. The one
        # figure the reader copies to pay - a default of 0 here once went
        # unnoticed by every test, because they all built their rows by hand
        self.assertEqual(row.amount_to_pay, 1_200_000_000)

    def test_should_only_count_configured_ref_types(self):
        self.bounty(500_000_000, day=10)
        self.bounty(999_999_999, day=11, ref_type="market_transaction")

        update_corp(CORP_ID, MONTH, YEAR)

        self.assertEqual(self.row().tax_value, 500_000_000)

    def test_should_only_count_entries_for_this_corporation(self):
        self.bounty(500_000_000, day=10)
        self.bounty(999_999_999, day=11, tax_receiver_id=OTHER_CORP_ID)

        update_corp(CORP_ID, MONTH, YEAR)

        self.assertEqual(self.row().tax_value, 500_000_000)


class TestUpdateCorpMonthBoundaries(PaymentsTestCase):
    def test_should_respect_the_month_boundaries(self):
        """_month_range is half open: [start, end)."""
        # last second of the previous month - must not count
        self.entry(
            200_000_000,
            datetime.datetime(YEAR, MONTH - 1, 31, 23, 59, 59, tzinfo=datetime.timezone.utc),
        )
        # the very first moment of the month - must count
        self.entry(
            100_000_000,
            datetime.datetime(YEAR, MONTH, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
        )
        # the first second of the following month - must not count
        self.entry(
            300_000_000,
            datetime.datetime(YEAR, MONTH + 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
        )

        update_corp(CORP_ID, MONTH, YEAR)

        self.assertEqual(self.row().tax_value, 100_000_000)


class TestUpdateCorpRepeatedRuns(PaymentsTestCase):
    def test_should_update_the_existing_row_on_a_second_run(self):
        self.bounty(100_000_000, day=10)
        update_corp(CORP_ID, MONTH, YEAR)
        self.assertEqual(self.row().tax_value, 100_000_000)

        self.bounty(150_000_000, day=11)
        update_corp(CORP_ID, MONTH, YEAR)

        self.assertEqual(
            MonthlyTax.objects.filter(corp_id=CORP_ID, month=MONTH, year=YEAR).count(),
            1,
        )
        self.assertEqual(self.row().tax_value, 250_000_000)

    def test_should_move_the_amount_with_the_income_on_a_second_run(self):
        """The update branch writes the row it found rather than creating one,
        which is the path a forgotten field silently keeps stale on."""
        self.bounty(100_000_000, day=10)
        update_corp(CORP_ID, MONTH, YEAR)
        first = self.row().amount_to_pay

        self.bounty(150_000_000, day=11)
        update_corp(CORP_ID, MONTH, YEAR)
        row = self.row()

        self.assertEqual(
            row.amount_to_pay,
            int(get_amount_to_pay(250_000_000, 10.0, row.alliance_tax_rate)),
        )
        self.assertGreater(row.amount_to_pay, first)

    def test_should_keep_a_payed_row_marked_payed(self):
        create_tax_row(
            CORP_ID, "Bravo Corp", payed=True, tax_value=1, tax_percentage=10.0,
            month=MONTH, year=YEAR, alliance_tax_rate=0.15,
        )
        self.bounty(700_000_000, day=10)

        update_corp(CORP_ID, MONTH, YEAR)

        row = self.row()
        self.assertTrue(row.payed)
        self.assertEqual(row.tax_value, 700_000_000)


class TestUpdateCorpRounding(PaymentsTestCase):
    def test_should_round_the_amount_rather_than_cut_it_off(self):
        """0.07 * 100 is 7.000000000000001 in floating point, and cutting
        the result off made 7M ISK at 7 % corp tax and 10 % alliance tax
        come out as 9,999,999 instead of 10,000,000."""
        corporation = EveCorporationInfo.objects.get(corporation_id=CORP_ID)
        corporation.tax_rate = 0.07
        corporation.save()
        self.config.tax_rate = Decimal("0.1")
        self.config.save()
        self.bounty(7_000_000, day=10)

        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        self.assertEqual(self.row().amount_to_pay, 10_000_000)
        self.assertEqual(breakdown["gross_income"], 100_000_000)
        # and the log shows the rate as it was set, without the float noise
        self.assertEqual(breakdown["corp_tax_percent"], 7.0)


class TestUpdateCorpWithoutAllianceTax(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.config.tax_rate = Decimal("0")
        self.config.save()
        self.bounty(500_000_000, day=10)

    def test_should_not_write_a_row_for_a_month_that_owes_nothing(self):
        """A 0 ISK row can never be matched by a payment, so it sat in the
        menu badge as outstanding for good."""
        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        self.assertFalse(
            MonthlyTax.objects.filter(corp_id=CORP_ID, month=MONTH, year=YEAR).exists()
        )
        self.assertEqual(breakdown["reason"], "no_alliance_rate")

    def test_should_leave_an_existing_row_alone(self):
        """It may carry a payment already; deleting it would lose that."""
        create_tax_row(
            CORP_ID, "Bravo Corp", payed=True, tax_value=1, tax_percentage=10.0,
            month=MONTH, year=YEAR, alliance_tax_rate=0.15,
        )

        update_corp(CORP_ID, MONTH, YEAR)

        row = self.row()
        self.assertTrue(row.payed)
        self.assertEqual(row.tax_value, 1)


class TestPaidIsNeverTakenBack(PaymentsTestCase):
    """Once a row is paid it stays paid, whatever a later run finds."""

    def test_should_keep_paid_when_the_caller_says_otherwise(self):
        """set_corp_tax is the one writer of the flag; asked to write
        False over a paid row - a recalculation after a rate correction
        finds no payment of the new amount - it keeps the payment."""
        create_tax_row(
            CORP_ID, "Bravo Corp", payed=True, tax_value=1, tax_percentage=10.0,
            month=MONTH, year=YEAR, alliance_tax_rate=0.15,
        )

        set_corp_tax(
            corp_id=CORP_ID, corp_name="Bravo Corp", tax_value=5_000_000,
            tax_percentage=10.0, month=MONTH, year=YEAR, payed=False,
            alliance_tax_rate=0.2,
        )

        self.assertTrue(self.row().payed)


class TestUpdateCorpYearRollover(PaymentsTestCase):
    def test_should_roll_december_into_january(self):
        self.entry(
            100_000_000,
            datetime.datetime(YEAR, 12, 31, 12, tzinfo=datetime.timezone.utc),
        )
        self.entry(
            300_000_000,
            datetime.datetime(YEAR + 1, 1, 1, 0, tzinfo=datetime.timezone.utc),
        )

        update_corp(CORP_ID, 12, YEAR)

        row = MonthlyTax.objects.get(corp_id=CORP_ID, month=12, year=YEAR)
        self.assertEqual(row.tax_value, 100_000_000)


class TestUpdateCorpBreakdown(PaymentsTestCase):
    """update_corp's return value: the settings page's recalculate button
    renders this as a log, so every step it claims to show has to be here."""

    def test_should_return_the_calculation_steps(self):
        self.bounty(500_000_000, day=10)
        self.bounty(300_000_000, day=20)
        self.config.tax_rate = Decimal("0.15")
        self.config.save()

        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        self.assertTrue(breakdown["ok"])
        self.assertEqual(breakdown["corp_id"], CORP_ID)
        self.assertEqual(breakdown["corp_name"], "Bravo Corp")
        self.assertEqual(breakdown["tax_types"], ["bounty_prizes"])
        self.assertEqual(breakdown["tax_value"], 800_000_000)
        self.assertEqual(breakdown["entries_considered"], 2)
        self.assertEqual(breakdown["corp_tax_percent"], 10.0)
        # 800M skimmed at 10% is 8,000M earned
        self.assertEqual(breakdown["gross_income"], 8_000_000_000)
        self.assertEqual(breakdown["alliance_tax_rate"], 0.15)
        self.assertEqual(breakdown["alliance_tax_percent"], 15.0)
        self.assertEqual(breakdown["amount_to_pay"], self.row().amount_to_pay)
        self.assertFalse(breakdown["payed"])

    def test_should_break_the_sum_down_by_tax_type(self):
        self.config.tax_types = ["bounty_prizes", "ess_escrow_transfer"]
        self.config.save()
        self.bounty(500_000_000, day=10, ref_type="bounty_prizes")
        self.bounty(200_000_000, day=11, ref_type="ess_escrow_transfer")

        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        by_type = {row["ref_type"]: row["sum"] for row in breakdown["by_type"]}
        self.assertEqual(by_type["bounty_prizes"], 500_000_000)
        self.assertEqual(by_type["ess_escrow_transfer"], 200_000_000)
        self.assertEqual(breakdown["tax_value"], 700_000_000)

    def test_should_explain_an_unknown_corporation(self):
        breakdown = update_corp(UNKNOWN_CORP_ID, MONTH, YEAR)

        self.assertFalse(breakdown["ok"])
        self.assertEqual(breakdown["reason"], "unknown_corp")

    def test_should_explain_a_missing_ingame_rate(self):
        corporation = EveCorporationInfo.objects.get(corporation_id=CORP_ID)
        corporation.tax_rate = None
        corporation.save()

        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        self.assertFalse(breakdown["ok"])
        self.assertEqual(breakdown["reason"], "no_tax_rate")

    def test_should_explain_a_month_without_entries(self):
        breakdown = update_corp(CORP_ID, MONTH, YEAR)

        self.assertFalse(breakdown["ok"])
        self.assertEqual(breakdown["reason"], "no_entries")


# --- corp_has_payed -----------------------------------------------------

ALLIANCE_RATE = 0.15
TAX_VALUE = 1_000_000_000
TAX_PERCENTAGE = 10.0
# the amount owed for TAX_VALUE/TAX_PERCENTAGE/ALLIANCE_RATE, worked out the
# same way corp_has_payed itself works it out
OWED = int(get_amount_to_pay(TAX_VALUE, TAX_PERCENTAGE, ALLIANCE_RATE))


class CorpHasPayedTestCase(PaymentsTestCase):
    """Shared fixture: a calculated row and a corporation to pay it to."""

    def setUp(self):
        super().setUp()
        self.holding = create_corporation(HOLDING_CORP_ID, "Holding Corp", None)

    def owe(self, payed=False, alliance_tax_rate=ALLIANCE_RATE):
        return create_tax_row(
            CORP_ID, "Bravo Corp", payed=payed,
            tax_value=TAX_VALUE, tax_percentage=TAX_PERCENTAGE,
            month=MONTH, year=YEAR, alliance_tax_rate=alliance_tax_rate,
        )

    def configure_holding(self):
        self.config.tax_corporation = self.holding
        self.config.save()

    def pay(self, amount, when=None, ref_type="player_donation", reason=None,
            second_party_id=_UNSET):
        self.entry_id += 1
        return CorporationWalletJournalEntry.objects.create(
            division=self.division,
            date=when or datetime.datetime(YEAR, MONTH, 2, tzinfo=datetime.timezone.utc),
            description="tax payment",
            entry_id=self.entry_id,
            ref_type=ref_type,
            first_party_id=RATTER_ID,
            second_party_id=(
                self.holding.corporation_id if second_party_id is _UNSET else second_party_id
            ),
            tax_receiver_id=None,
            context_id=None,
            context_id_type=None,
            reason=reason,
            amount=amount,
            tax=None,
        )

    def has_payed(self):
        return corp_has_payed(CORP_ID, MONTH, YEAR)


class TestCorpHasPayedWithoutARow(CorpHasPayedTestCase):
    def test_should_report_unpayed_without_a_row(self):
        self.assertFalse(self.has_payed())


class TestCorpHasPayedAlreadyMarked(CorpHasPayedTestCase):
    def test_should_trust_a_row_already_marked_payed(self):
        """No holding corporation is configured and the journal is empty -
        checking either would have to answer False on its own."""
        self.owe(payed=True)

        self.assertTrue(self.has_payed())


class TestCorpHasPayedHoldingCorporation(CorpHasPayedTestCase):
    def test_should_report_unpayed_without_a_holding_corporation(self):
        """A stray entry with no second party at all must not read as a
        match once nothing is configured to compare it against."""
        self.owe()
        self.pay(OWED, second_party_id=None)

        self.assertFalse(self.has_payed())


class TestCorpHasPayedAmountMatching(CorpHasPayedTestCase):
    def test_should_accept_a_payment_of_exactly_the_owed_amount(self):
        self.owe()
        self.configure_holding()
        self.pay(OWED)

        self.assertTrue(self.has_payed())

    def test_should_accept_a_negative_payment_too(self):
        self.owe()
        self.configure_holding()
        self.pay(-OWED)

        self.assertTrue(self.has_payed())

    def test_should_ignore_a_payment_before_the_month_started(self):
        self.owe()
        self.configure_holding()
        self.pay(
            OWED,
            when=datetime.datetime(YEAR, MONTH - 1, 31, 23, 59, 59, tzinfo=datetime.timezone.utc),
        )

        self.assertFalse(self.has_payed())

    def test_should_require_the_exact_amount_when_reason_is_not_used(self):
        self.owe()
        self.configure_holding()
        self.pay(OWED + 1)

        self.assertFalse(self.has_payed())


class TestCorpHasPayedReasonMatching(CorpHasPayedTestCase):
    def setUp(self):
        super().setUp()
        self.owe()
        self.configure_holding()
        self.config.use_reason = True
        self.config.save()

    def test_should_accept_a_larger_payment_when_using_reason(self):
        self.pay(OWED + 1, reason=f"{CORP_ID}/{MONTH}/{YEAR}")

        self.assertTrue(self.has_payed())

    def test_should_reject_a_wrong_reason(self):
        self.pay(OWED, reason="99999999/1/2000")

        self.assertFalse(self.has_payed())

    def test_should_reject_a_missing_reason(self):
        self.pay(OWED, reason=None)

        self.assertFalse(self.has_payed())


class TestCorpHasPayedRefType(CorpHasPayedTestCase):
    def test_should_ignore_a_payment_of_the_wrong_ref_type(self):
        self.owe()
        self.configure_holding()
        self.pay(OWED, ref_type="bounty_prizes")

        self.assertFalse(self.has_payed())


class TestCorpHasPayedStoredRate(CorpHasPayedTestCase):
    def test_should_use_the_rate_stored_on_the_row_not_todays_rate(self):
        """The field's own help text promises this: the rate in effect when
        the row was calculated, so a later change does not rewrite the past."""
        self.config.tax_rate = Decimal(str(ALLIANCE_RATE))
        self.config.save()
        self.owe()
        self.configure_holding()
        self.pay(OWED)

        self.assertTrue(self.has_payed())

        self.config.tax_rate = Decimal("0.9")
        self.config.save()

        self.assertTrue(self.has_payed())


# The two below moved here from test_views.py: neither renders a page.
# is_payable is a calendar rule and get_open_payment_count is a query, and
# both belong to the same code as the rest of this file.

class TestPayable(EosTaxTestCase):
    """When a month may be transferred.

    One function for the overview and the badge: two places disagreeing about
    what is due would be worse than no badge.
    """

    def test_should_refuse_the_running_month(self):
        self.assertFalse(is_payable(9, 2026, datetime.datetime(2026, 9, 20)))

    def test_should_wait_for_the_second_of_the_month(self):
        """The last journal entries of a closed month arrive on the first."""
        self.assertFalse(is_payable(8, 2026, datetime.datetime(2026, 9, 1)))
        self.assertTrue(is_payable(8, 2026, datetime.datetime(2026, 9, 2)))

    def test_should_carry_across_the_turn_of_the_year(self):
        self.assertTrue(is_payable(12, 2026, datetime.datetime(2027, 1, 5)))

    def test_should_refuse_a_month_in_the_future(self):
        self.assertFalse(is_payable(11, 2026, datetime.datetime(2026, 9, 20)))


class TestOpenPaymentCount(EosTaxTestCase):
    """What the number on the menu entry counts."""

    def setUp(self):
        previous = datetime.datetime.now() - relativedelta(months=1)
        self.period = (previous.month, previous.year)

        config = TaxConfiguration.get_solo()
        config.last_month = True
        config.current_month = True
        config.save()

    def row(self, corp_id, name, payed=False, period=None):
        month, year = period or self.period
        row = create_tax_row(corp_id, name, payed=payed)
        row.month = month
        row.year = year
        row.save()

        return row

    def count(self, **kwargs):
        return get_open_payment_count([self.period], **kwargs)

    def test_should_count_an_unpaid_row(self):
        self.row(ALPHA_CORP_ID, "Alpha Corp")

        self.assertEqual(self.count(admin=True), 1)

    def test_should_ignore_a_paid_row(self):
        self.row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        self.assertEqual(self.count(admin=True), 0)

    def test_should_ignore_the_running_month(self):
        """It has no reason code yet, so there is nothing to quote on a transfer."""
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=False)
        now = datetime.datetime.now()

        self.assertEqual(
            get_open_payment_count([(now.month, now.year)], admin=True), 0
        )

    def test_should_ignore_an_excluded_corporation(self):
        row = self.row(ALPHA_CORP_ID, "Alpha Corp")
        alliance = create_alliance(99000009, "Any Alliance")
        corporation = create_corporation(row.corp_id, "Alpha Corp", alliance)
        TaxConfiguration.get_solo().corporation_blacklist.set([corporation])

        self.assertEqual(self.count(admin=True), 0)

    def test_should_show_a_member_only_their_own_corporations(self):
        self.row(ALPHA_CORP_ID, "Alpha Corp")
        self.row(BRAVO_CORP_ID, "Bravo Corp")

        self.assertEqual(self.count(admin=False, corps=[BRAVO_CORP_ID]), 1)
        self.assertEqual(self.count(admin=True), 2)

    def test_should_stay_at_zero_without_any_corporation(self):
        self.row(ALPHA_CORP_ID, "Alpha Corp")

        self.assertEqual(self.count(admin=False, corps=[]), 0)


class TestWebsiteDataOrder(EosTaxTestCase):
    """get_website_data's own sort - overview.js's DataTables order is
    required to mirror it, since the client can re-sort the page after load.
    """

    def test_should_group_payable_unpaid_then_payable_paid_then_next_month(self):
        """The payable month's unpaid rows first (they carry a reason code),
        then its paid rows, then the not yet payable follow-up month -
        corporation name ascending breaks every tie, so a group never
        reorders itself by date."""
        now = datetime.datetime.now()
        previous = now - relativedelta(months=1)

        # payable month: two unpaid rows, out of alphabetical order here
        create_tax_row(
            OUTSIDER_CORP_ID, "Outsider Corp", payed=False,
            month=previous.month, year=previous.year,
        )
        create_tax_row(
            BRAVO_CORP_ID, "Bravo Corp", payed=False,
            month=previous.month, year=previous.year,
        )
        # payable month: a paid row, which belongs after every unpaid one
        create_tax_row(
            ALPHA_CORP_ID, "Alpha Corp", payed=True,
            month=previous.month, year=previous.year,
        )
        # the running month: not yet payable, so always without a reason -
        # also out of alphabetical order here
        create_tax_row(
            BRAVO_CORP_ID, "Bravo Corp", payed=False,
            month=now.month, year=now.year,
        )
        create_tax_row(
            ALPHA_CORP_ID, "Alpha Corp", payed=False,
            month=now.month, year=now.year,
        )

        dates = [(previous.month, previous.year), (now.month, now.year)]
        data = get_website_data(dates=dates, admin=True, corps=[])

        self.assertEqual(
            [
                (row["corporation_name"], row["month"], row["year"], row["payed"])
                for row in data
            ],
            [
                ("Bravo Corp", previous.month, previous.year, False),
                ("Outsider Corp", previous.month, previous.year, False),
                ("Alpha Corp", previous.month, previous.year, True),
                ("Alpha Corp", now.month, now.year, False),
                ("Bravo Corp", now.month, now.year, False),
            ],
        )


# the migration module name starts with a digit, so it cannot be imported
# with a plain import statement
backfill_amount_to_pay = import_module(
    "eos_tax.migrations.0019_monthlytax_amount_to_pay"
).backfill_amount_to_pay


class TestAmountToPayBackfill(EosTaxTestCase):
    """Migration 0019 working out amount_to_pay for rows written before it.

    Called with the installed app registry instead of a historical one: the
    three models it reads have not changed since, and the rows it has to get
    right are the ones the running app can still produce.
    """

    def setUp(self):
        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.2")
        config.save()

    def old_row(self, corp_id, month, year, alliance_tax_rate):
        """A row as the app left it before 0019: the field at its default."""
        return MonthlyTax.objects.create(
            corp_id=corp_id, corp_name="Old Corp", tax_value=1_000_000_000,
            tax_percentage=10.0, month=month, year=year, payed=False,
            alliance_tax_rate=alliance_tax_rate, amount_to_pay=0,
        )

    def backfill(self):
        backfill_amount_to_pay(installed_apps, None)

    def test_should_work_it_out_from_the_rate_on_the_row(self):
        row = self.old_row(CORP_ID, 3, 2026, alliance_tax_rate=0.1)

        self.backfill()
        row.refresh_from_db()

        # 1,000M skimmed at 10% is 10,000M earned; 10% of that
        self.assertEqual(row.amount_to_pay, 1_000_000_000)

    def test_should_fall_back_to_the_schedule_for_a_row_without_a_rate(self):
        """What the overview used to do at read time for such a row - the
        amount has to come out the same, or 0019 changes what is owed."""
        TaxRate.objects.create(valid_from=datetime.date(2026, 1, 1), rate=Decimal("0.05"))
        row = self.old_row(CORP_ID, 3, 2026, alliance_tax_rate=0)

        self.backfill()
        row.refresh_from_db()

        self.assertEqual(row.amount_to_pay, 500_000_000)

    def test_should_fall_back_to_the_base_rate_before_the_schedule_starts(self):
        TaxRate.objects.create(valid_from=datetime.date(2026, 6, 1), rate=Decimal("0.05"))
        row = self.old_row(CORP_ID, 3, 2026, alliance_tax_rate=0)

        self.backfill()
        row.refresh_from_db()

        self.assertEqual(row.amount_to_pay, 2_000_000_000)

    def test_should_not_crash_on_a_row_without_a_month(self):
        """month and year default to 0, and date() refuses both. On MariaDB a
        crash here leaves the column added and the migration unrecorded, so
        the next migrate fails on the duplicate column."""
        row = self.old_row(CORP_ID, 0, 0, alliance_tax_rate=0)

        self.backfill()
        row.refresh_from_db()

        self.assertEqual(row.amount_to_pay, 2_000_000_000)
