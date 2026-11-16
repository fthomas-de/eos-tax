"""The sixth tab of the bots page: listed characters who stopped logging in."""

from datetime import datetime, timedelta, timezone

from django.urls import reverse
from django.utils import timezone as django_timezone

from eos_tax.db.bot_ban import get_possibly_banned
from eos_tax.db.bot_store import settings_fingerprint
from eos_tax.models import BotReport, GmReport, TaxConfiguration
from eos_tax.tests.base import EosTaxTestCase

from .factories import (
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    add_character_audit,
    configure,
    create_alt,
    create_user,
)

COMPUTED_AT = datetime(YEAR, MONTH, 20, tzinfo=timezone.utc)


def _row(character_id, corporation_name="Bravo Corp"):
    return {
        "character_id": character_id,
        "character_name": f"Pilot {character_id}",
        "corporation_name": corporation_name,
        "level": "low",
    }


def _store(year, month, signal, *rows, listed=True, fingerprint="any"):
    """A stored list, reduced to the keys this tab reads."""
    BotReport.objects.create(
        year=year,
        month=month,
        signal=signal,
        report={
            "listed": listed,
            "groups": [{"characters": [row], "count": 1} for row in rows],
            "stats": {},
        },
        fingerprint=fingerprint,
        computed_at=COMPUTED_AT,
    )


def _gm(*bookings):
    """The stored GM report, reduced to what this tab reads: (character_id,
    description) per booking."""
    GmReport.objects.create(
        pk=1,
        report={"transactions": [
            {"character_id": character_id, "description": description}
            for character_id, description in bookings
        ]},
        computed_at=COMPUTED_AT,
    )


GM_X = "GM [16519715] issued transaction between Pilot and GM X"
GM_X_FIRST = "GM [16519715] issued transaction between GM X and Pilot"
BANK = "GM [31365906] issued transaction between Pilot and EVE Central Bank"


def _logged_in(character_id, days_ago, name=None):
    audit = add_character_audit(character_id, active=True, name=name)
    audit.last_known_login = (
        None if days_ago is None
        else django_timezone.now() - timedelta(days=days_ago)
    )
    audit.save()

    return audit


class TestPossiblyBanned(EosTaxTestCase):
    def rows(self, min_days=30):
        return {
            row["character_id"]: row
            for group in get_possibly_banned(min_days)["groups"]
            for row in group["characters"]
        }

    def test_should_list_a_listed_character_gone_quiet(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(RATTER_ID, 45)

        self.assertIn(RATTER_ID, self.rows())

    def test_should_leave_out_a_character_who_logged_in_since(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(RATTER_ID, 29)

        self.assertNotIn(RATTER_ID, self.rows())

    def test_should_take_the_number_of_days_it_is_given(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(RATTER_ID, 15)

        self.assertIn(RATTER_ID, self.rows(min_days=10))
        self.assertNotIn(RATTER_ID, self.rows(min_days=20))

    def test_should_leave_out_a_character_without_a_known_login(self):
        """The audit tab's finding, not this one."""
        _store(YEAR, MONTH, "hours", _row(RATTER_ID), _row(CASUAL_ID))
        _logged_in(RATTER_ID, None)

        self.assertEqual(self.rows(), {})

    def test_should_leave_out_a_quiet_character_no_list_showed(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(CASUAL_ID, 90)

        self.assertNotIn(CASUAL_ID, self.rows())

    def test_should_count_a_fallback_list_and_older_settings(self):
        """Whatever a tab showed, under whatever settings it was computed -
        the user's choice."""
        _store(YEAR, MONTH, "runs", _row(RATTER_ID), listed=False, fingerprint="old")
        _logged_in(RATTER_ID, 45)

        self.assertIn(RATTER_ID, self.rows())

    def test_should_name_every_month_once_newest_first(self):
        _store(YEAR, MONTH - 2, "hours", _row(RATTER_ID))
        _store(YEAR, MONTH, "runs", _row(RATTER_ID))
        _store(YEAR, MONTH, "clock", _row(RATTER_ID))
        _store(YEAR - 1, 12, "rhythm", _row(RATTER_ID))
        _logged_in(RATTER_ID, 45)

        self.assertEqual(
            self.rows()[RATTER_ID]["months"],
            [f"{YEAR}-{MONTH:02d}", f"{YEAR}-{MONTH - 2:02d}", f"{YEAR - 1}-12"],
        )

    def test_should_ignore_rows_that_are_no_reading(self):
        """Only the four readings are lists a reader saw a character on."""
        _store(YEAR, MONTH, "audit", _row(RATTER_ID))
        _logged_in(RATTER_ID, 45)

        self.assertEqual(self.rows(), {})

    def test_should_show_the_corporation_of_today(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID, corporation_name="Old Corp"))
        _logged_in(RATTER_ID, 45)

        self.assertEqual(self.rows()[RATTER_ID]["corporation_name"], "Bravo Corp")

    def test_should_group_under_the_main_ordered_by_name(self):
        owner = create_user("zulu", 94500001, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, RATTER_ID, "Busy Ratter")
        _store(YEAR, MONTH, "hours", _row(RATTER_ID), _row(CASUAL_ID))
        _logged_in(RATTER_ID, 45)
        _logged_in(CASUAL_ID, 45)

        groups = get_possibly_banned(30)["groups"]

        self.assertEqual(
            [group["main_name"] for group in groups],
            [f"Pilot {CASUAL_ID}", "zulu character"],
        )


class TestGmX(EosTaxTestCase):
    """A GM X booking puts a quiet character on the tab without any list -
    the user's choice."""

    def rows(self):
        return {
            row["character_id"]: row
            for group in get_possibly_banned(30)["groups"]
            for row in group["characters"]
        }

    def test_should_list_a_quiet_character_with_a_gm_x_booking(self):
        _gm((RATTER_ID, GM_X))
        _logged_in(RATTER_ID, 45, name="Busy Ratter")

        row = self.rows()[RATTER_ID]

        self.assertTrue(row["gm"])
        self.assertEqual(row["months"], [])
        # the GM report stores no name
        self.assertEqual(row["character_name"], "Busy Ratter")
        self.assertEqual(row["corporation_name"], "Bravo Corp")

    def test_should_count_gm_x_on_either_side(self):
        _gm((RATTER_ID, GM_X_FIRST))
        _logged_in(RATTER_ID, 45)

        self.assertIn(RATTER_ID, self.rows())

    def test_should_ignore_another_counterparty(self):
        _gm((RATTER_ID, BANK))
        _logged_in(RATTER_ID, 45)

        self.assertEqual(self.rows(), {})

    def test_should_leave_out_a_gm_x_character_who_logged_in_since(self):
        _gm((RATTER_ID, GM_X))
        _logged_in(RATTER_ID, 29)

        self.assertEqual(self.rows(), {})

    def test_should_keep_the_months_of_a_listed_character(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _gm((RATTER_ID, GM_X))
        _logged_in(RATTER_ID, 45)

        row = self.rows()[RATTER_ID]

        self.assertEqual(row["months"], [f"{YEAR}-{MONTH:02d}"])
        self.assertTrue(row["gm"])
        self.assertEqual(row["character_name"], f"Pilot {RATTER_ID}")

    def test_should_count_lists_and_gm_x_apart(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _gm((RATTER_ID, GM_X), (CASUAL_ID, GM_X), (CASUAL_ID, BANK))

        stats = get_possibly_banned(30)["stats"]

        self.assertEqual((stats["flagged_characters"], stats["gm_characters"]), (1, 2))


class TestTheSetting(EosTaxTestCase):
    def test_should_default_to_thirty_days(self):
        self.assertEqual(
            TaxConfiguration._meta.get_field("possibly_banned_min_days").default, 30
        )

    def test_should_not_recompute_the_lists_when_changed(self):
        """A bot_ name would put it in the fingerprint, and every stored
        month would be computed again for a filter applied at render."""
        config = configure()
        before = settings_fingerprint(config)

        config.possibly_banned_min_days = 90

        self.assertEqual(settings_fingerprint(config), before)


class TestBannedTab(EosTaxTestCase):
    def setUp(self):
        configure()
        self.client.force_login(
            create_user("boss", 94500002, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )
        self.month = f"{YEAR}-{MONTH:02d}"

    def fetch(self):
        return self.client.get(
            reverse("eos_tax:bot_signal", args=["banned"]), {"month": self.month}
        )

    def test_should_render_the_fragment_with_links_to_the_months(self):
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(RATTER_ID, 45)

        response = self.fetch()

        self.assertNotIn("<html", response.content.decode())
        self.assertContains(response, f"Pilot {RATTER_ID}")
        self.assertContains(response, f"{reverse('eos_tax:bots')}?month={self.month}")
        self.assertContains(response, "data-eos-sortable-groups")
        last_login = (django_timezone.now() - timedelta(days=45)).date()
        self.assertContains(response, last_login.isoformat())

    def test_should_read_the_days_from_the_settings(self):
        config = TaxConfiguration.get_solo()
        config.possibly_banned_min_days = 10
        config.save()
        _store(YEAR, MONTH, "hours", _row(RATTER_ID))
        _logged_in(RATTER_ID, 15)

        response = self.fetch()

        self.assertContains(response, f"Pilot {RATTER_ID}")
        self.assertContains(response, "at least 10 days ago")

    def test_should_link_a_gm_x_character_to_gm_transactions(self):
        _gm((RATTER_ID, GM_X))
        _logged_in(RATTER_ID, 45, name="Busy Ratter")

        response = self.fetch()

        self.assertContains(
            response,
            f'{reverse("eos_tax:gm_transactions")}?search=%22Busy%20Ratter%22">GM</a>',
        )

    def test_should_say_so_when_nobody_has_gone_quiet(self):
        self.assertContains(self.fetch(), "has logged in since")

    def test_should_be_a_tab_of_the_list_page_only(self):
        listing = self.client.get(reverse("eos_tax:bots"), {"month": self.month})
        detail = self.client.get(
            reverse("eos_tax:bot_detail", args=[RATTER_ID]), {"month": self.month}
        )

        self.assertContains(listing, 'data-bs-target="#eos-tax-tab-banned"')
        self.assertContains(listing, 'data-eos-signal="banned"')
        self.assertNotContains(detail, "eos-tax-tab-banned")
