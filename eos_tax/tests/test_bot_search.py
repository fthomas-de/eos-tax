from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from corptools.models import EveName

from eos_tax.db.bots import find_characters

from .factories import (
    BRAVO_CORP_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    build_corporations,
    configure,
    create_user,
)


class TestCharacterLookup(EosTaxTestCase):
    """Typing a name on the bots page and landing in the detail view.

    The list only shows the candidates and the ten longest days, so a character
    that crosses neither is otherwise unreachable - and that is exactly who you
    look up when someone reports a suspicion.
    """

    @classmethod
    def setUpTestData(cls):
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
        # find_characters caps at ten by default, so eleven is what shows it
        for index in range(11):
            EveName.objects.create(
                eve_id=2200000000 + index,
                name=f"Widespread {index}",
                category="character",
            )

        self.assertEqual(len(find_characters("Widespread")), 10)


class TestCharacterJump(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        build_corporations()
        configure()
        cls.user = create_user(
            "jumper", 96000010, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )

    def setUp(self):
        # self.client is rebuilt per test, so the login has to be too
        self.client.force_login(self.user)

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
        self.assertContains(response, 'No character found for "Nobody At All".')

    def test_should_still_show_the_list_without_a_name(self):
        """An empty box is not a search: the list page renders instead of
        jumping somewhere, which a bare 200 does not tell apart from the
        detail view a one hit search redirects to."""
        response = self.client.get(
            reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No character crossed both thresholds")
