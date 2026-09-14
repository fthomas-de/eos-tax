from datetime import datetime
from unittest import mock

from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from corptools.models import CorporationAudit, CorporationWalletDivision, EveName

from eos_tax.db.bots import get_bot_report
from eos_tax.db.shared import GROUP_LIMIT
from eos_tax.models import TaxConfiguration

from .factories import (
    ACTIVE_HOUR_MIN_ENTRIES,
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    OUTSIDER_CORP_ID,
    RATTER_ID,
    TAXED_ALLIANCE_ID,
    YEAR,
    add_entries,
    build_corporations,
    configure,
    create_alt,
    create_user,
)


class TestBotDetection(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        # a test mutates the configuration (tax_types/tax_alliances), so it
        # is rebuilt fresh every time rather than shared via setUpTestData
        configure()

    def candidates(self):
        return get_bot_report(YEAR, MONTH)["candidates"]

    def make_bot(self, character_id=RATTER_ID, days=(1, 2), hours=(0, 6, 12, 18)):
        for day in days:
            add_entries(self.divisions[BRAVO_CORP_ID], character_id, day, hours)

    def test_should_ignore_a_character_with_too_few_hours(self):
        # two hours a day is not "more than 2"
        self.make_bot(hours=(3, 15))

        self.assertEqual(self.candidates(), [])

    def test_should_ignore_a_character_with_too_few_days(self):
        # one suspicious day is not "more than 1"
        self.make_bot(days=(4,))

        self.assertEqual(self.candidates(), [])

    def test_should_count_each_hour_only_once(self):
        """Repeated entries inside one hour are still one hour of activity.

        add_entries writes ACTIVE_HOUR_MIN_ENTRIES rows per slot, so four
        slots on the same hour are eight rows - enough to show the collapse
        without filling the journal to prove it twice over.
        """
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, [7] * 4)

        self.assertEqual(self.candidates(), [])

    def test_should_only_count_configured_journal_types(self):
        self.make_bot(hours=(1, 2, 3, 4))
        config = TaxConfiguration.get_solo()
        config.tax_types = ["agent_mission_reward"]
        config.save()

        self.assertEqual(self.candidates(), [])

    def test_should_ignore_corporations_outside_the_taxed_alliances(self):
        for day in (1, 2):
            add_entries(
                self.divisions[OUTSIDER_CORP_ID],
                RATTER_ID,
                day,
                (0, 6, 12, 18),
                corp_id=OUTSIDER_CORP_ID,
            )

        self.assertEqual(self.candidates(), [])

    def test_should_report_the_counted_figures(self):
        self.make_bot(days=(1, 2, 3), hours=(0, 6, 12, 18))
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 9, (5,))  # one quiet day

        entry = self.candidates()[0]

        self.assertEqual(entry["suspicious_days"], 3)
        self.assertEqual(entry["active_days"], 4)
        self.assertEqual(entry["max_hours"], 4)
        # 13 active hours, each carrying the entries an active hour needs
        self.assertEqual(
            entry["contributed"], 13 * ACTIVE_HOUR_MIN_ENTRIES * 1000
        )

    def test_should_keep_characters_apart(self):
        """Also the plain positive case: a character over both thresholds is
        listed, and one under them is not."""
        self.make_bot()
        self.make_bot(character_id=CASUAL_ID, days=(1,), hours=(8,))

        names = [entry["character_name"] for entry in self.candidates()]

        self.assertEqual(names, ["Busy Ratter"])

    def test_should_look_at_the_selected_month_only(self):
        self.make_bot()

        self.assertEqual(
            get_bot_report(YEAR, MONTH + 1)["candidates"], []
        )

    def test_should_return_nothing_without_configured_alliances(self):
        self.make_bot()
        TaxConfiguration.get_solo().tax_alliances.clear()

        self.assertEqual(self.candidates(), [])


class TestBotRuntimeStats(EosTaxTestCase):
    """The page shows what the run cost, so growth is visible before it hurts."""

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        # a test clears tax_alliances, so the configuration stays per test
        configure()

    def test_should_count_what_the_run_walked(self):
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (9,))

        stats = get_bot_report(YEAR, MONTH)["stats"]

        self.assertEqual(stats["buckets"], 9)  # two days times four hours, plus one
        self.assertEqual(stats["characters"], 2)
        self.assertEqual(stats["candidates"], 1)

    def test_should_not_count_repeated_entries_as_extra_blocks(self):
        """Hour blocks are the figure to watch, so they must not track raw rows."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, [7] * 4)

        self.assertEqual(get_bot_report(YEAR, MONTH)["stats"]["buckets"], 1)

    def test_should_time_every_phase(self):
        stats = get_bot_report(YEAR, MONTH)["stats"]

        for key in ("seconds_query", "seconds_aggregate", "seconds_total"):
            with self.subTest(key=key):
                self.assertGreaterEqual(stats[key], 0)

        self.assertGreaterEqual(stats["seconds_total"], stats["seconds_query"])

    def test_should_report_zeroes_without_configured_alliances(self):
        TaxConfiguration.get_solo().tax_alliances.clear()

        stats = get_bot_report(YEAR, MONTH)["stats"]

        self.assertEqual(stats["buckets"], 0)
        self.assertEqual(stats["candidates"], 0)


class TestLongestDaysFallback(EosTaxTestCase):
    """An empty page says nothing about whether the thresholds fit."""

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def report(self):
        return get_bot_report(YEAR, MONTH)

    def test_should_stay_empty_without_any_activity(self):
        report = self.report()

        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["longest_days"], [])

    def test_should_list_the_longest_days_when_nothing_qualifies(self):
        # one hour a day never crosses the two hour threshold
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (5, 6, 7))
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (9,))

        report = self.report()

        self.assertEqual(report["candidates"], [])
        self.assertEqual(
            [entry["character_name"] for entry in report["longest_days"]],
            ["Busy Ratter", "Casual Pilot"],
        )

    def test_should_rank_by_the_longest_day(self):
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (1, 2))
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 2, (1, 2, 3, 4))

        longest = self.report()["longest_days"]

        self.assertEqual(longest[0]["character_name"], "Busy Ratter")
        self.assertEqual(longest[0]["max_hours"], 4)

    def test_should_cap_the_fallback_at_the_limit(self):
        """One over the cap is what shows a cap; four over only costs rows.

        Every character here is its own main - Alliance Auth was never told
        about any of them - so a row and a group are the same thing and this
        does not yet tell the row cap from the group cap apart. The next test
        does."""
        for index in range(GROUP_LIMIT + 1):
            character_id = 2100001000 + index
            EveName.objects.create(
                eve_id=character_id, name=f"Pilot {index}", category="character"
            )
            add_entries(self.divisions[BRAVO_CORP_ID], character_id, 1, (index % 12,))

        self.assertEqual(
            self.report()["groups_total"], GROUP_LIMIT
        )

    def test_should_show_ten_mains_even_when_two_of_the_top_rows_share_one(self):
        """Slicing the fallback to ten rows before grouping used to cost a
        main its whole listing: two alts of the same account filled two of
        those ten slots, and the eleventh row - a main of its own - never
        reached the grouping step to be counted. Grouping first and cutting
        the groups instead means all ten distinct mains show up, main pair
        included."""
        owner = create_user(
            "topalt", 94100050, BRAVO_CORP_ID, "Bravo Corp"
        )
        EveName.objects.create(
            eve_id=94100050, name="topalt character", category="character"
        )
        create_alt(owner, RATTER_ID, "Busy Ratter")
        # ranked first and second: six active hours each, well above the
        # one hour singles below
        for character_id in (94100050, RATTER_ID):
            add_entries(self.divisions[BRAVO_CORP_ID], character_id, 1, range(6))

        # nine more mains of their own, ranked third through eleventh
        for index in range(9):
            character_id = 2100001000 + index
            EveName.objects.create(
                eve_id=character_id, name=f"Pilot {index}", category="character"
            )
            add_entries(self.divisions[BRAVO_CORP_ID], character_id, 1, (index % 12,))

        report = self.report()

        # one main for the pair, nine for the singles - ten in reach, and the
        # cap does not cost the account its own second slot in exchange
        self.assertEqual(report["groups_total"], GROUP_LIMIT)
        self.assertEqual(len(report["groups"]), GROUP_LIMIT)

    def test_should_drop_the_fallback_once_something_qualifies(self):
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (9,))

        report = self.report()

        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["longest_days"], [])


class TestTaxReceivingCorporation(EosTaxTestCase):
    """Which Corporation the character earned for.

    Taken from the journal, not from the character's Alliance Auth record:
    almost no ratter is registered there, so that column would sit empty the
    way the Main one does.
    """

    SECOND_CORP_ID = 98000004

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def second_taxed_corporation(self):
        """Another Corporation in the taxed alliance, for a mid month move."""
        corporation = EveCorporationInfo.objects.create(
            corporation_id=self.SECOND_CORP_ID,
            corporation_name="Delta Corp",
            corporation_ticker="DELTA",
            alliance=EveAllianceInfo.objects.get(alliance_id=TAXED_ALLIANCE_ID),
            tax_rate=0.1,
        )
        audit = CorporationAudit.objects.create(corporation=corporation)

        return CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

    def first_candidate(self):
        return get_bot_report(YEAR, MONTH)["candidates"][0]

    def test_should_name_the_corporation_that_received_the_tax(self):
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        self.assertEqual(self.first_candidate()["corporation_name"], "Bravo Corp")

    def test_should_pick_the_corporation_that_got_the_most(self):
        """A character that moved mid month is named under where it earned."""
        second = self.second_taxed_corporation()
        for day in (1, 2):
            add_entries(
                self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18), tax=10
            )
        for day in (3, 4):
            add_entries(
                second, RATTER_ID, day, (0, 6, 12, 18),
                corp_id=self.SECOND_CORP_ID, tax=1000,
            )

        self.assertEqual(self.first_candidate()["corporation_name"], "Delta Corp")

    def test_should_name_the_corporation_in_the_fallback_list(self):
        """The ten longest days carry the column too."""
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 1, (0, 6))

        report = get_bot_report(YEAR, MONTH)

        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["longest_days"][0]["corporation_name"], "Bravo Corp")


class TestActiveHourRule(EosTaxTestCase):
    """An hour needs the same taxed journal type in it twice.

    One entry used to be enough, which let a single stray bounty tick stand for
    an hour of ratting.
    """

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        # a test overrides tax_types, so the configuration stays per test
        configure()

    def hours_on_day(self, day=1):
        report = get_bot_report(YEAR, MONTH)
        rows = report["candidates"] or report["longest_days"]

        return rows[0]["max_hours"] if rows else 0

    def test_should_ignore_an_hour_with_a_single_entry(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 6, 12), entries=1)

        self.assertEqual(get_bot_report(YEAR, MONTH)["longest_days"], [])

    def test_should_count_an_hour_that_reaches_the_threshold(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,))

        self.assertEqual(self.hours_on_day(), 1)

    def test_should_not_mix_two_different_types_into_one_hour(self):
        """Two taxed entries, but not two of the same - the hour stays quiet."""
        config = TaxConfiguration.get_solo()
        config.tax_types = ["bounty_prizes", "ess_escrow_transfer"]
        config.save()

        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,), entries=1)
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0,),
            ref_type="ess_escrow_transfer", entries=1,
        )

        self.assertEqual(get_bot_report(YEAR, MONTH)["longest_days"], [])

    def test_should_read_the_active_hour_rule_from_the_configuration(self):
        """One entry in an hour is noise at the shipped rule and a full hour
        of activity at a rule of one. The same journal, a different day - and
        the number deciding it was the one threshold of this tab that could
        not be seen or changed anywhere."""
        add_entries(
            self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (0, 6, 12), entries=1
        )

        self.assertEqual(self.hours_on_day(), 0)

        config = TaxConfiguration.get_solo()
        config.bot_hours_min_entries = 1
        config.save()

        self.assertEqual(self.hours_on_day(), 3)


class TestBotsPage(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def test_should_reject_basic_access(self):
        self.client.force_login(
            create_user("member", 94000001, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertEqual(response.status_code, 302)

    def test_should_render_for_admin_view(self):
        self.client.force_login(
            create_user("boss", 94000002, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No character crossed both thresholds")

    def test_should_list_a_candidate_for_the_selected_month(self):
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        self.client.force_login(
            create_user("boss", 94000003, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(response, "Busy Ratter")

    def test_should_show_the_fallback_when_nothing_qualifies(self):
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, 1, (5, 6, 7))
        self.client.force_login(
            create_user("boss", 94000007, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(response, "The ten mains with the longest days")
        self.assertContains(response, "Busy Ratter")
        # not the bare word: Alliance Auth's own menu says "Change Main" on
        # every page, so that would pass with no table at all
        self.assertContains(
            response, 'class="d-none d-md-table-cell">Main</th>'
        )

    def test_should_show_the_runtime_panel(self):
        self.client.force_login(
            create_user("boss", 94000005, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertContains(response, "hour blocks")
        self.assertContains(response, "characters")
        self.assertContains(response, "aggregation")

    def test_should_not_leak_template_comments(self):
        """A multi line {# #} is not a comment in Django - it renders as text."""
        self.client.force_login(
            create_user("boss", 94000006, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertNotContains(response, "Hour blocks are what the database")
        self.assertNotContains(response, "{#")

    def test_should_fall_back_to_the_running_month_on_junk_input(self):
        self.client.force_login(
            create_user("boss", 94000004, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"), {"month": "nonsense"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, datetime.now().strftime("%Y-%m"))


class TestSlowRuntimeIsSaidInWords(EosTaxTestCase):
    """A colour nobody has a baseline for is not a message.

    The runtime line used to turn amber and nothing else. A reader seeing the
    page for the first time has never seen the ordinary colour, so there is
    nothing to compare against - and on the light themes amber on white reads
    worse than the ordinary colour it is meant to stand out from.
    """

    @classmethod
    def setUpTestData(cls):
        build_corporations()
        configure()
        cls.user = create_user(
            "boss", 94000009, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )

    def setUp(self):
        # self.client is rebuilt per test, so the login has to be too
        self.client.force_login(self.user)

    def page(self):
        return self.client.get(reverse("eos_tax:bots"))

    def test_should_leave_the_line_in_the_ordinary_colour(self):
        self.assertContains(self.page(), "border-top text-body-secondary")

    def test_should_say_nothing_while_the_run_is_quick(self):
        self.assertNotContains(self.page(), "slower than usual")

    def test_should_say_it_in_words_once_the_run_is_slow(self):
        report = get_bot_report(YEAR, MONTH)
        report["stats"]["seconds_total"] = 3.0

        with mock.patch("eos_tax.views.get_bot_report", return_value=report):
            response = self.page()

        self.assertContains(response, "slower than usual")
