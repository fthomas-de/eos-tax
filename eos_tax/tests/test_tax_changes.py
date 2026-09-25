"""Detecting a corporation that moved its ingame tax rate.

The rate is not in the corporation journal - `tax` equals `amount` on every
bounty row. It is recovered from `reason`, which lists the NPCs killed, against
what the SDE says they pay.

The SDE lookup itself is a single query and is stood in for here; what these
cover is the part that belongs to this app: grouping fleet payouts back
together, smoothing a day of noise away, and deciding what counts as a step.
"""

import datetime
from decimal import Decimal
from unittest import mock

from allianceauth.eveonline.models import EveCorporationInfo
from corptools.models import (
    CorporationAudit,
    CorporationWalletDivision,
    CorporationWalletJournalEntry,
)
from django.urls import reverse

from eos_tax.db.tax_changes import get_corp_tax_changes, get_corp_tax_detail
from eos_tax.models import TaxConfiguration
from eos_tax.tests.base import EosTaxTestCase, read_static

from .factories import create_alliance, create_corporation, create_user

ALLIANCE_ID = 99000001
CORP_ID = 98000001
RATTER_ID = 2100000001
YEAR = 2026

# one NPC worth a round million, so a rate is easy to read off the numbers
NPC_TYPE_ID = 12345
NPC_BOUNTY = 1_000_000.0

BOUNTIES = {NPC_TYPE_ID: NPC_BOUNTY}


class TaxChangeTestCase(EosTaxTestCase):
    """Shared fixture: one taxed corporation and a journal to fill."""

    @classmethod
    def _build_fixture(cls):
        cls.alliance = create_alliance(ALLIANCE_ID, "Taxed Alliance")
        corporation = create_corporation(CORP_ID, "Bravo Corp", cls.alliance)
        audit = CorporationAudit.objects.create(corporation=corporation)
        cls.division = CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

    @classmethod
    def _build_config(cls):
        config = TaxConfiguration.get_solo()
        config.tax_types = ["bounty_prizes"]
        config.save()
        config.tax_alliances.set([cls.alliance])

    @classmethod
    def setUpTestData(cls):
        cls._build_fixture()
        cls._build_config()

    def setUp(self):
        self.entry_id = 0

    def payout(self, day, rate, system=30000001, kills=10, shared_by=1, minute=0,
               reason=None):
        """One payout of `kills` NPCs, taxed at `rate`, split between a fleet."""
        full = NPC_BOUNTY * kills
        share = full * rate / shared_by

        for member in range(shared_by):
            self.entry_id += 1
            CorporationWalletJournalEntry.objects.create(
                division=self.division,
                date=datetime.datetime(
                    YEAR, 6, day, 12, minute, member,
                    tzinfo=datetime.timezone.utc,
                ),
                description="got bounty prizes for killing pirates",
                entry_id=self.entry_id,
                ref_type="bounty_prizes",
                first_party_id=1000125,
                second_party_id=RATTER_ID + member,
                tax_receiver_id=CORP_ID,
                context_id=system,
                context_id_type="system_id",
                reason=reason or f"{NPC_TYPE_ID}: {kills}",
                amount=share,
                tax=share,
            )

    def steady(self, days, rate, **kwargs):
        """Enough payouts a day, over enough days, to count as a plateau.

        Three a day is RATE_MIN_PAYOUTS_PER_DAY exactly, which is the point: a
        fixture sitting well above a threshold stops saying where the
        threshold is, and every one of these is a journal insert.
        """
        for day in days:
            for minute in range(3):
                self.payout(day, rate, minute=minute * 5, **kwargs)

    def as_admin(self, url, **params):
        self.client.force_login(
            create_user("taxadmin", 97000010, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES):
            return self.client.get(url, params)

    def changes(self, tolerance=None):
        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES):
            if tolerance is None:
                return get_corp_tax_changes(YEAR)["rows"]

            return get_corp_tax_changes(YEAR, tolerance)["rows"]

    def detail(self):
        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES):
            return get_corp_tax_detail(CORP_ID, YEAR)


class TestRateRecovery(TaxChangeTestCase):
    def test_should_read_the_rate_off_a_payout(self):
        self.steady(range(1, 5), 0.10)

        days = self.detail()["days"]

        self.assertTrue(days)
        for day in days:
            self.assertAlmostEqual(day["rate"], 0.10, places=6)

    def test_should_sum_a_fleet_payout_back_together(self):
        """Six members each get a sixth; splitting them would report a sixth
        of the rate."""
        self.steady(range(1, 5), 0.10, shared_by=6)

        for day in self.detail()["days"]:
            self.assertAlmostEqual(day["rate"], 0.10, places=6)

    def test_should_skip_a_day_with_too_few_payouts(self):
        self.payout(1, 0.10)
        self.payout(2, 0.10)

        self.assertEqual(self.detail()["days"], [])

    def test_should_report_nothing_without_the_sde(self):
        self.steady(range(1, 5), 0.10)

        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value={}):
            self.assertEqual(get_corp_tax_changes(YEAR)["rows"], [])


class TestStepDetection(TaxChangeTestCase):
    """Two tests here override tax_change_min_points, so the configuration
    is rebuilt fresh every test instead of being shared via setUpTestData."""

    @classmethod
    def setUpTestData(cls):
        cls._build_fixture()

    def setUp(self):
        super().setUp()
        self._build_config()

    def test_should_stay_quiet_on_a_steady_rate(self):
        self.steady(range(1, 11), 0.10)

        self.assertEqual(self.changes(), [])

    def test_should_find_a_rate_that_dropped(self):
        self.steady(range(1, 6), 0.10)
        self.steady(range(6, 11), 0.02)

        rows = self.changes()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["corp_name"], "Bravo Corp")
        self.assertAlmostEqual(rows[0]["step"]["from_rate"], 0.10, places=3)
        self.assertAlmostEqual(rows[0]["step"]["to_rate"], 0.02, places=3)
        self.assertLess(rows[0]["step"]["change"], 0)

    def test_should_find_a_rate_that_rose(self):
        self.steady(range(1, 6), 0.02)
        self.steady(range(6, 11), 0.10)

        self.assertGreater(self.changes()[0]["step"]["change"], 0)

    def test_should_smooth_an_outlier_on_the_first_day(self):
        """A centred window has only two entries at the edge, and the median of
        two is their mean - the outlier used to survive at half strength."""
        self.steady([1], 0.05)
        self.steady(range(2, 12), 0.10)

        self.assertEqual(self.changes(), [])

    def test_should_ignore_a_single_day_of_noise(self):
        """A fleet payout landing either side of a minute halves that day."""
        self.steady(range(1, 6), 0.10)
        self.steady([6], 0.05)
        self.steady(range(7, 12), 0.10)

        self.assertEqual(self.changes(), [])

    def test_should_weigh_nine_to_ten_as_one_point(self):
        """Not the eleven percent it makes of the old value."""
        self.steady(range(1, 6), 0.09)
        self.steady(range(6, 11), 0.10)

        self.assertAlmostEqual(
            self.changes()[0]["step"]["change_points"], 1.0, places=6
        )

    def test_should_weigh_a_move_the_same_at_any_level(self):
        """Half a point is half a point, at two percent or at ten - which is
        what points buy and relative percent does not."""
        self.steady(range(1, 6), 0.1000)
        self.steady(range(6, 11), 0.1050)

        moved = self.changes()[0]["step"]["change_points"]

        self.assertAlmostEqual(moved, 0.50, places=6)

    def test_should_find_a_move_that_reaches_the_minimum(self):
        self.steady(range(1, 6), 0.1000)
        self.steady(range(6, 11), 0.1050)

        self.assertEqual(len(self.changes()), 1)

    def test_should_ignore_a_move_below_the_minimum(self):
        """Two tenths of a point does not change the bill enough to care."""
        self.steady(range(1, 6), 0.1000)
        self.steady(range(6, 11), 0.1020)

        self.assertEqual(self.changes(), [])

    def test_should_take_the_minimum_from_the_settings(self):
        """The number lives on the settings page, not in the code."""
        config = TaxConfiguration.get_solo()
        config.tax_change_min_points = Decimal("0.10")
        config.save()

        self.steady(range(1, 6), 0.1000)
        self.steady(range(6, 11), 0.1020)

        self.assertEqual(len(self.changes()), 1)

    def test_should_fall_back_when_the_setting_is_empty(self):
        """An unset value must not mean a threshold of zero."""
        config = TaxConfiguration.get_solo()
        config.tax_change_min_points = 0
        config.save()

        self.steady(range(1, 6), 0.1000)
        self.steady(range(6, 11), 0.1020)

        self.assertEqual(self.changes(), [])

    def test_should_need_a_level_to_hold_for_two_days(self):
        """Without a threshold this is what keeps single days out of the list."""
        self.steady(range(1, 6), 0.1000)
        self.steady([6], 0.1005)
        self.steady(range(7, 12), 0.1000)

        self.assertEqual(self.changes(), [])

    def test_should_count_the_systems_behind_a_step(self):
        """A rate change moves every system at once, a bounty modifier one."""
        for day in range(1, 6):
            for index, system in enumerate((30000001, 30000002, 30000003)):
                self.payout(day, 0.10, system=system, minute=index * 5)
        for day in range(6, 11):
            for index, system in enumerate((30000001, 30000002, 30000003)):
                self.payout(day, 0.02, system=system, minute=index * 5)

        self.assertEqual(self.changes()[0]["step"]["systems"], 3)

    def test_should_name_the_day_it_happened(self):
        self.steady(range(1, 6), 0.10)
        self.steady(range(6, 11), 0.02)

        self.assertEqual(
            self.changes()[0]["step"]["on"], datetime.date(YEAR, 6, 6)
        )


class TestSeveralChanges(TaxChangeTestCase):
    """A Corporation that switched more than once shows up more than once.

    The detector always found every step; the list used to keep one row per
    Corporation and show only the largest of them.
    """

    def levels(self, *pairs):
        """Consecutive stretches of days, each at its own rate."""
        day = 1
        for rate, length in pairs:
            self.steady(range(day, day + length), rate)
            day += length

    def test_should_list_every_change_of_one_corporation(self):
        self.levels((0.10, 5), (0.08, 5), (0.06, 5), (0.04, 5))

        self.assertEqual(len(self.changes()), 3)

    def test_should_name_the_corporation_on_every_row(self):
        self.levels((0.10, 5), (0.02, 5), (0.06, 5))

        names = {row["corp_name"] for row in self.changes()}

        self.assertEqual(names, {"Bravo Corp"})

    def test_should_carry_how_often_that_corporation_switched(self):
        """One row still says whether it stands alone."""
        self.levels((0.10, 5), (0.02, 5), (0.06, 5))

        for row in self.changes():
            self.assertEqual(row["changes"], 2)

    def test_should_order_by_the_size_of_the_move(self):
        self.levels((0.10, 5), (0.09, 5), (0.02, 5))

        moves = [round(row["step"]["change_points"], 2) for row in self.changes()]

        self.assertEqual(moves, [-7.0, -1.0])

    def test_should_find_a_rate_that_came_back(self):
        """Down and up again is two changes, not none."""
        self.levels((0.10, 5), (0.02, 5), (0.10, 5))

        self.assertEqual(len(self.changes()), 2)

    def test_should_count_corporations_and_changes_apart(self):
        self.levels((0.10, 5), (0.02, 5), (0.06, 5))

        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES):
            stats = get_corp_tax_changes(YEAR)["stats"]

        self.assertEqual(stats["changes"], 2)
        self.assertEqual(stats["flagged"], 1)


class TestHalfPointRounding(TaxChangeTestCase):
    """Levels read in half points, so a zero reads as 0 and a full rate as 100.

    The measurement lands a hair beside the ingame rate - 0.02 rather than 0 -
    and nobody types 0.02 into a search box.
    """

    def levels(self, *pairs):
        day = 1
        for rate, length in pairs:
            self.steady(range(day, day + length), rate)
            day += length

    def shown(self):
        change = self.changes()[0]["step"]

        return change["from_percent"], change["to_percent"]

    def test_should_read_a_switched_off_tax_as_zero(self):
        self.levels((0.0902, 5), (0.0002, 5))

        self.assertEqual(self.shown(), (9.0, 0.0))

    def test_should_read_a_full_rate_as_a_hundred(self):
        self.levels((0.0902, 5), (0.998, 5))

        self.assertEqual(self.shown(), (9.0, 100.0))

    def test_should_keep_a_half_step(self):
        self.levels((0.0902, 5), (0.0851, 5))

        self.assertEqual(self.shown(), (9.0, 8.5))

    def test_should_keep_exact_values_when_rounding_would_hide_the_change(self):
        """0.45 apart can land on the same half, and "9.5 to 9.5" reads as
        nothing having happened."""
        self.levels((0.0926, 5), (0.0971, 5))

        first, second = self.shown()

        self.assertNotEqual(first, second)
        self.assertAlmostEqual(first, 9.26, places=6)

    def test_should_add_up_after_rounding(self):
        """The move has to be the difference of the two numbers beside it."""
        self.levels((0.0902, 5), (0.0002, 5))

        change = self.changes()[0]["step"]

        self.assertAlmostEqual(
            change["change_points"],
            change["to_percent"] - change["from_percent"],
            places=6,
        )

    def test_should_render_a_zero_without_decimals(self):
        """"0.00" is not what anyone types into a search box."""
        self.levels((0.0902, 5), (0.0002, 5))

        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        # "0&nbsp;%" alone is inside the "Only 100&nbsp;%" button
        self.assertContains(response, "&rarr;\n                                        0&nbsp;%")
        self.assertNotContains(response, "0.00&nbsp;%")


class TestExtremeFilters(TaxChangeTestCase):
    """Buttons for a tax switched off and one turned all the way up.

    A substring search cannot do this: typing 0 also finds 10, 20 and 30.
    """

    def levels(self, *pairs):
        day = 1
        for rate, length in pairs:
            self.steady(range(day, day + length), rate)
            day += length

    def markers(self):
        return self.changes()[0]["step"]["extremes"]

    def test_should_mark_a_move_to_zero(self):
        self.levels((0.0902, 5), (0.0002, 5))

        self.assertEqual(self.markers(), "eostax-zero")

    def test_should_mark_a_move_away_from_zero(self):
        """Switching the tax back on is worth seeing too."""
        self.levels((0.0002, 5), (0.0902, 5))

        self.assertEqual(self.markers(), "eostax-zero")

    def test_should_mark_a_move_to_a_full_rate(self):
        self.levels((0.0902, 5), (0.998, 5))

        self.assertEqual(self.markers(), "eostax-full")

    def test_should_mark_both_ends(self):
        self.levels((0.0002, 5), (0.998, 5))

        self.assertEqual(self.markers(), "eostax-full eostax-zero")

    def test_should_leave_an_ordinary_move_unmarked(self):
        self.levels((0.1002, 5), (0.0902, 5))

        self.assertEqual(self.markers(), "")

    def test_should_carry_the_marker_into_the_cell(self):
        self.levels((0.0902, 5), (0.0002, 5))

        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        # the marker on its own is also the quick filter button, which
        # renders for any non empty list, and data-search= only says a row
        # exists - neither says the marker reached the cell
        self.assertContains(response, 'eostax-zero"')
        self.assertContains(response, 'data-search="9 0 eostax-zero"')

    def test_should_offer_the_buttons(self):
        self.levels((0.0902, 5), (0.0002, 5))

        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(response, 'data-eos-filter="eostax-zero"')
        self.assertContains(response, 'data-eos-filter="eostax-full"')
        self.assertContains(response, 'data-eos-filter=""')

    def test_should_hide_the_buttons_without_rows(self):
        """Nothing found, nothing to filter.

        Asserted on the button markup: the identifier also appears in the
        script that binds the clicks, on every rendering of the page.
        """
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertNotContains(response, 'data-eos-filter="eostax-zero"')
        self.assertNotContains(response, 'data-eos-filter="eostax-full"')


class TestTaxChangePages(TaxChangeTestCase):
    def setUp(self):
        super().setUp()
        self.steady(range(1, 6), 0.10)
        self.steady(range(6, 11), 0.02)

    def test_should_reject_basic_access(self):
        self.client.force_login(
            create_user("member", 97000011, CORP_ID, "Bravo Corp", ["basic_access"])
        )
        response = self.client.get(reverse("eos_tax:tax_changes"))

        self.assertEqual(response.status_code, 302)

    def test_should_reject_basic_access_on_the_detail_view(self):
        """Reaching the curve by its url must need the same permission."""
        self.client.force_login(
            create_user("nosy", 97000012, CORP_ID, "Bravo Corp", ["basic_access"])
        )
        response = self.client.get(
            reverse("eos_tax:tax_change_detail", args=[CORP_ID])
        )

        self.assertEqual(response.status_code, 302)

    def test_should_link_to_the_detail_view(self):
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(
            response, reverse("eos_tax:tax_change_detail", args=[CORP_ID])
        )

    def test_should_render_the_curve(self):
        response = self.as_admin(
            reverse("eos_tax:tax_change_detail", args=[CORP_ID]), year=YEAR
        )

        # both names also appear in the script block, which renders
        # whether or not there is a curve to draw
        self.assertContains(response, '<canvas id="eos-tax-rate-chart">')
        self.assertContains(response, 'id="eos-tax-series"')

    def test_should_make_the_table_sortable(self):
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(response, 'id="table-eos-tax-changes"')
        self.assertContains(response, "dataTables.min")

    def test_should_keep_the_order_the_server_sent(self):
        """Biggest move first. DataTables would otherwise sort by the first
        column on load and throw that away."""
        self.assertIn("order: []", read_static("tax-changes.js"))

    def test_should_load_its_script_from_a_static_file(self):
        """The config checks read the file; this is what ties it to the page."""
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(response, "eos_tax/js/tax-changes")

    def test_should_search_the_corporation_and_the_change(self):
        """The change column too, so 0 and 100 find a tax switched off or up."""
        script = read_static("tax-changes.js")

        self.assertEqual(script.count("searchable: true"), 2)
        self.assertEqual(script.count("searchable: false"), 3)

    def test_should_sort_the_change_by_its_size_not_its_text(self):
        """The cell reads as two percentages and an arrow."""
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(response, 'data-order="-8.0"')

    def test_should_sort_the_date_chronologically(self):
        """June 6 comes after June 5, which "June 6, 2026" as text does not."""
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertContains(response, f'data-order="{YEAR}-06-06"')

    def test_should_not_localise_the_sort_values(self):
        """A German locale would render the move as -8,0 and sort it as text."""
        self.client.force_login(
            create_user("german", 97000013, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        with mock.patch("eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES):
            response = self.client.get(
                reverse("eos_tax:tax_changes"),
                {"year": YEAR},
                headers={"accept-language": "de"},
            )

        self.assertNotContains(response, 'data-order="-8,0"')

    def test_should_not_leave_a_visible_template_comment(self):
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertNotContains(response, "{#")

    def test_should_offer_the_tab_to_an_admin(self):
        """Asked of another page: this one names itself in its own card
        title, whether the navigation links to it or not."""
        response = self.as_admin(reverse("eos_tax:statistics"))

        self.assertContains(
            response, f'href="{reverse("eos_tax:tax_changes")}"'
        )


class TestPayoutsThatCannotBeTrusted(TaxChangeTestCase):
    """Payouts the recovery has to drop instead of turning into a rate.

    Neither case shows up in the current journal - measured over a full year,
    every NPC was priced and no ratio came near one. Both are what the data
    starts to look like when the static data export falls behind the game, and
    both fail towards the same wrong answer: a rate that reads far too high.
    """

    def test_should_skip_a_payout_the_sde_cannot_price(self):
        """One unknown NPC would otherwise shrink the bounty, not the payout."""
        for minute in range(4):
            self.payout(1, 0.10, minute=minute * 5,
                        reason=f"{NPC_TYPE_ID}: 1,999999: 9")

        self.assertEqual(self.detail()["days"], [])

    def test_should_still_price_a_payout_the_sde_knows_in_full(self):
        for minute in range(4):
            self.payout(1, 0.10, minute=minute * 5, kills=1,
                        reason=f"{NPC_TYPE_ID}: 1")

        self.assertAlmostEqual(self.detail()["days"][0]["rate"], 0.10, places=6)

    def test_should_drop_a_share_larger_than_the_whole_bounty(self):
        """Two ratters in one tick with the same kill list are summed as if
        they were one fleet; past a hundred percent that is provably what
        happened, because no rate can take more than the bounty."""
        for minute in range(4):
            self.payout(1, 0.60, minute=minute * 5)
            self.payout(1, 0.60, minute=minute * 5)

        self.assertEqual(self.detail()["days"], [])

    def test_should_keep_a_fleet_payout_that_stays_inside_the_bounty(self):
        self.steady(range(1, 5), 0.60, shared_by=6)

        self.assertAlmostEqual(self.detail()["days"][0]["rate"], 0.60, places=6)


class TestBlacklistedCorporations(TaxChangeTestCase):
    """The blacklist promises never taxed and never listed, so it holds here too."""

    def setUp(self):
        super().setUp()
        self.steady(range(1, 4), 0.10)
        self.steady(range(4, 7), 0.20)

    def blacklist(self):
        config = TaxConfiguration.get_solo()
        config.corporation_blacklist.set(
            EveCorporationInfo.objects.filter(corporation_id=CORP_ID)
        )

    def test_should_list_the_corporation_while_it_is_not_blacklisted(self):
        self.assertEqual(len(self.changes()), 1)

    def test_should_drop_a_blacklisted_corporation(self):
        self.blacklist()

        self.assertEqual(self.changes(), [])

    def test_should_not_count_it_among_the_corporations_examined(self):
        self.blacklist()

        with mock.patch(
            "eos_tax.db.tax_changes._npc_bounties", return_value=BOUNTIES
        ):
            stats = get_corp_tax_changes(YEAR)["stats"]

        self.assertEqual(stats["corporations"], 0)


class TestYearFromTheQueryString(TaxChangeTestCase):
    """The year builds datetime(year + 1, 1, 1), which has a range of its own."""

    def setUp(self):
        super().setUp()
        self.steady(range(1, 4), 0.10)

    def assert_falls_back(self, url, year):
        response = self.as_admin(url, year=year)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["year"], datetime.datetime.now().year)

    def test_should_fall_back_on_the_last_year_datetime_accepts(self):
        self.assert_falls_back(reverse("eos_tax:tax_changes"), 9999)

    def test_should_fall_back_on_a_year_below_one(self):
        self.assert_falls_back(reverse("eos_tax:tax_changes"), 0)

    def test_should_fall_back_on_a_negative_year(self):
        self.assert_falls_back(reverse("eos_tax:tax_changes"), -1)

    def test_should_fall_back_on_the_detail_view_too(self):
        self.assert_falls_back(
            reverse("eos_tax:tax_change_detail", args=[CORP_ID]), 9999
        )

    def test_should_keep_a_year_it_can_use(self):
        response = self.as_admin(reverse("eos_tax:tax_changes"), year=YEAR)

        self.assertEqual(response.context["year"], YEAR)


class TestQuickFilterButtons(TaxChangeTestCase):
    """The group is a set of toggles, and a toggle has to announce its state.

    Bootstrap draws the pressed one with a class, which says nothing to a
    screen reader - the three buttons would read as identical and the table
    would change underneath without a reason being given.
    """

    def setUp(self):
        super().setUp()
        # not exactly zero: a payout of nothing is not written at all, so
        # there would be no first plateau and nothing to change from
        self.steady(range(1, 6), 0.0002)
        self.steady(range(6, 11), 0.0902)

    def test_should_mark_the_active_filter_as_pressed(self):
        body = self.as_admin(reverse("eos_tax:tax_changes")).content.decode()

        self.assertIn('class="btn btn-outline-secondary active"\n'
                      '                            aria-pressed="true"', body)

    def test_should_mark_the_other_filters_as_not_pressed(self):
        body = self.as_admin(reverse("eos_tax:tax_changes")).content.decode()

        self.assertEqual(body.count('aria-pressed="false"'), 2)

    def test_should_move_the_state_with_the_class(self):
        """Both are set in the same handler, so neither can drift."""
        script = read_static("tax-changes.js")

        self.assertIn('other.setAttribute("aria-pressed", "false");', script)
        self.assertIn('button.setAttribute("aria-pressed", "true");', script)
