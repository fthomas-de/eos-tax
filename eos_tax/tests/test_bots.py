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

from eos_tax.db_connector import (
    ACTIVE_HOUR_MIN_ENTRIES,
    find_characters,
    get_bot_candidates,
    get_bot_report,
    get_character_month,
)
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


def add_entries(
    division,
    character_id,
    day,
    hours,
    ref_type="bounty_prizes",
    corp_id=CORP_ID,
    tax=1000,
    entries=ACTIVE_HOUR_MIN_ENTRIES,
):
    """Taxed journal entries in the given hours of the day, in EVE time.

    Enough entries per hour to make it active, because that is what a test
    saying "these hours" means. Pass entries=1 to write a lone one.
    """
    for hour in hours:
        for minute in range(entries):
            CorporationWalletJournalEntry.objects.create(
                division=division,
                # spread within the hour, so the entries are distinguishable
                date=datetime(YEAR, MONTH, day, hour, minute, tzinfo=timezone.utc),
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
        # 13 active hours, each carrying the entries an active hour needs
        self.assertEqual(
            entry["contributed"], 13 * ACTIVE_HOUR_MIN_ENTRIES * 1000
        )

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


class TestTaxReceivingCorporation(EosTaxTestCase):
    """Which Corporation the character earned for.

    Taken from the journal, not from the character's Alliance Auth record:
    almost no ratter is registered there, so that column would sit empty the
    way the Main one does.
    """

    SECOND_CORP_ID = 98000004

    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def second_taxed_corporation(self):
        """Another Corporation in the taxed alliance, for a mid month move."""
        corporation = EveCorporationInfo.objects.create(
            corporation_id=self.SECOND_CORP_ID,
            corporation_name="Delta Corp",
            corporation_ticker="DELTA",
            alliance=EveAllianceInfo.objects.get(alliance_id=ALLIANCE_ID),
            tax_rate=0.1,
        )
        audit = CorporationAudit.objects.create(corporation=corporation)

        return CorporationWalletDivision.objects.create(
            corporation=audit, balance=0, division=1
        )

    def first_candidate(self):
        return get_bot_candidates(YEAR, MONTH)[0]

    def test_should_name_the_corporation_that_received_the_tax(self):
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        self.assertEqual(self.first_candidate()["corporation_name"], "Bravo Corp")

    def test_should_pick_the_corporation_that_got_the_most(self):
        """A character that moved mid month is named under where it earned."""
        second = self.second_taxed_corporation()
        for day in (1, 2):
            add_entries(self.divisions[CORP_ID], RATTER_ID, day, (0, 6, 12, 18), tax=10)
        for day in (3, 4):
            add_entries(
                second, RATTER_ID, day, (0, 6, 12, 18),
                corp_id=self.SECOND_CORP_ID, tax=1000,
            )

        self.assertEqual(self.first_candidate()["corporation_name"], "Delta Corp")

    def test_should_name_the_corporation_in_the_fallback_list(self):
        """The ten longest days carry the column too."""
        add_entries(self.divisions[CORP_ID], CASUAL_ID, 1, (0, 6))

        report = get_bot_report(YEAR, MONTH)

        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["longest_days"][0]["corporation_name"], "Bravo Corp")


class TestActiveHourRule(EosTaxTestCase):
    """An hour needs the same taxed journal type in it twice.

    One entry used to be enough, which let a single stray bounty tick stand for
    an hour of ratting.
    """

    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def hours_on_day(self, day=1):
        report = get_bot_report(YEAR, MONTH)
        rows = report["candidates"] or report["longest_days"]

        return rows[0]["max_hours"] if rows else 0

    def test_should_ignore_an_hour_with_a_single_entry(self):
        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, (0, 6, 12), entries=1)

        self.assertEqual(get_bot_report(YEAR, MONTH)["longest_days"], [])

    def test_should_count_an_hour_that_reaches_the_threshold(self):
        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, (0,))

        self.assertEqual(self.hours_on_day(), 1)

    def test_should_not_mix_two_different_types_into_one_hour(self):
        """Two taxed entries, but not two of the same - the hour stays quiet."""
        config = TaxConfiguration.get_solo()
        config.tax_types = ["bounty_prizes", "ess_escrow_transfer"]
        config.save()

        add_entries(self.divisions[CORP_ID], RATTER_ID, 1, (0,), entries=1)
        add_entries(
            self.divisions[CORP_ID], RATTER_ID, 1, (0,),
            ref_type="ess_escrow_transfer", entries=1,
        )

        self.assertEqual(get_bot_report(YEAR, MONTH)["longest_days"], [])


class TestCharacterMonth(EosTaxTestCase):
    """The detail matrix: calendar weeks as rows, weekdays as columns."""

    def setUp(self):
        self.divisions = build_corporations()
        configure()

    def active(self, day, hours):
        """Make each of these hours active on that day."""
        add_entries(self.divisions[CORP_ID], RATTER_ID, day, hours)

    def detail(self):
        return get_character_month(RATTER_ID, YEAR, MONTH)

    def cell(self, detail, day):
        for week in detail["weeks"]:
            for entry in week["days"]:
                if entry["in_month"] and entry["day"] == day:
                    return entry

        raise AssertionError(f"day {day} not in the matrix")

    def test_should_start_every_row_on_a_monday(self):
        for week in self.detail()["weeks"]:
            self.assertEqual(week["days"][0]["date"].weekday(), 0)
            self.assertEqual(len(week["days"]), 7)

    def test_should_carry_the_neighbouring_days_as_placeholders(self):
        """Dropping them would shift the weekday columns."""
        detail = self.detail()
        outside = [
            day
            for week in detail["weeks"]
            for day in week["days"]
            if not day["in_month"]
        ]

        self.assertTrue(outside)
        for day in outside:
            self.assertEqual(day["hours"], 0)

    def test_should_hold_every_day_of_the_month(self):
        detail = self.detail()
        in_month = [
            day["day"]
            for week in detail["weeks"]
            for day in week["days"]
            if day["in_month"]
        ]

        self.assertEqual(in_month, list(range(1, 32)))

    def test_should_count_the_active_hours_of_a_day(self):
        self.active(3, (0, 6, 12))

        self.assertEqual(self.cell(self.detail(), 3)["hours"], 3)

    def test_should_name_the_hours_for_the_tooltip(self):
        self.active(4, (7, 22))

        self.assertEqual(self.cell(self.detail(), 4)["hour_list"], "07, 22")

    def test_should_leave_a_quiet_day_uncoloured(self):
        self.active(5, (0, 6))

        self.assertEqual(self.cell(self.detail(), 6)["alpha"], 0)

    def test_should_paint_the_busiest_day_darkest(self):
        self.active(5, (0, 6, 12, 18))
        self.active(6, (0,))

        detail = self.detail()

        self.assertGreater(self.cell(detail, 5)["alpha"], self.cell(detail, 6)["alpha"])

    def test_should_summarise_the_month(self):
        self.active(5, (0, 6, 12))
        self.active(6, (3,))

        detail = self.detail()

        self.assertEqual(detail["active_days"], 2)
        self.assertEqual(detail["active_hours"], 4)
        self.assertEqual(detail["busiest"], 3)

    def test_should_step_the_legend_like_the_cells(self):
        self.active(5, (0, 6))

        legend = self.detail()["legend"]

        self.assertEqual(len(legend), 5)
        self.assertEqual(legend, sorted(legend, key=lambda step: step["alpha"]))

    def test_should_name_the_character(self):
        self.assertEqual(self.detail()["character_name"], "Busy Ratter")

    def test_should_stay_empty_for_another_month(self):
        self.active(5, (0, 6, 12))

        other = get_character_month(RATTER_ID, YEAR, MONTH + 1)

        self.assertEqual(other["active_days"], 0)
        self.assertEqual(other["busiest"], 0)

    def test_should_ignore_corporations_outside_the_taxed_alliances(self):
        add_entries(
            self.divisions[OUTSIDE_CORP_ID], RATTER_ID, 5, (0, 6),
            corp_id=OUTSIDE_CORP_ID,
        )

        self.assertEqual(self.detail()["active_days"], 0)


class TestCharacterDetailPage(EosTaxTestCase):
    def setUp(self):
        self.divisions = build_corporations()
        configure()
        add_entries(self.divisions[CORP_ID], RATTER_ID, 3, (0, 6, 12))

    def detail_page(self, user_permissions=("admin_view",)):
        user = create_user(
            "detail", 94000010, CORP_ID, "Bravo Corp", list(user_permissions)
        )
        self.client.force_login(user)

        return self.client.get(
            reverse("eos_tax:bot_detail", args=[RATTER_ID]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )

    def test_should_reject_basic_access(self):
        response = self.detail_page(user_permissions=("basic_access",))

        self.assertEqual(response.status_code, 302)

    def test_should_render_the_matrix(self):
        response = self.detail_page()

        self.assertContains(response, "Busy Ratter")
        self.assertContains(response, "--bs-primary-rgb")

    def test_should_link_back_to_the_month_it_came_from(self):
        response = self.detail_page()
        expected = f"{reverse('eos_tax:bots')}?month={YEAR}-{MONTH:02d}"

        self.assertContains(response, expected)

    def test_should_not_leave_a_visible_template_comment(self):
        """Django only treats single line {# #} as a comment."""
        self.assertNotContains(self.detail_page(), "{#")

    def test_should_link_every_character_from_the_list(self):
        self.client.force_login(
            create_user("lister", 94000011, CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(
            response, reverse("eos_tax:bot_detail", args=[RATTER_ID])
        )


class TestCharacterLookup(EosTaxTestCase):
    """Typing a name on the bots page and landing in the detail view.

    The list only shows the candidates and the ten longest days, so a character
    that crosses neither is otherwise unreachable - and that is exactly who you
    look up when someone reports a suspicion.
    """

    def setUp(self):
        build_corporations()
        configure()
        EveName.objects.create(
            eve_id=2100000003, name="Tux Tuxel", category="character"
        )
        EveName.objects.create(eve_id=2100000004, name="Tuxel", category="character")
        EveName.objects.create(
            eve_id=2100000005, name="Bravo Corp", category="corporation"
        )

    def names(self, probe):
        return [match["name"] for match in find_characters(probe)]

    def test_should_let_an_exact_name_win(self):
        """Otherwise "Tuxel" is buried by every name containing it."""
        self.assertEqual(self.names("Tuxel"), ["Tuxel"])

    def test_should_ignore_case(self):
        self.assertEqual(self.names("tuxel"), ["Tuxel"])

    def test_should_offer_every_partial_match(self):
        self.assertEqual(self.names("Tux"), ["Tux Tuxel", "Tuxel"])

    def test_should_leave_out_anything_that_is_not_a_character(self):
        self.assertEqual(self.names("Bravo"), [])

    def test_should_return_nothing_for_an_empty_search(self):
        self.assertEqual(self.names("   "), [])

    def test_should_cap_a_wide_search(self):
        for index in range(15):
            EveName.objects.create(
                eve_id=2200000000 + index,
                name=f"Widespread {index}",
                category="character",
            )

        self.assertEqual(len(find_characters("Widespread")), 10)


class TestCharacterJump(EosTaxTestCase):
    def setUp(self):
        build_corporations()
        configure()
        self.client.force_login(
            create_user("jumper", 96000010, CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def search(self, name):
        return self.client.get(
            reverse("eos_tax:bots"),
            {"month": f"{YEAR}-{MONTH:02d}", "character": name},
        )

    def test_should_open_the_detail_view_for_one_hit(self):
        response = self.search("Busy Ratter")
        expected = reverse("eos_tax:bot_detail", args=[RATTER_ID])

        self.assertRedirects(
            response,
            f"{expected}?month={YEAR}-{MONTH:02d}",
            fetch_redirect_response=False,
        )

    def test_should_keep_the_month_across_the_jump(self):
        response = self.search("Busy Ratter")

        self.assertIn(f"month={YEAR}-{MONTH:02d}", response["Location"])

    def test_should_offer_the_candidates_for_several_hits(self):
        EveName.objects.create(
            eve_id=2100000006, name="Busy Miner", category="character"
        )

        response = self.search("Busy")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Busy Ratter")
        self.assertContains(response, "Busy Miner")

    def test_should_say_so_when_nothing_matches(self):
        response = self.search("Nobody At All")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nobody At All")

    def test_should_still_show_the_list_without_a_name(self):
        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertEqual(response.status_code, 200)


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
