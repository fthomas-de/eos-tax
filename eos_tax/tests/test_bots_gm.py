"""GM Transactions on the bots pages: red rows, the account tab, copy buttons."""

import datetime
from decimal import Decimal

from corptools.models import CharacterAudit
from django.core.cache import cache
from django.urls import reverse

from eos_tax.db.gm_transactions import (
    account_character_ids,
    get_gm_page,
    get_stored_gm_report,
    gm_listed_character_ids,
    store_gm_report,
)
from eos_tax.models import GmNote, TaxConfiguration
from eos_tax.tests.base import EosTaxTestCase, json_script

from .factories import (
    BRAVO_CORP_ID,
    CASUAL_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    add_character_audit,
    add_entries,
    add_wallet_entry,
    build_corporations,
    configure,
    create_alt,
    create_user,
)

GM_TEXT = "GM [16519715] issued transaction between Mr Vaseline and GM X"

ALT_ID = 2100000301
STRANGER_ID = 2100000302
BROKE_ID = 2100000303


def _at(day):
    return datetime.datetime(YEAR, MONTH, day, 12, tzinfo=datetime.timezone.utc)


class TestGmListed(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        build_corporations()

    def setUp(self):
        configure()

    def test_should_take_both_sources_of_the_gm_page(self):
        booked = add_character_audit(ALT_ID, True, name="Booked Pilot")
        add_wallet_entry(booked, GM_TEXT, Decimal("-1"), _at(3))
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()
        add_character_audit(STRANGER_ID, True, name="Clean Pilot")
        store_gm_report()

        self.assertEqual(gm_listed_character_ids(), {ALT_ID, BROKE_ID})

    def test_should_take_the_wallets_before_the_job_ran(self):
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()

        self.assertEqual(gm_listed_character_ids(), {BROKE_ID})


class TestAccount(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        build_corporations()

    def test_should_take_every_character_of_the_account(self):
        owner = create_user("owner", 2100000399, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, ALT_ID, "Alt Pilot")
        create_user("other", 2100000398, BRAVO_CORP_ID, "Bravo Corp")

        self.assertEqual(account_character_ids(ALT_ID), {ALT_ID, 2100000399})

    def test_should_take_an_unregistered_character_alone(self):
        self.assertEqual(account_character_ids(STRANGER_ID), {STRANGER_ID})

    def test_should_narrow_the_gm_page_to_the_account(self):
        alt = add_character_audit(ALT_ID, True, name="Alt Pilot")
        add_wallet_entry(alt, GM_TEXT, Decimal("-1"), _at(3))
        stranger = add_character_audit(STRANGER_ID, True, name="Stranger")
        add_wallet_entry(stranger, GM_TEXT, Decimal("-2"), _at(4))
        stranger.balance = Decimal("-5.00")
        stranger.save()
        store_gm_report()

        page = get_gm_page(get_stored_gm_report(), {ALT_ID})

        self.assertEqual([row["character_id"] for row in page["rows"]], [ALT_ID])
        self.assertEqual(page["stats"]["negative"], 0)


class BotsPageTestCase(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()
        # low enough that every reading lists the ratter - see
        # test_should_give_a_group_of_one_its_heading_in_every_reading
        config = TaxConfiguration.get_solo()
        config.bot_rhythm_min_payouts = 1
        config.bot_rhythm_corp_min_payouts = 1
        config.bot_clock_min_payouts = 1
        config.bot_clock_corp_min_payouts = 1
        config.bot_clock_min_concentration = 0
        config.save()
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))
        # the corporation's yardstick for rhythm and clock
        add_entries(self.divisions[BRAVO_CORP_ID], CASUAL_ID, 3, (1, 7, 13, 19))
        self.client.force_login(
            create_user("boss", 2100000397, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def tearDown(self):
        cache.clear()

    def bots(self):
        return self.client.get(reverse("eos_tax:bots"), {"month": f"{YEAR}-{MONTH:02d}"})

    def signal(self, name):
        return self.client.get(
            reverse("eos_tax:bot_signal", args=[name]), {"month": f"{YEAR}-{MONTH:02d}"}
        )

    def detail(self, character_id=RATTER_ID):
        return self.client.get(
            reverse("eos_tax:bot_detail", args=[character_id]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )

    def gm_tab(self, character_id=RATTER_ID):
        return self.client.get(
            reverse("eos_tax:bot_signal_detail", args=["gm", character_id]),
            {"month": f"{YEAR}-{MONTH:02d}"},
        )

    def below_zero(self, character_id):
        audit = add_character_audit(character_id, True)
        audit.balance = Decimal("-10.00")
        audit.save()

        return audit


class TestRedRows(BotsPageTestCase):
    def test_should_mark_a_character_the_gm_page_lists(self):
        self.below_zero(RATTER_ID)

        self.assertContains(self.bots(), 'class="table-danger"', count=1)

    def test_should_leave_every_other_row_alone(self):
        self.assertNotContains(self.bots(), "table-danger")

    def test_should_mark_the_fetched_tabs_too(self):
        self.below_zero(RATTER_ID)

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.signal(name)
                rows = response.content.decode().split("<tr")
                ratter = [row for row in rows if f"bots/{RATTER_ID}/" in row]

                self.assertEqual(len(ratter), 1)
                self.assertIn('class="table-danger"', ratter[0].split(">")[0])

    def test_should_mark_the_audit_tab(self):
        """The ratter has no audit on the lists' terms, so it is listed there."""
        self.below_zero(RATTER_ID)
        CharacterAudit.objects.filter(character__character_id=RATTER_ID).update(active=False)

        self.assertContains(self.signal("audit"), 'class="table-danger"', count=1)


class TestCopyButtons(BotsPageTestCase):
    def test_should_offer_the_character_and_main_names_on_the_list(self):
        owner = create_user("owner", 2100000396, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, RATTER_ID, "Busy Ratter")

        response = self.bots()

        self.assertContains(response, 'data-clipboard-text="Busy Ratter"')
        # in the Main column and in the group heading
        self.assertContains(response, 'data-clipboard-text="owner character"', count=2)
        self.assertContains(response, "Copy main name to clipboard")
        self.assertContains(response, "clipboard.min.js")
        self.assertContains(response, "eos_tax/js/copy-buttons.")

    def test_should_offer_the_names_on_the_fetched_tabs(self):
        owner = create_user("owner", 2100000396, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, RATTER_ID, "Busy Ratter")

        for name in ("runs", "rhythm", "clock"):
            with self.subTest(name=name):
                response = self.signal(name)

                self.assertContains(response, 'data-clipboard-text="Busy Ratter"')
                # in the Main column and in the group heading
                self.assertContains(
                    response, 'data-clipboard-text="owner character"', count=2
                )

    def test_should_offer_the_name_on_the_character_page(self):
        response = self.detail()

        self.assertContains(response, 'data-clipboard-text="Busy Ratter"')
        self.assertContains(response, "eos_tax/js/copy-buttons.")


class TestGmTab(BotsPageTestCase):
    def test_should_offer_the_tab_on_the_character_page_only(self):
        detail = self.detail()
        config = json_script(detail.content.decode(), "eos-tax-config")

        self.assertContains(detail, 'data-bs-target="#eos-tax-tab-gm"')
        self.assertContains(detail, 'data-eos-signal="gm"')
        self.assertEqual(
            config["signals"]["gm"],
            reverse("eos_tax:bot_signal_detail", args=["gm", RATTER_ID])
            + f"?month={YEAR}-{MONTH:02d}",
        )
        self.assertNotContains(self.bots(), "eos-tax-tab-gm")

    def test_should_list_the_whole_account_and_nobody_else(self):
        owner = create_user("owner", 2100000396, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(owner, RATTER_ID, "Busy Ratter")
        create_alt(owner, ALT_ID, "Alt Pilot")
        alt = add_character_audit(ALT_ID, True)
        add_wallet_entry(alt, GM_TEXT, Decimal("-5000000"), _at(3))
        stranger = add_character_audit(STRANGER_ID, True, name="Stranger Pilot")
        add_wallet_entry(stranger, GM_TEXT, Decimal("-7"), _at(4))
        self.below_zero(BROKE_ID)

        response = self.gm_tab()
        body = response.content.decode()

        self.assertNotIn("<html", body)
        self.assertIn("Alt Pilot", body)
        self.assertIn("-5,000,000", body)
        self.assertIn('data-clipboard-text="Alt Pilot"', body)
        self.assertNotIn("Stranger Pilot", body)
        self.assertNotIn(f"bots/{BROKE_ID}/", body)

    def test_should_list_a_wallet_below_zero_of_the_account(self):
        self.below_zero(RATTER_ID)

        body = self.gm_tab().content.decode()

        self.assertIn(f"bots/{RATTER_ID}/", body)
        self.assertIn("1 wallet below zero", body)

    def test_should_show_a_cleared_row_read_only(self):
        self.below_zero(RATTER_ID)
        GmNote.objects.create(character_id=RATTER_ID, entry_id=0, text="owes", cleared=True)

        body = self.gm_tab().content.decode()

        self.assertIn("fa-check text-success", body)
        self.assertNotIn("data-eos-cleared-box", body)

    def test_should_say_so_when_the_account_has_nothing(self):
        self.assertContains(
            self.gm_tab(), "No GM transaction and no wallet below zero on this account."
        )
