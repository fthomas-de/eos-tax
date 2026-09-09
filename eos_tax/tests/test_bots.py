import itertools
from datetime import datetime, timezone

from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

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

from eos_tax.db_connector import get_bot_candidates, get_bot_report
from eos_tax.models import TaxConfiguration

from .test_views import create_user

ALLIANCE_ID = 99000001
OTHER_ALLIANCE_ID = 99000002
CORP_ID = 98000001
OUTSIDE_CORP_ID = 98000003

RATTER_ID = 2100000001
CASUAL_ID = 2100000002

YEAR = 2026
MONTH = 5

# small thresholds keep the fixtures readable: more than 2 hours on more than 1 day
MIN_HOURS = 2
MIN_DAYS = 1

entry_ids = itertools.count(1)


def configure():
    config = TaxConfiguration.get_solo()
    config.tax_types = ["bounty_prizes"]
    config.bot_min_hours_per_day = MIN_HOURS
    config.bot_min_days_per_month = MIN_DAYS
    config.save()
    config.tax_alliances.set(
        EveAllianceInfo.objects.filter(alliance_id=ALLIANCE_ID)
    )

    return config


def build_corporations():
    taxed = EveAllianceInfo.objects.create(
        alliance_id=ALLIANCE_ID, alliance_name="Taxed Alliance", alliance_ticker="TAX"
    )
    other = EveAllianceInfo.objects.create(
        alliance_id=OTHER_ALLIANCE_ID, alliance_name="Other Alliance", alliance_ticker="OTH"
    )

    divisions = {}
    for corp_id, name, alliance in (
        (CORP_ID, "Bravo Corp", taxed),
        (OUTSIDE_CORP_ID, "Outsider Corp", other),
    ):
        corporation = EveCorporationInfo.objects.create(
            corporation_id=corp_id,
            corporation_name=name,
            corporation_ticker=name[:5].upper(),
            alliance=alliance,
            tax_rate=0.1,
        )
        audit = CorporationAudit.objects.create(corporation=corporation)
        divisions[corp_id] = CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

    EveName.objects.create(eve_id=RATTER_ID, name="Busy Ratter", category="character")
    EveName.objects.create(eve_id=CASUAL_ID, name="Casual Pilot", category="character")

    return divisions


def add_entries(division, character_id, day, hours, ref_type="bounty_prizes", corp_id=CORP_ID, tax=1000):
    """One taxed journal entry per given hour of the day, in EVE time."""
    for hour in hours:
        CorporationWalletJournalEntry.objects.create(
            division=division,
            date=datetime(YEAR, MONTH, day, hour, 30, tzinfo=timezone.utc),
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


class TestBotDetection(EosTaxTestCase):
    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def candidates(self):
        return get_bot_candidates(YEAR, MONTH)

    def make_bot(self, character_id=RATTER_ID, days=(1, 2), hours=(0, 6, 12, 18)):
        for day in days:
            add_entries(self.divisions[CORP_ID], character_id, day, hours)

    def test_should_list_a_character_above_both_thresholds(self):
        self.make_bot()

        names = [entry["character_name"] for entry in self.candidates()]

        self.assertEqual(names, ["Busy Ratter"])

    def test_should_ignore_a_character_with_too_few_hours(self):
        # two hours a day is not "more than 2"
        self.make_bot(hours=(3, 15))

        self.assertEqual(self.candidates(), [])

    def test_should_ignore_a_character_with_too_few_days(self):
        # one suspicious day is not "more than 1"
        self.make_bot(days=(4,))

        self.assertEqual(self.candidates(), [])

    def test_should_count_each_hour_only_once(self):
        """Twenty entries inside one hour are still one hour of activity."""
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, [7] * 20)

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
                self.divisions[OUTSIDE_CORP_ID],
                RATTER_ID,
                day,
                (0, 6, 12, 18),
                corp_id=OUTSIDE_CORP_ID,
            )

        self.assertEqual(self.candidates(), [])

    def test_should_report_the_counted_figures(self):
        self.make_bot(days=(1, 2, 3), hours=(0, 6, 12, 18))
        add_entries(self.divisions[CORP_ID], RATTER_ID, 9, (5,))  # one quiet day

        entry = self.candidates()[0]

        self.assertEqual(entry["suspicious_days"], 3)
        self.assertEqual(entry["active_days"], 4)
        self.assertEqual(entry["max_hours"], 4)
        self.assertEqual(entry["contributed"], 13 * 1000)

    def test_should_keep_characters_apart(self):
        self.make_bot()
        self.make_bot(character_id=CASUAL_ID, days=(1,), hours=(8,))

        names = [entry["character_name"] for entry in self.candidates()]

        self.assertEqual(names, ["Busy Ratter"])

    def test_should_look_at_the_selected_month_only(self):
        self.make_bot()

        self.assertEqual(get_bot_candidates(YEAR, MONTH + 1), [])

    def test_should_return_nothing_without_configured_alliances(self):
        self.make_bot()
        TaxConfiguration.get_solo().tax_alliances.clear()

        self.assertEqual(self.candidates(), [])


class TestBotRuntimeStats(EosTaxTestCase):
    """The page shows what the run cost, so growth is visible before it hurts."""

    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def test_should_count_what_the_run_walked(self):
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        add_entries(self.divisions[CORP_ID], CASUAL_ID, 1, (9,))

        stats = get_bot_report(YEAR, MONTH)["stats"]

        self.assertEqual(stats["buckets"], 9)  # two days times four hours, plus one
        self.assertEqual(stats["characters"], 2)
        self.assertEqual(stats["candidates"], 1)

    def test_should_not_count_repeated_entries_as_extra_blocks(self):
        """Hour blocks are the figure to watch, so they must not track raw rows."""
        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, [7] * 30)

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

    def test_should_agree_with_the_plain_helper(self):
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        self.assertEqual(
            get_bot_candidates(YEAR, MONTH), get_bot_report(YEAR, MONTH)["candidates"]
        )


class TestLongestDaysFallback(EosTaxTestCase):
    """An empty page says nothing about whether the thresholds fit."""

    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def report(self):
        return get_bot_report(YEAR, MONTH)

    def test_should_stay_empty_without_any_activity(self):
        report = self.report()

        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["longest_days"], [])

    def test_should_list_the_longest_days_when_nothing_qualifies(self):
        # one hour a day never crosses the two hour threshold
        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, (5, 6, 7))
        add_entries(self.divisions[CORP_ID], CASUAL_ID, 1, (9,))

        report = self.report()

        self.assertEqual(report["candidates"], [])
        self.assertEqual(
            [entry["character_name"] for entry in report["longest_days"]],
            ["Busy Ratter", "Casual Pilot"],
        )

    def test_should_rank_by_the_longest_day(self):
        add_entries(self.divisions[CORP_ID], CASUAL_ID, 1, (1, 2))
        add_entries(self.divisions[CORP_ID], RATTER_ID, 2, (1, 2, 3, 4))

        longest = self.report()["longest_days"]

        self.assertEqual(longest[0]["character_name"], "Busy Ratter")
        self.assertEqual(longest[0]["max_hours"], 4)

    def test_should_cap_the_fallback_at_ten(self):
        for index in range(14):
            character_id = 2100001000 + index
            EveName.objects.create(
                eve_id=character_id, name=f"Pilot {index}", category="character"
            )
            add_entries(self.divisions[CORP_ID], character_id, 1, (index % 12,))

        self.assertEqual(len(self.report()["longest_days"]), 10)

    def test_should_drop_the_fallback_once_something_qualifies(self):
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        add_entries(self.divisions[CORP_ID], CASUAL_ID, 1, (9,))

        report = self.report()

        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["longest_days"], [])


class TestMainCharacter(EosTaxTestCase):
    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def test_should_name_the_main_behind_a_candidate(self):
        """The ratting character is an alt; the report has to name its main."""
        owner = create_user("boss", 91999001, CORP_ID, "Bravo Corp", ["admin_view"])
        main = owner.profile.main_character
        main.character_name = "The Main"
        main.save()

        alt = EveCharacter.objects.create(
            character_id=RATTER_ID,
            character_name="Busy Ratter",
            corporation_id=CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRVO",
        )
        CharacterOwnership.objects.create(
            character=alt, user=owner, owner_hash="alt-owner-hash"
        )

        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        candidate = get_bot_report(YEAR, MONTH)["candidates"][0]

        self.assertEqual(candidate["character_name"], "Busy Ratter")
        self.assertEqual(candidate["main_name"], "The Main")

    def test_should_leave_the_main_empty_for_an_unknown_character(self):
        """Journal entries can name characters Alliance Auth has never seen."""
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        candidate = get_bot_report(YEAR, MONTH)["candidates"][0]

        self.assertEqual(candidate["main_name"], "")


class TestBotsPage(EosTaxTestCase):
    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def test_should_reject_basic_access(self):
        self.client.force_login(
            create_user("member", 94000001, CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertEqual(response.status_code, 302)

    def test_should_render_for_admin_view(self):
        self.client.force_login(
            create_user("boss", 94000002, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No character crossed both thresholds")

    def test_should_list_a_candidate_for_the_selected_month(self):
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        self.client.force_login(
            create_user("boss", 94000003, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(response, "Busy Ratter")

    def test_should_show_the_fallback_when_nothing_qualifies(self):
        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, (5, 6, 7))
        self.client.force_login(
            create_user("boss", 94000007, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(response, "The ten longest days of the month")
        self.assertContains(response, "Busy Ratter")
        self.assertContains(response, "Main")

    def test_should_show_the_runtime_panel(self):
        self.client.force_login(
            create_user("boss", 94000005, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertContains(response, "hour blocks")
        self.assertContains(response, "characters")
        self.assertContains(response, "aggregation")

    def test_should_not_leak_template_comments(self):
        """A multi line {# #} is not a comment in Django - it renders as text."""
        self.client.force_login(
            create_user("boss", 94000006, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"))

        self.assertNotContains(response, "Hour blocks are what the database")
        self.assertNotContains(response, "{#")

    def test_should_fall_back_to_the_running_month_on_junk_input(self):
        self.client.force_login(
            create_user("boss", 94000004, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:bots"), {"month": "nonsense"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, datetime.now().strftime("%Y-%m"))
