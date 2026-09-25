"""The three bot signals beyond the hour thresholds, and their tab.

`_longest_run` and `_typical_hour` are tested directly with hand built
moments/hours - the interesting behaviour lives in a few minutes here or
there, which is easier to pin down without a database round trip. The three
`get_*` functions and the view are tested through the fixtures instead, the
way the rest of this app is.
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from django.urls import reverse

from corptools.models import CorporationAudit, CorporationWalletDivision, EveName
from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)

from eos_tax.db.bot_signals import (
    _clock_distance,
    _longest_run,
    _payouts,
    _purge_index,
    _purged_for,
    _typical_hour,
    get_clock_offset,
    get_daily_profile,
    get_unbroken_runs,
)
from eos_tax.db.shared import GROUP_LIMIT
from eos_tax.util import format_clock, format_duration
from eos_tax.models import TaxConfiguration
from eos_tax.tests.base import EosTaxTestCase, json_script
from eos_tax.views import BOT_SIGNALS

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    RATTER_ID,
    TAXED_ALLIANCE_ID,
    YEAR,
    add_entries,
    build_corporations,
    configure,
    create_corporation,
    create_alt,
    create_user,
)

BASE = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)

# A second character beyond the two the shared fixtures name, for the tests
# that need three distinct people rather than two.
WANDERER_ID = 2100000003

# The rest of the Corporation. Since a character is no longer measured against
# a window their own payouts helped build, every fixture needs somebody else
# to be the Corporation.
CROWD_ID = 2100000004


def _moments(*minute_offsets):
    return [BASE + timedelta(minutes=offset) for offset in minute_offsets]


# The two minute values the shipped configuration carries. Written out here
# rather than read from it: these tests are about the chain finder, and would
# otherwise start passing or failing according to somebody's settings page.
TOLERANCE = 25
CEILING = 60


def _run(moments, max_gaps):
    """The chain finder at the shipped tolerance and ceiling."""
    return _longest_run(moments, max_gaps, TOLERANCE, CEILING)


class TestLongestRun(EosTaxTestCase):
    """The chain finder itself, independent of the database.

    A handful of minutes decide every case here, which is more exactly
    expressed as timestamps than as journal rows.
    """

    def test_should_report_no_run_for_no_payouts(self):
        self.assertEqual(_run([], max_gaps=0)["ticks"], 0)

    def test_should_report_one_tick_for_a_single_payout(self):
        self.assertEqual(_run(_moments(0), max_gaps=0)["ticks"], 1)

    def test_should_chain_five_payouts_twenty_minutes_apart(self):
        run = _run(_moments(0, 20, 40, 60, 80), max_gaps=0)

        self.assertEqual(run["ticks"], 5)
        self.assertEqual(run["gaps"], 0)

    def test_should_not_break_on_a_gap_at_the_tolerance(self):
        """25 minutes is the tolerance itself - still one uninterrupted chain."""
        run = _run(_moments(0, 25, 50), max_gaps=0)

        self.assertEqual(run["ticks"], 3)
        self.assertEqual(run["gaps"], 0)

    def test_should_break_on_a_gap_just_over_tolerance_without_allowance(self):
        run = _run(_moments(0, 26), max_gaps=0)

        # the two payouts land in separate fragments, so the longest is one tick
        self.assertEqual(run["ticks"], 1)

    def test_should_survive_a_gap_just_over_tolerance_with_one_allowance(self):
        run = _run(_moments(0, 26), max_gaps=1)

        self.assertEqual(run["ticks"], 2)
        self.assertEqual(run["gaps"], 1)

    def test_should_always_break_on_a_gap_over_the_hour_cap(self):
        """The most important case: the ceiling overrides max_gaps entirely.

        Without this cap a generous max_gaps would weld a morning and an
        evening session into one twelve hour chain.
        """
        # two three tick chains, 70 minutes apart - past the ceiling (60)
        moments = _moments(0, 20, 40, 110, 130, 150)

        run = _run(moments, max_gaps=5)

        self.assertEqual(run["ticks"], 3)

    def test_should_report_the_longer_of_two_chains_with_its_own_span(self):
        moments = _moments(0, 20, 40, 110, 130, 150, 170, 190)

        run = _run(moments, max_gaps=0)

        self.assertEqual(run["ticks"], 5)
        self.assertEqual(run["start"], BASE + timedelta(minutes=110))
        self.assertEqual(run["end"], BASE + timedelta(minutes=190))

    def test_should_report_the_gaps_of_the_reported_chain_only(self):
        """A short chain earlier in the list used its one allowed gap and
        then ended past the ceiling; the longer chain reported here has none
        of its own, and the number returned must say so rather than carry
        the earlier chain's count."""
        moments = _moments(0, 20, 50, 200, 220, 240, 260, 280, 300)

        run = _run(moments, max_gaps=1)

        self.assertEqual(run["ticks"], 6)
        self.assertEqual(run["gaps"], 0)
        self.assertEqual(run["start"], BASE + timedelta(minutes=200))
        self.assertEqual(run["end"], BASE + timedelta(minutes=300))

    def test_should_give_up_the_oldest_interruption_rather_than_start_over(self):
        """2 + 15 + 15 ticks with one interruption allowed: the last two
        blocks make 30 together. Starting from scratch at the second
        interruption threw away the middle block and reported 17."""
        ticks = [0, 20]
        ticks += [65 + 20 * index for index in range(15)]
        ticks += [ticks[-1] + 45 + 20 * index for index in range(15)]

        run = _run(_moments(*ticks), max_gaps=1)

        self.assertEqual(run["ticks"], 30)
        self.assertEqual(run["gaps"], 1)
        self.assertEqual(run["start"], BASE + timedelta(minutes=65))

    def test_should_slide_with_no_interruption_allowed_at_all(self):
        """With an allowance of nothing an interruption is a plain end."""
        run = _run(_moments(0, 20, 60, 80, 100), max_gaps=0)

        self.assertEqual(run["ticks"], 3)
        self.assertEqual(run["gaps"], 0)


class TestPurgedBaseline(EosTaxTestCase):
    """Who comes out of a yardstick, and how often.

    A character's own payouts are subtracted from their Corporation before
    they are measured against it. A character who is themselves flagged must
    therefore not be subtracted a second time along with the other flagged
    ones - they would be compared against a Corporation short of them twice.
    """

    def setUp(self):
        self.characters = {
            1: {"corp_id": 7, "moments": _moments(0, 1, 2, 3)},
            2: {"corp_id": 7, "moments": _moments(60, 61, 62, 63, 64, 65)},
        }
        self.index = _purge_index(self.characters, {1, 2})

    def test_should_sum_the_flagged_characters_per_corporation(self):
        self.assertEqual(self.index[7]["hours"], Counter({0: 4, 1: 6}))
        self.assertEqual(self.index[7]["ids"], {1, 2})

    def test_should_leave_out_the_measured_character_when_they_are_flagged(self):
        purged = _purged_for(self.index, 7, 1, Counter({0: 4}))

        self.assertEqual(purged, Counter({1: 6}))

    def test_should_hand_over_every_flagged_character_for_somebody_else(self):
        purged = _purged_for(self.index, 7, 3, Counter({5: 2}))

        self.assertEqual(purged, Counter({0: 4, 1: 6}))

    def test_should_hand_over_nothing_for_a_corporation_without_flagged_members(self):
        self.assertIsNone(_purged_for(self.index, 99, 1, Counter()))
        self.assertIsNone(_purged_for(None, 7, 1, Counter()))


class TestUnbrokenRuns(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()

    def test_should_list_a_character_over_the_threshold_and_skip_one_under_it(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (0,), entries=3)

        result = get_unbroken_runs(YEAR, MONTH, min_ticks=5, max_gaps=0)

        names = [row["character_name"] for row in result["rows"]]
        self.assertEqual(names, ["Busy Ratter"])
        # a hit means the fallback list has nothing to add
        self.assertEqual(result["longest"], [])

    def test_should_sort_rows_by_the_longest_run_first(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (0,), entries=3)

        result = get_unbroken_runs(YEAR, MONTH, min_ticks=1, max_gaps=0)

        names = [row["character_name"] for row in result["rows"]]
        self.assertEqual(names, ["Busy Ratter", "Casual Pilot"])

    def test_should_fall_back_to_the_longest_runs_when_nothing_qualifies(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (0,), entries=3)

        result = get_unbroken_runs(YEAR, MONTH, min_ticks=100, max_gaps=0)

        self.assertEqual(result["rows"], [])
        names = [row["character_name"] for row in result["longest"]]
        self.assertEqual(names, ["Busy Ratter", "Casual Pilot"])

    def test_should_cap_the_fallback_list_at_the_limit(self):
        """One over the cap is what shows a cap; more only costs rows.

        Every character here is its own main, so a row and a group are the
        same thing and this does not yet tell the row cap from the group cap
        apart. The next test does."""
        for index in range(GROUP_LIMIT + 1):
            character_id = 2100002000 + index
            EveName.objects.create(
                eve_id=character_id, name=f"Pilot {index}", category="character"
            )
            add_entries(
                self.divisions[BRAVO_CORP_ID], character_id, 1, (index % 12,), entries=2
            )

        result = get_unbroken_runs(YEAR, MONTH, min_ticks=100, max_gaps=0)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["stats"]["groups_total"], GROUP_LIMIT)

    def test_should_show_ten_mains_even_when_two_of_the_top_rows_share_one(self):
        """Slicing the fallback to ten rows before grouping used to cost a
        main its whole listing: two alts of the same account filled two of
        those ten slots, and the eleventh row - a main of its own - never
        reached the grouping step to be counted."""
        owner = create_user("topalt", 94100060, BRAVO_CORP_ID, "Bravo Corp")
        EveName.objects.create(
            eve_id=94100060, name="topalt character", category="character"
        )
        create_alt(owner, RATTER_ID, "Busy Ratter")
        # ranked first and second: six ticks each, well above the two-tick
        # singles below
        for character_id in (94100060, RATTER_ID):
            add_entries(
                self.divisions[BRAVO_CORP_ID], character_id, 1, (0,), entries=6
            )

        # nine more mains of their own, ranked third through eleventh
        for index in range(9):
            character_id = 2100002000 + index
            EveName.objects.create(
                eve_id=character_id, name=f"Pilot {index}", category="character"
            )
            add_entries(
                self.divisions[BRAVO_CORP_ID], character_id, 1, (index % 12,), entries=2
            )

        result = get_unbroken_runs(YEAR, MONTH, min_ticks=100, max_gaps=0)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["stats"]["groups_total"], GROUP_LIMIT)
        self.assertEqual(len(result["groups"]), GROUP_LIMIT)

    def test_should_use_the_configured_thresholds_when_none_are_given(self):
        config = TaxConfiguration.get_solo()
        config.bot_run_min_ticks = 4
        config.bot_run_max_gaps = 0
        config.save()
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=5)

        result = get_unbroken_runs(YEAR, MONTH)

        self.assertEqual(result["stats"]["min_ticks"], 4)
        self.assertEqual(result["stats"]["max_gaps"], 0)
        self.assertEqual(
            [row["character_name"] for row in result["rows"]], ["Busy Ratter"]
        )

    def test_should_drop_a_blacklisted_corporation(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        before = get_unbroken_runs(YEAR, MONTH, min_ticks=1, max_gaps=0)
        self.assertEqual(before["stats"]["characters"], 1)

        TaxConfiguration.get_solo().corporation_blacklist.add(
            EveCorporationInfo.objects.get(corporation_id=BRAVO_CORP_ID)
        )

        after = get_unbroken_runs(YEAR, MONTH, min_ticks=1, max_gaps=0)
        self.assertEqual(after["rows"], [])
        self.assertEqual(after["longest"], [])
        self.assertEqual(after["stats"]["characters"], 0)

    def test_should_read_the_tick_tolerance_from_the_configuration(self):
        """An hour between two payouts is a break at the shipped tolerance and
        an ordinary tick at a wider one - the same journal, two answers."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 1), entries=1)

        def ticks():
            rows = get_unbroken_runs(YEAR, MONTH, min_ticks=1, max_gaps=0)["rows"]

            return rows[0]["ticks"]

        self.assertEqual(ticks(), 1)

        config = TaxConfiguration.get_solo()
        config.bot_run_tick_tolerance = 60
        config.save()

        self.assertEqual(ticks(), 2)

    def test_should_read_the_break_ceiling_from_the_configuration(self):
        """Two hours apart is past the shipped ceiling, so no allowance can
        bridge it - the allowance only applies below the ceiling, which is
        what keeps one of them from welding a morning to an evening."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 2), entries=1)

        def ticks():
            rows = get_unbroken_runs(YEAR, MONTH, min_ticks=1, max_gaps=1)["rows"]

            return rows[0]["ticks"]

        self.assertEqual(ticks(), 1)

        config = TaxConfiguration.get_solo()
        config.bot_run_gap_minutes = 120
        config.save()

        self.assertEqual(ticks(), 2)


class TestDailyProfile(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        # the journal references a name, so the rest of the Corporation needs
        # one before it can have payouts
        EveName.objects.create(
            eve_id=CROWD_ID, name="Crowd Pilot", category="character"
        )

    def setUp(self):
        configure()

    def build_rows(self):
        """A Corporation working hours 0-7, and one character who does not.

        Crowd is the Corporation: 64 payouts on its schedule, enough to be a
        yardstick for everyone else after their own payouts come out. Ratter
        follows that schedule, Casual spreads evenly over the whole day.
        """
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(8)), entries=8
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=5
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, tuple(range(24)), entries=2
        )

        # the measurement, not the list: these tests are about the
        # arithmetic, and half of their characters are ordinary on purpose
        return get_daily_profile(YEAR, MONTH)["measured"]

    def row_for(self, rows, name):
        return next(row for row in rows if row["character_name"] == name)

    def test_should_report_no_rows_when_the_corporation_is_below_its_payout_floor(self):
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 1, 2, 3, 4), entries=1
        )

        self.assertEqual(get_daily_profile(YEAR, MONTH)["measured"], [])

    def test_should_drop_a_character_below_its_own_payout_floor(self):
        # Crowd is the yardstick for both; Casual stays too thin to be measured
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(8)), entries=8
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=5
        )
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (10,), entries=5)

        names = [
            row["character_name"]
            for row in get_daily_profile(YEAR, MONTH)["measured"]
        ]

        self.assertIn("Busy Ratter", names)
        self.assertNotIn("Casual Pilot", names)

    def test_should_not_flag_a_character_who_keeps_the_corp_schedule(self):
        """Ratter is inside the window every time, and so is the yardstick
        once Casual is out of it: the honest member and the honest part of the
        Corporation agree exactly, which is nothing to report."""
        ratter = self.row_for(self.build_rows(), "Busy Ratter")

        # Casual is flat enough to be flagged, so the second pass measures
        # against Crowd alone - 64 payouts, all of them on the schedule
        self.assertEqual(ratter["share"], 100)
        self.assertEqual(ratter["corp_share"], 100)
        self.assertEqual(ratter["difference"], 0)
        self.assertEqual(ratter["level"], "low")

    def test_should_leave_the_flagged_out_of_the_yardstick(self):
        """Casual is 48 of the Corporation's 112 payouts and spread over the
        whole clock, so leaving them in the yardstick drags it flat and makes
        everybody else look concentrated by comparison - the reading hiding
        its own findings behind the loudest of them."""
        self.build_rows()
        report = get_daily_profile(YEAR, MONTH)
        purged = self.row_for(report["measured"], "Busy Ratter")

        self.assertEqual(report["stats"]["purged"], 1)
        self.assertEqual(purged["corp_share"], 100)

        config = TaxConfiguration.get_solo()
        config.bot_rhythm_purge_strong = False
        config.save()

        plain = get_daily_profile(YEAR, MONTH)
        kept = self.row_for(plain["measured"], "Busy Ratter")

        # 80 of 112 in the window once Casual is back in it
        self.assertEqual(plain["stats"]["purged"], 0)
        self.assertEqual(kept["corp_share"], 71)
        self.assertEqual(kept["difference"], -29)

    def test_should_keep_the_plain_yardstick_when_purging_leaves_too_little(self):
        """A Corporation that would fall under its own floor keeps the whole
        of itself. Losing its members from the reading altogether would hide
        findings, which is the opposite of the point."""
        # Crowd is flat and flagged; without Crowd nothing is left of the
        # Corporation, so Ratter is still measured against Crowd
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(24)), entries=3
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=5
        )

        report = get_daily_profile(YEAR, MONTH)
        names = [row["character_name"] for row in report["measured"]]

        self.assertEqual(report["stats"]["purged"], 1)
        self.assertIn("Busy Ratter", names)

    def test_should_report_a_smaller_share_for_a_character_spread_across_the_day(self):
        """Eight hours out of twenty-four is a third, which is where a
        character spread evenly over the clock always lands."""
        casual = self.row_for(self.build_rows(), "Casual Pilot")

        # without Casual the Corporation is entirely on schedule
        self.assertEqual(casual["share"], 33)
        self.assertEqual(casual["corp_share"], 100)
        self.assertEqual(casual["difference"], 67)
        self.assertEqual(casual["level"], "high")

    def test_should_sort_rows_by_the_largest_difference_first(self):
        names = [row["character_name"] for row in self.build_rows()]

        self.assertEqual(names, ["Casual Pilot", "Busy Ratter", "Crowd Pilot"])

    def test_should_read_the_length_of_the_busy_window_from_the_configuration(self):
        """The window is the yardstick, so its length moves every score with
        it. Crowd works twelve hours evenly: eight of them hold two thirds of
        the day, twelve hold all of it."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(12)), entries=6
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(12)), entries=5
        )

        def corp_share():
            report = get_daily_profile(YEAR, MONTH)

            return (
                self.row_for(report["measured"], "Busy Ratter")["corp_share"],
                report["stats"]["busy_hours"],
            )

        self.assertEqual(corp_share(), (67, 8))

        config = TaxConfiguration.get_solo()
        config.bot_rhythm_busy_hours = 12
        config.save()

        self.assertEqual(corp_share(), (100, 12))

    def test_should_list_only_what_reaches_the_difference_threshold(self):
        """Ranking without cutting filled the table with characters more
        concentrated than their own Corporation - the opposite of what this
        looks for - and left the reader to find the few that were not.

        The threshold is set here rather than taken from the configuration:
        this is about the cut, and reading the shipped default would make the
        test move whenever somebody tunes the page.
        """
        config = TaxConfiguration.get_solo()
        config.bot_rhythm_min_difference = 50
        config.save()

        rows = self.build_rows()

        # Casual is spread over the whole clock, Ratter keeps the schedule
        self.assertEqual(
            [row["character_name"] for row in rows][:1], ["Casual Pilot"]
        )

        report = get_daily_profile(YEAR, MONTH)
        listed = [row["character_name"] for row in report["rows"]]

        self.assertIn("Casual Pilot", listed)
        self.assertNotIn("Busy Ratter", listed)
        self.assertEqual(len(report["measured"]), 3)

    def test_should_fall_back_to_the_largest_differences_when_none_qualify(self):
        """An empty table says the threshold was not met. It does not say by
        how much, which is the thing worth knowing when the threshold is the
        setting under discussion."""
        config = TaxConfiguration.get_solo()
        config.bot_rhythm_min_difference = 100
        config.save()

        self.build_rows()
        report = get_daily_profile(YEAR, MONTH)

        self.assertEqual(report["rows"], [])
        self.assertEqual(len(report["longest"]), 3)
        self.assertTrue(report["groups"])


class TestPayoutsPerCharacter(EosTaxTestCase):
    """Who a payout belongs to, before any reading looks at it."""

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()

    def test_should_count_a_character_who_moved_with_the_last_corporation(self):
        """Whichever row the unordered query returned first used to decide,
        so a character who moved could change Corporation between page
        loads. Many early rows in the old one must not outvote the move."""
        alpha = create_corporation(
            ALPHA_CORP_ID, "Alpha Corp",
            EveAllianceInfo.objects.get(alliance_id=TAXED_ALLIANCE_ID),
        )
        division = CorporationWalletDivision.objects.create(
            corporation=CorporationAudit.objects.create(corporation=alpha),
            balance=0, division=1,
        )
        add_entries(division, RATTER_ID, 1, (1, 2, 3), corp_id=ALPHA_CORP_ID, entries=5)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 20, (4,))

        self.assertEqual(_payouts(YEAR, MONTH)[RATTER_ID]["corp_id"], BRAVO_CORP_ID)

    def test_should_drop_a_payout_without_a_second_party(self):
        add_entries(self.divisions[BRAVO_CORP_ID], None, 1, (4,))

        self.assertNotIn(None, _payouts(YEAR, MONTH))


class TestTypicalHourAndClockDistance(EosTaxTestCase):
    def test_should_place_an_hour_at_its_middle(self):
        """Payouts in the 12 o'clock bucket fall anywhere from 12:00 to
        12:59, so the bucket stands for half past - reading it as its
        start put every middle of a day half an hour early."""
        self.assertAlmostEqual(_typical_hour({12: 5}), 12.5, places=6)

    def test_should_average_across_midnight_toward_zero_not_toward_noon(self):
        """The reason the circular mean exists: 23:00 and 01:00 average to
        a time near midnight, not to 12:00 as a plain mean would give."""
        middle = _typical_hour({23: 1, 1: 1})

        self.assertLess(_clock_distance(middle, 0.5), 0.01)
        self.assertGreater(_clock_distance(middle, 12), 5)

    def test_should_find_no_middle_in_a_day_spread_evenly_round_the_clock(self):
        """24 equal hours have no middle; the angle of their average is
        rounding noise, and a single extra payout used to drag it to
        whichever hour it fell in."""
        flat = {hour: 10 for hour in range(24)}
        nudged = {**flat, 3: 11}

        self.assertIsNone(_typical_hour(flat, 0.2))
        self.assertIsNone(_typical_hour(nudged, 0.2))

    def test_should_keep_a_middle_for_an_ordinary_evening(self):
        """Six hours of an evening are concentrated far beyond the shipped
        floor - the threshold only ever removes days that are nearly flat."""
        evening = {hour: 10 for hour in range(18, 24)}

        self.assertAlmostEqual(_typical_hour(evening, 0.2), 21, places=6)

    def test_should_ignore_the_floor_when_none_is_given(self):
        """The rhythm reading asks for a middle without a floor."""
        self.assertIsNotNone(_typical_hour({hour: 10 for hour in range(24)}))

    def test_should_measure_the_short_way_round_the_clock(self):
        self.assertEqual(_clock_distance(23, 1), 2)


class TestClockOffset(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        for eve_id, name in (
            (WANDERER_ID, "Wandering Pilot"), (CROWD_ID, "Crowd Pilot")
        ):
            EveName.objects.create(eve_id=eve_id, name=name, category="character")

    def setUp(self):
        configure()
        # the Crowd's own yardstick here is noon against midnight, which
        # has no middle to speak of; these tests are about distance and
        # order, and the floor gets its own tests below
        config = TaxConfiguration.get_solo()
        config.bot_clock_min_concentration = 0
        config.save()

    def build_rows(self):
        """A Corporation anchored at noon and two characters twelve hours off.

        Noon and midnight are opposite points of the clock, so the circular
        mean of the two sides lands exactly on the heavier one however the
        payouts are split - which keeps the expected middle at 12 whichever
        character is being left out of it.

        Casual and Wandering sit the same distance from that middle and carry
        different payout counts, which is the tie break.
        """
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (12,), entries=60)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (12,), entries=45)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (0,), entries=15)
        add_entries(self.divisions[BRAVO_CORP_ID], WANDERER_ID, 1, (0,), entries=20)

        # the measurement, not the list - two of these four characters
        # sit right on top of their Corporation, which is the point
        return get_clock_offset(YEAR, MONTH)["measured"]

    def test_should_report_the_distance_between_a_characters_middle_and_the_corps(self):
        rows = {row["character_name"]: row for row in self.build_rows()}

        # the noon bucket stands for half past twelve
        self.assertEqual(rows["Busy Ratter"]["middle"], 12.5)
        self.assertEqual(rows["Busy Ratter"]["corp_middle"], 12.5)
        self.assertEqual(rows["Busy Ratter"]["apart"], 0.0)
        self.assertEqual(rows["Casual Pilot"]["apart"], 12.0)
        self.assertEqual(rows["Wandering Pilot"]["apart"], 12.0)

    def test_should_sort_by_the_largest_gap_then_by_more_payouts(self):
        names = [row["character_name"] for row in self.build_rows()]

        # two ties, each broken by the better evidenced row
        self.assertEqual(
            names,
            ["Wandering Pilot", "Casual Pilot", "Crowd Pilot", "Busy Ratter"],
        )

    def test_should_read_the_full_deviation_distance_from_the_configuration(self):
        """Six hours from the Corporation is halfway across the clock at the
        shipped scale and the whole way across at a six hour one. The distance
        does not change; what counts as far does."""
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (12,), entries=60)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (18,), entries=20)

        def reading():
            rows = {
                row["character_name"]: row
                for row in get_clock_offset(YEAR, MONTH)["measured"]
            }

            return rows["Busy Ratter"]["apart"], rows["Busy Ratter"]["level"]

        self.assertEqual(reading(), (6.0, "medium"))

        config = TaxConfiguration.get_solo()
        config.bot_clock_max_apart = 6
        config.save()

        self.assertEqual(reading(), (6.0, "high"))

    def test_should_list_only_what_reaches_the_distance_threshold(self):
        """Everybody sits some distance from their Corporation; most of it is
        the difference between playing after work and playing after dinner."""
        self.build_rows()
        report = get_clock_offset(YEAR, MONTH)
        listed = [row["character_name"] for row in report["rows"]]

        # twelve hours away, against two who sit on the Corporation's own hour
        self.assertEqual(sorted(listed), ["Casual Pilot", "Wandering Pilot"])
        self.assertEqual(len(report["measured"]), 4)

    def test_should_fall_back_to_the_largest_distances_when_none_qualify(self):
        """An empty table says the threshold was not met. It does not say by
        how much, which is the thing worth knowing when the threshold is the
        setting under discussion.

        A Corporation keeping one hour and a member keeping the next: an hour
        apart, well under the shipped four, and nobody is listed.
        """
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (12,), entries=60)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (13,), entries=45)

        report = get_clock_offset(YEAR, MONTH)

        self.assertEqual(report["rows"], [])
        self.assertEqual(len(report["longest"]), 2)
        self.assertTrue(report["groups"])

    def test_should_leave_out_a_character_whose_day_has_no_middle(self):
        """A round the clock script gets no distance at all rather than
        the random one the rounding of a flat day would give it."""
        config = TaxConfiguration.get_solo()
        config.bot_clock_min_concentration = 20
        config.save()
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (12,), entries=60)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, range(24), entries=2)

        names = [row["character_name"] for row in get_clock_offset(YEAR, MONTH)["measured"]]

        self.assertNotIn("Busy Ratter", names)

    def test_should_count_listed_characters_against_measured_ones(self):
        """"9 of 40 measured" set mains against characters; both figures
        are characters now. The two listed characters share one main here,
        which is what tells the two counts apart."""
        owner = create_user("clockmain", 94100060, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, CASUAL_ID, "Casual Pilot")
        create_alt(owner, WANDERER_ID, "Wandering Pilot")
        self.build_rows()
        stats = get_clock_offset(YEAR, MONTH)["stats"]

        self.assertEqual(stats["groups_total"], 1)
        self.assertEqual(stats["listed_characters"], 2)
        self.assertEqual(stats["measured_characters"], 4)


class TestBotSignalView(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()

    def test_should_render_each_signal_as_a_fragment(self):
        self.client.force_login(
            create_user("boss", 94100001, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.client.get(
                    reverse("eos_tax:bot_signal", args=[name]),
                    {"month": f"{YEAR}-{MONTH:02d}"},
                )

                self.assertEqual(response.status_code, 200)
                # a fragment, not a full page - the tab injects it with innerHTML
                self.assertNotIn("<html", response.content.decode())

    def test_should_404_for_an_unknown_signal(self):
        self.client.force_login(
            create_user("boss", 94100002, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bot_signal", args=["unknown"]))

        self.assertEqual(response.status_code, 404)

    def test_should_redirect_without_admin_view(self):
        self.client.force_login(
            create_user("member", 94100003, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:bot_signal", args=["runs"]))

        self.assertEqual(response.status_code, 302)

    def test_should_reflect_the_selected_month(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)
        config = TaxConfiguration.get_solo()
        config.bot_run_min_ticks = 3
        config.bot_run_max_gaps = 0
        config.save()
        self.client.force_login(
            create_user("boss", 94100004, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        with_data = self.client.get(
            reverse("eos_tax:bot_signal", args=["runs"]), {"month": f"{YEAR}-{MONTH:02d}"}
        )
        without_data = self.client.get(
            reverse("eos_tax:bot_signal", args=["runs"]),
            {"month": f"{YEAR}-{MONTH + 1:02d}"},
        )

        self.assertContains(with_data, "Busy Ratter")
        self.assertNotContains(without_data, "Busy Ratter")
        self.assertContains(without_data, "No taxed income in this month.")

    def test_should_show_the_characters_age_in_every_reading(self):
        """The age comes from grouped(), which every reading funnels its
        rows through - one shared computation, one column wired per
        template. A handful of entries is enough: with nothing crossing a
        threshold each reading falls back to listing what it has, and the
        character still carries its age there."""
        EveCharacter.objects.create(
            character_id=RATTER_ID,
            character_name="Busy Ratter",
            corporation_id=BRAVO_CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRAVO",
            birthday=date(YEAR - 1, MONTH, 1),
        )
        # rhythm and clock both measure a character against the rest of its
        # own Corporation, never against itself - so a second character has
        # to carry the baseline, and the minimum needed for one is lowered
        # rather than manufactured, since that gate is not what this test
        # is about
        config = TaxConfiguration.get_solo()
        config.bot_rhythm_min_payouts = 1
        config.bot_rhythm_corp_min_payouts = 1
        config.bot_clock_min_payouts = 1
        config.bot_clock_corp_min_payouts = 1
        # four hours six apart are a perfectly flat day, which has no
        # middle; the age column is what this is about
        config.bot_clock_min_concentration = 0
        config.save()
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 6, 12, 18))
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 2, (1, 7, 13, 19))
        self.client.force_login(
            create_user("boss", 94100005, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.client.get(
                    reverse("eos_tax:bot_signal", args=[name]),
                    {"month": f"{YEAR}-{MONTH:02d}"},
                )

                self.assertContains(response, "1 y")


class TestBotsPageTabs(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def setUp(self):
        self.client.force_login(
            create_user("boss", 94100005, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def page(self):
        return self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

    def test_should_mark_the_list_links_to_be_kept_on_the_open_tab(self):
        """Opening a Character from a list dropped the reader onto the matrix,
        whichever list they came from - the same fault the dropdown had, from
        the other direction."""
        for day in (1, 2):
            add_entries(
                self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18)
            )

        self.assertContains(self.page(), "data-eos-keep-tab")

    def test_should_carry_all_four_tab_targets_and_the_config_element(self):
        response = self.page()

        for target in ("hours", "runs", "rhythm", "clock"):
            with self.subTest(target=target):
                self.assertContains(response, f'id="eos-tax-tab-{target}"')

        self.assertContains(response, 'id="eos-tax-config"')

    def test_should_give_each_signal_tab_a_url_for_the_displayed_month(self):
        """Parsed as JSON, not grepped as a substring - a URL that merely
        mentions the right characters somewhere is not the same as a tab
        that loads the right month."""
        response = self.page()
        config = json_script(response.content.decode(), "eos-tax-config")

        month = f"{YEAR}-{MONTH:02d}"
        for name in BOT_SIGNALS:
            with self.subTest(name=name):
                expected = f"{reverse('eos_tax:bot_signal', args=[name])}?month={month}"
                self.assertEqual(config["signals"][name], expected)

    def test_should_keep_the_hour_thresholds_inside_their_own_tab(self):
        """The explanation used to sit above the tab strip, where it read as
        the heading of all four tabs while describing only the first - so
        somebody looking at unbroken runs was being told about hours."""
        body = self.page().content.decode()

        hours = body.index('id="eos-tax-tab-hours"')
        runs = body.index('id="eos-tax-tab-runs"')
        text = body.index("hours of a day, on at least")

        self.assertGreater(text, hours)
        self.assertLess(text, runs)


class TestTimeFormatting(EosTaxTestCase):
    """A time of day and a length, written so nobody has to convert them.

    These tabs printed 14.6 for a time and 4.7 for a length, which is the
    arithmetic the page exists to save the reader.
    """

    def test_should_write_a_fractional_hour_as_a_time(self):
        self.assertEqual(format_clock(14.6), "14:36")
        self.assertEqual(format_clock(18.7), "18:42")

    def test_should_keep_a_time_inside_the_day(self):
        """The circular mean lands just short of midnight as readily as just
        past it, and 24:00 is not a time anyone writes."""
        self.assertEqual(format_clock(23.99), "23:59")
        self.assertEqual(format_clock(24.0), "00:00")
        self.assertEqual(format_clock(0.0), "00:00")

    def test_should_say_nothing_for_a_missing_time(self):
        self.assertEqual(format_clock(None), "")
        self.assertEqual(format_duration(None), "")

    def test_should_write_a_length_with_both_units(self):
        self.assertEqual(format_duration(4.7), "4 h 42 min")

    def test_should_drop_the_part_that_is_zero(self):
        self.assertEqual(format_duration(5.0), "5 h")
        self.assertEqual(format_duration(0.5), "30 min")


class TestRunPresentation(EosTaxTestCase):
    """What a run row carries beyond its length."""

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=12)

    def test_should_never_call_a_run_below_the_threshold_strong(self):
        """The fallback list is made of runs that did not reach the threshold
        and says so in the line above it. Calling them strong made the tab
        contradict itself."""
        report = get_unbroken_runs(YEAR, MONTH, min_ticks=18, max_gaps=0)

        self.assertEqual(report["rows"], [])
        self.assertTrue(report["longest"])

        for row in report["longest"]:
            with self.subTest(character=row["character_name"]):
                self.assertNotEqual(row["level"], "high")

    def test_should_call_a_run_that_reaches_the_threshold_strong(self):
        report = get_unbroken_runs(YEAR, MONTH, min_ticks=12, max_gaps=0)

        self.assertEqual(report["rows"][0]["level"], "high")

    def test_should_carry_the_span_as_well_as_the_length(self):
        """So the reader sees when it happened without adding the duration
        back onto the start."""
        row = get_unbroken_runs(YEAR, MONTH, min_ticks=2, max_gaps=0)["rows"][0]

        self.assertLess(row["started_at"], row["ended_at"])
        self.assertTrue(row["duration"])
        self.assertTrue(row["same_day"])
