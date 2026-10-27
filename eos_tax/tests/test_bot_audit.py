"""The fifth tab of the bots page: listed characters without a current audit."""

from datetime import datetime, timezone

from django.urls import reverse

from corptools.models import EveName

from eos_tax.db.bot_audit import AUDIT_INACTIVE, AUDIT_MISSING, get_unaudited_mains
from eos_tax.db.bot_store import get_stored_reports, store_bot_reports
from eos_tax.tests.base import EosTaxTestCase

from .factories import (
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    add_character_audit,
    add_entries,
    build_corporations,
    configure,
    create_alt,
    create_user,
)

# A third character the journal names, for an audit that has gone stale.
STALE_ID = 2100000005


def _row(character_id, level="high"):
    return {
        "character_id": character_id,
        "character_name": f"Pilot {character_id}",
        "corporation_name": "Bravo Corp",
        "level": level,
    }


def _report(groups=(), computed_at=None):
    """A stored list, reduced to the keys this tab reads."""
    return {
        "groups": [
            {"characters": list(characters), "count": len(characters)}
            for characters in groups
        ],
        "computed_at": computed_at or datetime(YEAR, MONTH, 20, tzinfo=timezone.utc),
    }


class TestUnauditedMains(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        EveName.objects.create(
            eve_id=STALE_ID, name="Stale Pilot", category="character"
        )

    def setUp(self):
        configure()
        # two days over the hour thresholds: listed on "Hours per day", and
        # on the runs tab's fallback list of the longest runs
        for character_id in (RATTER_ID, CASUAL_ID, STALE_ID):
            for day in (1, 2):
                add_entries(
                    self.divisions[BRAVO_CORP_ID], character_id, day, (0, 6, 12, 18)
                )

    def report(self):
        store_bot_reports(YEAR, MONTH)

        return get_unaudited_mains(get_stored_reports(YEAR, MONTH))

    def rows(self):
        return {
            row["character_id"]: row
            for group in self.report()["groups"]
            for row in group["characters"]
        }

    def test_should_list_a_character_without_an_audit(self):
        self.assertEqual(self.rows()[RATTER_ID]["audit"], AUDIT_MISSING)

    def test_should_leave_out_a_character_with_a_current_audit(self):
        add_character_audit(CASUAL_ID, active=True)

        self.assertNotIn(CASUAL_ID, self.rows())

    def test_should_list_an_audit_corptools_calls_inactive(self):
        """An audit that exists is not yet a current one - corptools keeps
        the row when the token is lost and only clears `active`."""
        add_character_audit(STALE_ID, active=False)

        self.assertEqual(self.rows()[STALE_ID]["audit"], AUDIT_INACTIVE)

    def test_should_group_under_the_main_and_not_check_the_rest_of_the_account(self):
        """The main has no audit either, but never ratted this month - only
        the characters the tabs show are checked."""
        owner = create_user("owner", 94300001, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, RATTER_ID, "Busy Ratter")

        report = self.report()
        group = next(
            group for group in report["groups"]
            if group["main_name"] == "owner character"
        )

        self.assertEqual(
            [row["character_id"] for row in group["characters"]], [RATTER_ID]
        )
        self.assertNotIn(94300001, self.rows())

    def test_should_name_the_tabs_that_listed_the_character(self):
        signals = self.rows()[RATTER_ID]["signals"]

        self.assertIn("hours", signals)
        self.assertIn("runs", signals)


class TestWhatTheTabsShow(EosTaxTestCase):
    """Driven by hand built lists, since a real one only cuts at ten mains -
    more characters than any other test here needs."""

    def rows(self, reports):
        return [
            row
            for group in get_unaudited_mains(reports)["groups"]
            for row in group["characters"]
        ]

    def test_should_take_the_strongest_assessment_of_its_readings(self):
        reports = {
            "runs": _report(groups=[[_row(RATTER_ID, "low")]]),
            "clock": _report(groups=[[_row(RATTER_ID, "high")]]),
            "rhythm": _report(groups=[[_row(RATTER_ID, "medium")]]),
        }

        (row,) = self.rows(reports)

        self.assertEqual(row["level"], "high")
        self.assertEqual(row["signals"], ["runs", "clock", "rhythm"])

    def test_should_list_every_main_not_the_first_ten(self):
        characters = [_row(2100001000 + number) for number in range(12)]
        reports = {"hours": _report(groups=[[row] for row in characters])}

        self.assertEqual(len(get_unaudited_mains(reports)["groups"]), 12)

    def test_should_be_as_old_as_its_oldest_list(self):
        """The list is only as fresh as the stalest of the four it reads."""
        older = datetime(YEAR, MONTH, 3, tzinfo=timezone.utc)
        reports = {
            "hours": _report(groups=[[_row(RATTER_ID)]]),
            "runs": _report(computed_at=older),
        }

        self.assertEqual(get_unaudited_mains(reports)["computed_at"], older)


class TestAuditTab(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()
        configure()

    def setUp(self):
        self.client.force_login(
            create_user("boss", 94300002, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def test_should_render_the_fragment_with_a_link_back_to_the_tab(self):
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        month = f"{YEAR}-{MONTH:02d}"

        response = self.client.get(
            reverse("eos_tax:bot_signal", args=["audit"]), {"month": month}
        )

        self.assertNotIn("<html", response.content.decode())
        self.assertContains(response, "Busy Ratter")
        self.assertContains(response, "no audit")
        self.assertContains(
            response, f"{reverse('eos_tax:bots')}?month={month}&amp;tab=hours"
        )

    def test_should_say_so_when_everybody_has_a_current_audit(self):
        response = self.client.get(
            reverse("eos_tax:bot_signal", args=["audit"]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )

        self.assertContains(response, "has a current audit")

    def test_should_be_a_tab_of_the_list_page_only(self):
        """The character page shares the tab strip, and has no lists to sum
        up - a fifth tab there would open onto nothing."""
        month = f"{YEAR}-{MONTH:02d}"

        listing = self.client.get(reverse("eos_tax:bots"), {"month": month})
        detail = self.client.get(
            reverse("eos_tax:bot_detail", args=[RATTER_ID]), {"month": month}
        )

        self.assertContains(listing, 'data-bs-target="#eos-tax-tab-audit"')
        self.assertContains(listing, 'id="eos-tax-tab-audit"')
        self.assertNotContains(detail, "eos-tax-tab-audit")
