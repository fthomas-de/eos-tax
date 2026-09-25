"""The character detail page's three fetched tabs: run, rhythm and clock.

`get_run_detail`, `get_rhythm_detail` and `get_clock_detail` are the same
three readings `test_bot_signals.py` covers for the whole roster, read for
one character instead. The fixtures and the style follow that module; only
the shape of the result differs, because a detail page draws points and a
list page draws rows.
"""

import datetime
import re

from django.urls import reverse

from allianceauth.eveonline.models import EveCharacter
from corptools.models import CorporationWalletJournalEntry, EveName

from eos_tax.db.bot_signals import (
    _clock_distance,
    get_clock_detail,
    get_rhythm_detail,
    get_run_detail,
)
from eos_tax.models import TaxConfiguration
from eos_tax.tests.base import EosTaxTestCase, json_script, read_static
from eos_tax.util import format_duration

from .factories import (
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    add_entries,
    build_corporations,
    configure,
    create_alt,
    create_user,
    entry_ids,
)

# The rest of the Corporation for the exclusion cases. Since a character is
# never measured against a window their own payouts helped build, most of
# these fixtures need somebody else to be "the Corporation".
CROWD_ID = 2100000030


class TestRunDetail(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()

    def test_should_report_no_run_for_an_unknown_character(self):
        result = get_run_detail(999999999, YEAR, MONTH)

        self.assertEqual(result["points"], [])
        self.assertIsNone(result["run"])

    def test_should_report_one_point_per_payout_with_day_and_decimal_hour(self):
        # minutes 0..30 in hour 12, so one payout lands exactly on 12:30
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (12,), entries=31)

        points = get_run_detail(RATTER_ID, YEAR, MONTH)["points"]

        self.assertEqual(len(points), 31)
        half_past = next(point for point in points if point["hour"] == 12.5)
        self.assertEqual(half_past["day"], 1)

    def test_should_mark_only_the_longest_chain_as_in_run(self):
        """A short chain and a long chain on the same day - only the long one
        may come back marked. This is the case a Corporation-wide unbroken
        run picks correctly already; the detail page draws it point by point
        and has its own chance to get it wrong."""
        # two ticks a minute apart, then a gap past the break ceiling
        # (bot_run_gap_minutes), then five
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=2)
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (3,), entries=5)

        points = get_run_detail(RATTER_ID, YEAR, MONTH, max_gaps=0)["points"]
        short_chain = [point for point in points if point["hour"] < 1]
        long_chain = [point for point in points if point["hour"] >= 1]

        self.assertEqual(len(short_chain), 2)
        self.assertEqual(len(long_chain), 5)
        self.assertTrue(all(not point["in_run"] for point in short_chain))
        self.assertTrue(all(point["in_run"] for point in long_chain))

    def test_should_carry_ticks_gaps_duration_same_day_and_level_on_the_run(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        run = get_run_detail(RATTER_ID, YEAR, MONTH, max_gaps=0)["run"]

        self.assertEqual(run["ticks"], 6)
        self.assertEqual(run["gaps"], 0)
        self.assertEqual(run["duration"], format_duration(5 / 60))
        self.assertTrue(run["same_day"])
        # six ticks against the shipped eighteen: a third of the way, which
        # is where the middle band starts
        self.assertEqual(run["level"], "medium")

    def test_should_not_call_a_run_high_before_it_reaches_the_configured_threshold(self):
        """The case the tab used to contradict itself on: a run short of the
        configured threshold must not be called strong."""
        config = TaxConfiguration.get_solo()
        config.bot_run_min_ticks = 10
        config.save()
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=9)

        run = get_run_detail(RATTER_ID, YEAR, MONTH, max_gaps=0)["run"]

        self.assertEqual(run["ticks"], 9)
        self.assertNotEqual(run["level"], "high")

    def test_should_call_a_run_high_once_it_reaches_the_configured_threshold(self):
        config = TaxConfiguration.get_solo()
        config.bot_run_min_ticks = 10
        config.save()
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=10)

        run = get_run_detail(RATTER_ID, YEAR, MONTH, max_gaps=0)["run"]

        self.assertEqual(run["ticks"], 10)
        self.assertEqual(run["level"], "high")


class TestRhythmDetail(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        EveName.objects.create(eve_id=CROWD_ID, name="Crowd Pilot", category="character")

    def setUp(self):
        configure()

    def test_should_report_an_empty_series_for_an_unknown_character(self):
        self.assertEqual(get_rhythm_detail(999999999, YEAR, MONTH)["series"], [])

    def test_should_always_return_twenty_four_hourly_entries(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (2, 5, 9), entries=4)

        series = get_rhythm_detail(RATTER_ID, YEAR, MONTH)["series"]

        self.assertEqual(len(series), 24)
        self.assertEqual({item["hour"] for item in series}, set(range(24)))

    def test_should_report_shares_not_counts_so_they_sum_to_a_hundred(self):
        """A share, not a count: a Corporation always outweighs one character
        in raw numbers, so a count would draw the character's own day as a
        flat line along the bottom."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (2, 5, 9), entries=4)

        series = get_rhythm_detail(RATTER_ID, YEAR, MONTH)["series"]

        total = sum(item["character"] for item in series)
        self.assertAlmostEqual(total, 100, delta=0.1)

    def test_should_report_the_busiest_window_of_the_rest_of_the_corporation(self):
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(8)), entries=8
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8, 16)), entries=5
        )

        window = get_rhythm_detail(RATTER_ID, YEAR, MONTH)["window"]

        self.assertEqual(window, list(range(8)))

    def test_should_leave_the_measured_character_out_of_the_baseline(self):
        """The most important case: Ratter provides most of the volume here.
        Without excluding Ratter's own payouts the combined total would still
        be dominated by them, and the "rest of the Corporation" curve would
        just be Ratter's own curve again - every character would compare
        ordinary against themselves."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(16, 24)), entries=6
        )

        series = {
            item["hour"]: item
            for item in get_rhythm_detail(RATTER_ID, YEAR, MONTH)["series"]
        }

        for hour in range(8):
            with self.subTest(hour=hour):
                self.assertGreater(series[hour]["character"], 0)
                self.assertEqual(series[hour]["corporation"], 0)

        for hour in range(16, 24):
            with self.subTest(hour=hour):
                self.assertEqual(series[hour]["character"], 0)
                self.assertGreater(series[hour]["corporation"], 0)

    def test_should_report_no_share_when_too_little_remains_after_exclusion(self):
        """Below bot_rhythm_corp_min_payouts once Ratter's own payouts come out, the rest
        of the Corporation is not a yardstick - the reading has to say so
        rather than invent a share from a handful of payouts."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (16,), entries=5)

        self.assertIsNone(get_rhythm_detail(RATTER_ID, YEAR, MONTH)["share"])

    def test_should_hand_over_no_corporation_at_all_without_a_yardstick(self):
        """It used to hand back the Character's own day as the Corporation's,
        and the chart drew two lines exactly on top of each other - a picture
        of perfect agreement with something that is not there."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (16,), entries=5)

        series = get_rhythm_detail(RATTER_ID, YEAR, MONTH)["series"]

        self.assertEqual(len(series), 24)
        self.assertTrue(all(point["corporation"] is None for point in series))
        self.assertTrue(any(point["character"] > 0 for point in series))


class TestClockDetail(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        EveName.objects.create(eve_id=CROWD_ID, name="Crowd Pilot", category="character")

    def setUp(self):
        configure()

    def test_should_report_no_series_and_no_middle_for_an_unknown_character(self):
        result = get_clock_detail(999999999, YEAR, MONTH)

        self.assertEqual(result["series"], [])
        self.assertIsNone(result["middle"])

    def test_should_write_the_middles_as_clock_times_not_decimals(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (12,), entries=10)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (12,), entries=40)

        result = get_clock_detail(RATTER_ID, YEAR, MONTH)

        self.assertRegex(result["middle_at"], r"^\d{2}:\d{2}$")
        self.assertRegex(result["corp_middle_at"], r"^\d{2}:\d{2}$")

    def test_should_write_the_distance_as_a_duration_with_units(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (12,), entries=10)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (16,), entries=40)

        result = get_clock_detail(RATTER_ID, YEAR, MONTH)

        self.assertEqual(result["apart"], 4.0)
        self.assertEqual(result["apart_for"], format_duration(4.0))
        self.assertNotEqual(result["apart_for"], "4.0")

    def test_should_average_near_midnight_for_activity_split_across_it(self):
        """The reason the circular mean exists: activity only at 23:00 and
        01:00 has to land near midnight, not near noon as a plain average of
        23 and 1 would give."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (23, 1), entries=5)
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (12,), entries=40)

        middle = get_clock_detail(RATTER_ID, YEAR, MONTH)["middle"]

        # half past midnight: each hour bucket stands for its middle
        self.assertLess(_clock_distance(middle, 0.5), 0.1)
        self.assertGreater(_clock_distance(middle, 12), 5)

    def test_should_exclude_the_measured_character_from_the_corp_baseline(self):
        """Without leaving Ratter out, Ratter's own hours would dominate the
        combined total and pull the baseline toward Ratter's own schedule
        instead of the rest of the Corporation's."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(
            self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, tuple(range(16, 24)), entries=6
        )

        corp_middle = get_clock_detail(RATTER_ID, YEAR, MONTH)["corp_middle"]

        self.assertLess(_clock_distance(corp_middle, 19.5), 1)
        self.assertGreater(_clock_distance(corp_middle, 3.5), 5)

    def test_should_hand_over_no_corporation_at_all_without_a_yardstick(self):
        """The same fault as on the rhythm reading, and worse on a radar
        chart: two identical rings are one ring, so the Character appeared to
        share a clock with a Corporation that had no clock."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (16,), entries=5)

        detail = get_clock_detail(RATTER_ID, YEAR, MONTH)

        self.assertIsNone(detail["middle"])
        self.assertTrue(
            all(point["corporation"] is None for point in detail["series"])
        )
        self.assertTrue(any(point["character"] > 0 for point in detail["series"]))


class TestBotSignalDetailView(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()
        self.client.force_login(
            create_user("boss", 94100020, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def test_should_render_each_signal_as_a_fragment_not_a_full_page(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.client.get(
                    reverse("eos_tax:bot_signal_detail", args=[name, RATTER_ID]),
                    {"month": f"{YEAR}-{MONTH:02d}"},
                )

                self.assertEqual(response.status_code, 200)
                # a fragment, not a full page - the tab injects it with innerHTML
                self.assertNotIn("<html", response.content.decode())

    def test_should_404_for_an_unknown_signal(self):
        response = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["unknown", RATTER_ID])
        )

        self.assertEqual(response.status_code, 404)

    def test_should_redirect_without_admin_view(self):
        self.client.force_login(
            create_user("member", 94100021, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["runs", RATTER_ID])
        )

        self.assertEqual(response.status_code, 302)

    def test_should_reflect_the_selected_month(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        with_data = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["runs", RATTER_ID]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )
        without_data = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["runs", RATTER_ID]),
            {"month": f"{YEAR}-{MONTH + 1:02d}"},
        )

        self.assertContains(with_data, 'data-eos-chart="runs"')
        self.assertNotContains(without_data, 'data-eos-chart="runs"')
        self.assertContains(without_data, "No taxed income in this month.")

    def test_should_carry_a_canvas_and_matching_chart_data_for_each_signal(self):
        """The contract between the fragment and the chart script. Break it
        and the chart stays blank while the server notices nothing - so the
        JSON is parsed, not grepped for a substring."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.client.get(
                    reverse("eos_tax:bot_signal_detail", args=[name, RATTER_ID]),
                    {"month": f"{YEAR}-{MONTH:02d}"},
                )
                body = response.content.decode()

                self.assertContains(response, f'data-eos-chart="{name}"')
                data = json_script(body, "eos-tax-chart-data")
                self.assertIsInstance(data, list)
                self.assertTrue(data)

    def test_should_carry_the_busy_window_only_on_the_rhythm_fragment(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=6)

        response = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["rhythm", RATTER_ID]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )
        body = response.content.decode()

        self.assertIn('id="eos-tax-chart-window"', body)
        self.assertIsInstance(json_script(body, "eos-tax-chart-window"), list)

    def test_should_say_the_corporation_is_too_small_instead_of_a_number(self):
        EveName.objects.create(eve_id=CROWD_ID, name="Crowd Pilot", category="character")
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, tuple(range(8)), entries=10
        )
        add_entries(self.divisions[BRAVO_CORP_ID], CROWD_ID, 1, (16,), entries=5)

        response = self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["rhythm", RATTER_ID]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )

        self.assertContains(response, "no rhythm to compare against and none is drawn")


class TestBotDetailPageTabs(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()
        self.month = f"{YEAR}-{MONTH:02d}"
        self.owner = create_user(
            "boss", 94100030, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )
        self.client.force_login(self.owner)

    def page(self):
        return self.client.get(
            reverse("eos_tax:bot_detail", args=[RATTER_ID]),
            {"month": self.month},
        )

    def build_family(self):
        """Two ratting characters on the reader's own account."""
        for character_id, name in (
            (RATTER_ID, "Busy Ratter"), (CASUAL_ID, "Casual Pilot")
        ):
            create_alt(self.owner, character_id, name)

        for day in (1, 2):
            for character_id in (RATTER_ID, CASUAL_ID):
                add_entries(
                    self.divisions[BRAVO_CORP_ID], character_id, day,
                    (0, 6, 12, 18),
                )

    def test_should_keep_the_matrix_explanation_inside_its_own_tab(self):
        """Above the tab strip it described the matrix to somebody who might
        be looking at any of the other three readings."""
        body = self.page().content.decode()

        hours = body.index('id="eos-tax-tab-hours"')
        runs = body.index('id="eos-tax-tab-runs"')
        text = body.index("An hour counts as active")

        self.assertGreater(text, hours)
        self.assertLess(text, runs)

    def test_should_show_the_characters_age_after_its_name(self):
        """The character page and the character list read the same
        birthday - see TestBotsPage's own test for the list side."""
        EveCharacter.objects.create(
            character_id=RATTER_ID,
            character_name="Busy Ratter",
            corporation_id=BRAVO_CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRAVO",
            birthday=datetime.date(YEAR - 1, MONTH, 1),
        )

        body = self.page().content.decode()

        self.assertIn("Busy Ratter", body)
        self.assertIn("(1 y)", body)

    def test_should_leave_the_name_alone_without_a_known_birthday(self):
        """No EveCharacter row for the character at all here - Alliance Auth
        never had a birthday to show, and an empty pair of parentheses would
        read worse than none."""
        body = self.page().content.decode()

        self.assertIn("Busy Ratter", body)
        # the age span itself, not a bare "()" - the page has other
        # parentheses on it that have nothing to do with this
        self.assertNotIn('fw-normal">(', body)

    def test_should_link_to_zkillboard_and_the_character_audit(self):
        """Two jumps to where eos_tax itself shows nothing: kills and losses,
        and the account and wallet data this whole page is built from."""
        body = self.page().content.decode()

        self.assertIn(f"https://zkillboard.com/character/{RATTER_ID}/", body)
        self.assertIn(
            reverse("corptools:reactmain", args=[RATTER_ID]), body
        )

    def test_should_offer_the_other_characters_of_the_main(self):
        """Handed over by the list the reader clicked through from, because
        working it out here would mean a second walk over the whole month for
        the whole alliance - the cost the tabs were split up to avoid."""
        self.build_family()

        self.client.get(reverse("eos_tax:bots"), {"month": self.month})
        response = self.page()
        family = response.context["family"]

        self.assertIn("dropdown-toggle", response.content.decode())
        self.assertEqual(
            [member["name"] for member in family["characters"]], ["Casual Pilot"]
        )
        # the reading the assessments beside the names came from
        self.assertEqual(str(family["signal"]), "Hours per day")
        self.assertTrue(all(member["level"] for member in family["characters"]))

    def test_should_name_the_reading_the_assessments_came_from(self):
        """The four readings disagree on purpose, so a badge without its
        reading would be a verdict from nowhere."""
        self.build_family()

        self.client.get(
            reverse("eos_tax:bot_signal", args=["runs"]), {"month": self.month}
        )

        self.assertEqual(
            str(self.page().context["family"]["signal"]), "Unbroken runs"
        )

    def test_should_list_only_alts_with_a_taxed_transaction_when_opened_without_a_list(self):
        """Cold - a bookmark, the search box - Alliance Auth still knows who
        belongs together, so the jump list is there. Only the assessments are
        missing, because producing one means reading the whole month for the
        whole alliance, and a jump list without badges beats none.

        The main itself is a candidate too - from an alt it would be the
        useful jump - but build_family() never gives it a payout, so it stays
        out same as any alt would."""
        self.build_family()

        family = self.page().context["family"]

        self.assertEqual(str(family["signal"]), "")
        self.assertEqual(
            [member["name"] for member in family["characters"]], ["Casual Pilot"]
        )
        self.assertTrue(
            all(member["level"] is None for member in family["characters"])
        )

    def test_should_leave_out_an_alt_without_a_taxed_transaction_this_month(self):
        """An account collects characters for a lifetime; most of them never
        near this corporation's income. Casual Pilot only qualifies here
        because build_family() gives it a payout - drop that and the jump
        list should be empty rather than list a name with nothing behind
        it."""
        self.build_family()
        CorporationWalletJournalEntry.objects.filter(
            second_party_id=CASUAL_ID
        ).delete()

        family = self.page().context["family"]

        self.assertIsNone(family)

    def test_should_show_no_dropdown_for_a_character_alliance_auth_knows_nothing_of(self):
        """The journal names characters nobody ever registered. Without an
        ownership there is no account, so there is nothing to list."""
        self.build_family()

        response = self.client.get(
            reverse("eos_tax:bot_detail", args=[CROWD_ID]),
            {"month": self.month},
        )

        self.assertIsNone(response.context["family"])
        self.assertNotIn("dropdown-toggle", response.content.decode())

    def test_should_ignore_a_grouping_from_another_month(self):
        """A stale grouping beside a fresh month would be worse than none,
        because it would look current - so the month falls back to the plain
        list of alts rather than keeping September's assessments.

        A payout of its own in January, on top of build_family()'s May ones,
        keeps the cold fallback from returning empty here for an unrelated
        reason - this is about the stale signal, not about January having
        nothing to show."""
        self.build_family()
        self.client.get(reverse("eos_tax:bots"), {"month": self.month})
        CorporationWalletJournalEntry.objects.create(
            division=self.divisions[BRAVO_CORP_ID],
            date=datetime.datetime(2026, 1, 15, 12, tzinfo=datetime.timezone.utc),
            description="got bounty prizes for killing pirates",
            entry_id=next(entry_ids),
            ref_type="bounty_prizes",
            first_party_id=1000125,
            second_party_id=CASUAL_ID,
            second_party_name_id=CASUAL_ID,
            tax_receiver_id=BRAVO_CORP_ID,
            amount=1000,
            tax=1000,
        )

        other = self.client.get(
            reverse("eos_tax:bot_detail", args=[RATTER_ID]),
            {"month": "2026-01"},
        )

        self.assertEqual(str(other.context["family"]["signal"]), "")
        self.assertEqual(
            [member["name"] for member in other.context["family"]["characters"]],
            ["Casual Pilot"],
        )

    def test_should_mark_the_jump_links_to_be_kept_on_the_open_tab(self):
        """Comparing one reading across a main was two clicks per character:
        the jump landed on the matrix every time, and the second click was
        easy to forget."""
        self.build_family()
        self.client.get(reverse("eos_tax:bots"), {"month": self.month})

        body = self.page().content.decode()
        # the attribute itself, not the month form's data-eos-keep-tab-field
        marked = len(re.findall(r"data-eos-keep-tab(?![-\w])", body))

        # one alt in the dropdown, plus the way back to the list
        self.assertEqual(marked, 2)

    def test_should_carry_the_script_that_keeps_the_tab(self):
        """Rewritten on each tab change rather than when a link is clicked: a
        middle click never fires a click handler, and a link whose behaviour
        depends on one is a link that lies."""
        script = read_static("bots.js")

        self.assertIn("function eosTaxKeepTab", script)
        self.assertIn("data-eos-keep-tab", script)
        self.assertIn('searchParams.set("tab"', script)
        # and the other half: a page asked for a tab opens it
        self.assertIn("eosTaxOpenRequestedTab()", script)
        self.assertIn("bootstrap.Tab.getOrCreateInstance", script)

    def test_should_keep_links_that_were_not_there_when_the_tab_opened(self):
        """Two cases the shown.bs.tab listener alone cannot reach: a list
        fetched into a pane after that event, and the tab that is already open
        when the page loads, for which the event never fires at all."""
        script = read_static("bots.js")
        landed = script.split("pane.innerHTML = html;", 1)[1]

        self.assertIn("eosTaxKeepTab(eosTaxTabName(pane))", landed)
        self.assertIn(".tab-pane.active[id^='eos-tax-tab-']", script)

    def test_should_carry_all_four_tab_targets(self):
        response = self.page()

        for target in ("hours", "runs", "rhythm", "clock"):
            with self.subTest(target=target):
                self.assertContains(response, f'id="eos-tax-tab-{target}"')

    def test_should_give_each_signal_tab_a_url_for_the_displayed_month(self):
        """Parsed as JSON, not grepped as a substring - a URL that merely
        mentions the right characters somewhere is not the same as a tab
        that loads the month shown on screen."""
        response = self.page()
        config = json_script(response.content.decode(), "eos-tax-config")

        month = f"{YEAR}-{MONTH:02d}"
        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                expected = (
                    reverse("eos_tax:bot_signal_detail", args=[name, RATTER_ID])
                    + f"?month={month}"
                )
                self.assertEqual(config["signals"][name], expected)

    def test_should_still_render_the_hours_matrix_as_the_first_tab(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 6, 12))

        response = self.page()

        self.assertContains(response, 'id="eos-tax-tab-hours"')
        self.assertNotContains(
            response, "This character had no active hour in the selected month."
        )
