from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from eos_tax.db.bots import get_bot_report, get_character_month

from .factories import (
    BRAVO_CORP_ID,
    MONTH,
    OUTSIDER_CORP_ID,
    RATTER_ID,
    YEAR,
    add_entries,
    build_corporations,
    configure,
    create_user,
)


class TestCharacterMonth(EosTaxTestCase):
    """The detail matrix: calendar weeks as rows, weekdays as columns."""

    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def active(self, day, hours):
        """Make each of these hours active on that day."""
        add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, hours)

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
            self.divisions[OUTSIDER_CORP_ID], RATTER_ID, 5, (0, 6),
            corp_id=OUTSIDER_CORP_ID,
        )

        self.assertEqual(self.detail()["active_days"], 0)


class TestCharacterDetailPage(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        divisions = build_corporations()
        configure()
        add_entries(divisions[BRAVO_CORP_ID], RATTER_ID, 3, (0, 6, 12))

    def detail_page(self, user_permissions=("admin_view",)):
        user = create_user(
            "detail", 94000010, BRAVO_CORP_ID, "Bravo Corp", list(user_permissions)
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
            create_user("lister", 94000011, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertContains(
            response, reverse("eos_tax:bot_detail", args=[RATTER_ID])
        )


class TestMainCharacter(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def test_should_name_the_main_behind_a_candidate(self):
        """The ratting character is an alt; the report has to name its main."""
        owner = create_user("boss", 91999001, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        main = owner.profile.main_character
        main.character_name = "The Main"
        main.save()

        alt = EveCharacter.objects.create(
            character_id=RATTER_ID,
            character_name="Busy Ratter",
            corporation_id=BRAVO_CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRVO",
        )
        CharacterOwnership.objects.create(
            character=alt, user=owner, owner_hash="alt-owner-hash"
        )

        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        candidate = get_bot_report(YEAR, MONTH)["candidates"][0]

        self.assertEqual(candidate["character_name"], "Busy Ratter")
        self.assertEqual(candidate["main_name"], "The Main")

    def test_should_leave_the_main_empty_for_an_unknown_character(self):
        """Journal entries can name characters Alliance Auth has never seen."""
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

        candidate = get_bot_report(YEAR, MONTH)["candidates"][0]

        self.assertEqual(candidate["main_name"], "")
