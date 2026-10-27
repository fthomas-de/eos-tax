"""The GM transactions page: GM bookings and wallets below zero."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from allianceauth.eveonline.models import EveCharacter
from corptools.models import CharacterAudit

from eos_tax.db.gm_transactions import (
    find_gm_transactions,
    get_gm_page,
    get_stored_gm_report,
    sides,
    store_gm_report,
)
from eos_tax.models import GmReport
from eos_tax.tasks import GM_REPORT_LOCK, run_update_gm_report
from eos_tax.tests.base import EosTaxTestCase, read_static, table_body

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    LONG_AGO,
    OUTSIDER_CORP_ID,
    add_character_audit,
    add_corporation_history,
    add_wallet_entry,
    build_corporations,
    configure,
    create_alt,
    create_tax_row,
    create_user,
)

GM_ID = 2100000101
BROKE_ID = 2100000102
DEEPER_ID = 2100000103
CLEAN_ID = 2100000104

GM_TEXT = "GM [16519715] issued transaction between Mr Vaseline and GM X"
BANK_TEXT = "GM [31365906] issued transaction between Hydra head4 and EVE Central Bank"


def _at(day, hour=12):
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


class TestSides(EosTaxTestCase):
    def test_should_read_the_character_first_and_the_counterparty_second(self):
        self.assertEqual(sides(GM_TEXT, set()), ("Mr Vaseline", "GM X"))
        self.assertEqual(sides(BANK_TEXT, set()), ("Hydra head4", "EVE Central Bank"))
        self.assertEqual(
            sides(
                "GM [16519715] issued transaction between Women's clothing mountain and GM X",
                set(),
            ),
            ("Women's clothing mountain", "GM X"),
        )

    def test_should_keep_an_and_inside_the_name(self):
        self.assertEqual(
            sides("GM [1] issued transaction between Salt and Pepper and GM X", set()),
            ("Salt and Pepper", "GM X"),
        )

    def test_should_take_the_player_side_wherever_it_stands(self):
        # a GM taking ISK back names the character second
        self.assertEqual(
            sides("GM [1] issued transaction between GM X and Mr Vaseline",
                  {"mr vaseline"}),
            ("Mr Vaseline", "GM X"),
        )
        self.assertEqual(sides(GM_TEXT, {"mr vaseline"}), ("Mr Vaseline", "GM X"))

    def test_should_compare_player_names_regardless_of_case(self):
        self.assertEqual(
            sides("GM [1] issued transaction between GM X and MR VASELINE",
                  {"mr vaseline"}),
            ("MR VASELINE", "GM X"),
        )

    def test_should_offer_no_counterparty_between_two_players(self):
        self.assertEqual(
            sides("GM [1] issued transaction between Mr Vaseline and Hydra head4",
                  {"mr vaseline", "hydra head4"}),
            ("Mr Vaseline", ""),
        )

    def test_should_be_empty_without_the_pattern(self):
        self.assertEqual(sides("GM [1] issued a refund", set()), ("", ""))
        self.assertEqual(
            sides("GM [1] issued transaction between nobody", set()), ("", "")
        )


class GmTestCase(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        build_corporations()

    def setUp(self):
        configure()
        self.gm = add_character_audit(GM_ID, True, name="Mr Vaseline")
        self.gm.balance = Decimal("1500.00")
        self.gm.save()

    def page(self):
        store_gm_report()

        return get_gm_page(get_stored_gm_report())


class TestFindGmTransactions(GmTestCase):
    def test_should_find_only_descriptions_starting_with_gm(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-5000000000"), _at(3))
        # the same words elsewhere, and a different case, are not a GM booking
        add_wallet_entry(self.gm, f"Note: {GM_TEXT}", 1, _at(4), "player_donation")
        add_wallet_entry(self.gm, GM_TEXT.lower(), 1, _at(5), "player_donation")
        add_wallet_entry(self.gm, "Office rental fee between X and Y GmbH", 1, _at(6),
                         "office_rental_fee")

        found = find_gm_transactions()

        self.assertEqual([row["description"] for row in found], [GM_TEXT])
        self.assertEqual(found[0]["character_id"], GM_ID)

    def test_should_survive_storage_with_date_and_amount_intact(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-5000000000.50"), _at(3))

        transaction = self.page()["rows"][0]

        self.assertEqual(transaction["date"], _at(3))
        self.assertEqual(transaction["amount"], Decimal("-5000000000.50"))


class TestGmPage(GmTestCase):
    def test_should_list_a_gm_transaction_with_everything_around_it(self):
        user = create_user("vaseline", 2100000199, BRAVO_CORP_ID, "Bravo Corp")
        EveCharacter.objects.filter(character_id=GM_ID).delete()
        create_alt(user, GM_ID, "Mr Vaseline")
        EveCharacter.objects.filter(character_id=GM_ID).update(alliance_name="Taxed Alliance")
        self.gm = CharacterAudit.objects.create(
            character=EveCharacter.objects.get(character_id=GM_ID),
            active=True,
            balance=Decimal("-250.00"),
        )
        add_wallet_entry(self.gm, BANK_TEXT, Decimal("-1000000"), _at(3))

        row = self.page()["rows"][0]

        self.assertEqual(row["character_name"], "Mr Vaseline")
        self.assertEqual(row["corporation_name"], "Bravo Corp")
        self.assertEqual(row["alliance_name"], "Taxed Alliance")
        self.assertEqual(row["main_name"], "vaseline character")
        self.assertEqual(row["named_character"], "Hydra head4")
        self.assertEqual(row["amount"], Decimal("-1000000"))
        self.assertEqual(row["balance"], Decimal("-250.00"))
        self.assertEqual(row["description"], BANK_TEXT)

    def test_should_show_the_characters_age(self):
        EveCharacter.objects.filter(character_id=GM_ID).update(
            birthday=date.today() - timedelta(days=400)
        )
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()

        rows = {row["character_id"]: row for row in self.page()["rows"]}

        self.assertEqual(rows[GM_ID]["age"], "1 y")
        self.assertEqual(rows[GM_ID]["age_days"], 400)
        # no birthday known: nothing to show and nothing to sort by
        self.assertEqual(rows[BROKE_ID]["age"], "")
        self.assertIsNone(rows[BROKE_ID]["age_days"])

    def test_should_take_the_age_from_the_job(self):
        """For a wallet below zero as much as for a transaction - the job
        finds both."""
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()
        EveCharacter.objects.filter(character_id=BROKE_ID).update(
            birthday=date.today() - timedelta(days=400)
        )
        store_gm_report()
        EveCharacter.objects.filter(character_id=BROKE_ID).update(
            birthday=date.today() - timedelta(days=10)
        )

        row = get_gm_page(get_stored_gm_report())["rows"][0]

        self.assertEqual((row["age"], row["age_days"]), ("1 y", 400))

    def test_should_read_a_report_stored_before_ages(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        GmReport.objects.create(
            pk=1,
            report={"transactions": find_gm_transactions()},
            computed_at=_at(4),
        )

        row = get_gm_page(get_stored_gm_report())["rows"][0]

        self.assertEqual((row["age"], row["age_days"]), ("", None))

    def test_should_name_the_corporation_at_the_time_of_each_transaction(self):
        add_corporation_history(GM_ID, ALPHA_CORP_ID, datetime(2022, 1, 1, tzinfo=timezone.utc))
        # outside the alliance, and left since: shown all the same
        add_corporation_history(GM_ID, OUTSIDER_CORP_ID, datetime(2023, 1, 1, tzinfo=timezone.utc))
        add_corporation_history(GM_ID, BRAVO_CORP_ID, datetime(2024, 1, 1, tzinfo=timezone.utc))
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-2"),
                         datetime(2023, 6, 1, tzinfo=timezone.utc))
        # the very second a membership started belongs to it
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-3"),
                         datetime(2022, 1, 1, tzinfo=timezone.utc))
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-4"),
                         datetime(2021, 1, 1, tzinfo=timezone.utc))
        broke = add_character_audit(BROKE_ID, True)
        broke.balance = Decimal("-10.00")
        broke.save()

        page = self.page()

        self.assertEqual(
            [(row["amount"], row["corporation_then"]) for row in page["rows"]],
            [(Decimal("-1"), f"Corp {BRAVO_CORP_ID}"),
             (Decimal("-2"), f"Corp {OUTSIDER_CORP_ID}"),
             (Decimal("-3"), f"Corp {ALPHA_CORP_ID}"),
             # before the first record, and no transaction at all
             (Decimal("-4"), ""),
             (None, "")],
        )

    def test_should_survive_two_records_starting_the_same_second(self):
        moment = datetime(2023, 1, 1, tzinfo=timezone.utc)
        add_corporation_history(GM_ID, ALPHA_CORP_ID, moment)
        add_corporation_history(GM_ID, BRAVO_CORP_ID, moment)
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), moment)

        row = self.page()["rows"][0]

        # the later record wins, as in the tax calculation
        self.assertEqual(row["corporation_then"], f"Corp {BRAVO_CORP_ID}")

    def test_should_offer_every_counterparty_on_the_page(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-2"), _at(4))
        add_wallet_entry(self.gm, BANK_TEXT, Decimal("-3"), _at(5))
        add_wallet_entry(self.gm, "GM [1] issued transaction between Mr Vaseline and "
                                  "secure commerce commission", Decimal("-4"), _at(6))
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()

        page = self.page()

        # by name whatever the case, the rows without one last
        self.assertEqual(
            [(party["name"], party["count"]) for party in page["parties"]],
            [("EVE Central Bank", 1), ("GM X", 2),
             ("secure commerce commission", 1), ("", 1)],
        )
        self.assertEqual(
            {row["counterparty"] for row in page["rows"] if row["character_id"] == BROKE_ID},
            {""},
        )

    def test_should_never_offer_a_character_as_counterparty(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        # the GM takes ISK back: the wallet owner stands second
        add_wallet_entry(self.gm, "GM [1] issued transaction between GM X and Mr Vaseline",
                         Decimal("2"), _at(4))
        # another registered character moved by the GM
        add_character_audit(DEEPER_ID, True, name="Deep Pockets")
        add_wallet_entry(self.gm, "GM [1] issued transaction between EVE Central Bank "
                                  "and Deep Pockets", Decimal("3"), _at(5))

        page = self.page()

        self.assertEqual(
            [(party["name"], party["count"]) for party in page["parties"]],
            [("EVE Central Bank", 1), ("GM X", 2)],
        )
        self.assertEqual(
            [row["named_character"] for row in page["rows"]],
            ["Deep Pockets", "Mr Vaseline", "Mr Vaseline"],
        )

    def test_should_list_a_wallet_below_zero_without_a_transaction(self):
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()
        clean = add_character_audit(CLEAN_ID, True, name="Clean Pilot")
        clean.balance = Decimal("0.00")
        clean.save()

        page = self.page()

        self.assertEqual([row["character_id"] for row in page["rows"]], [BROKE_ID])
        self.assertIsNone(page["rows"][0]["amount"])
        self.assertEqual(page["stats"]["negative"], 1)

    def test_should_put_wallets_below_zero_after_transactions_deepest_first(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-2"), _at(9))
        for character_id, balance in ((BROKE_ID, "-10.00"), (DEEPER_ID, "-900.00")):
            audit = add_character_audit(character_id, True)
            audit.balance = Decimal(balance)
            audit.save()

        rows = self.page()["rows"]

        self.assertEqual(
            [(row["character_id"], row["amount"]) for row in rows],
            [(GM_ID, Decimal("-2")), (GM_ID, Decimal("-1")),
             (DEEPER_ID, None), (BROKE_ID, None)],
        )

    def test_should_read_the_balance_now_not_when_the_job_ran(self):
        store_gm_report()
        CharacterAudit.objects.filter(pk=self.gm.pk).update(balance=Decimal("-1.00"))

        rows = get_gm_page(get_stored_gm_report())["rows"]

        self.assertEqual([row["character_id"] for row in rows], [GM_ID])

    def test_should_name_only_corporations_of_the_alliance_in_joining_order(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        # Alpha has left the alliance - Alliance Auth no longer says so, its
        # tax rows still do
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp")
        add_corporation_history(GM_ID, ALPHA_CORP_ID, LONG_AGO)
        add_corporation_history(GM_ID, OUTSIDER_CORP_ID, datetime(2023, 1, 1, tzinfo=timezone.utc))
        add_corporation_history(GM_ID, BRAVO_CORP_ID, datetime(2024, 1, 1, tzinfo=timezone.utc))
        add_corporation_history(GM_ID, ALPHA_CORP_ID, datetime(2025, 1, 1, tzinfo=timezone.utc))

        row = self.page()["rows"][0]

        self.assertEqual(
            row["alliance_corporations"],
            [f"Corp {ALPHA_CORP_ID}", f"Corp {BRAVO_CORP_ID}"],
        )


class TestGmJob(GmTestCase):
    def tearDown(self):
        cache.clear()

    def test_should_free_the_lock_after_a_failure(self):
        cache.add(GM_REPORT_LOCK, 1)

        with mock.patch("eos_tax.tasks.store_gm_report", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                run_update_gm_report()

        self.assertIsNone(cache.get(GM_REPORT_LOCK))

    def test_should_run_with_the_tax_job(self):
        from eos_tax.tasks import run_update_alliance

        with mock.patch("eos_tax.tasks.queue_gm_report") as queued, \
                mock.patch("eos_tax.tasks.queue_corporations"), \
                mock.patch("eos_tax.tasks.queue_bot_reports"):
            run_update_alliance()

        queued.assert_called_once_with()


class TestGmView(GmTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user(
            "admin", 2100000198, BRAVO_CORP_ID, "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)
        self.url = reverse("eos_tax:gm_transactions")

    def tearDown(self):
        cache.clear()

    def test_should_redirect_without_admin_view(self):
        user = create_user("basic", 2100000197, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        self.client.force_login(user)

        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_should_render_the_rows_the_job_found(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-5000000000"), _at(3))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = table_body(response)
        self.assertIn("Mr Vaseline", body)
        self.assertIn(GM_TEXT, body)
        self.assertIn('data-order="-5000000000.00"', body)
        self.assertIn(reverse("corptools:reactmain", args=[GM_ID]), body)
        self.assertContains(response, "eos_tax/js/gm-transactions.")
        self.assertContains(response, f'href="{self.url}"')

    def test_should_sort_the_age_by_days(self):
        EveCharacter.objects.filter(character_id=GM_ID).update(
            birthday=date.today() - timedelta(days=400)
        )
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        body = table_body(self.client.get(self.url))

        self.assertIn('data-order="400">1 y</td>', body)

    def test_script_should_describe_every_column(self):
        """DataTables refuses a table whose columns option has a different
        length than its header - the page would stay unsorted."""
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        response = self.client.get(self.url)
        header = response.content.decode().split("<thead>")[1].split("</thead>")[0]

        self.assertEqual(
            read_static("gm-transactions.js").count("searchable:"),
            header.count("<th "),
        )

    def test_should_offer_a_box_per_counterparty(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        add_wallet_entry(self.gm, BANK_TEXT, Decimal("-2"), _at(4))

        content = self.client.get(self.url).content.decode()

        self.assertIn("data-eos-party-filter", content)
        self.assertIn('value="GM X"', content)
        self.assertIn('value="EVE Central Bank"', content)
        self.assertIn('<tr data-eos-party="GM X">', content)
        self.assertIn('<tr data-eos-party="EVE Central Bank">', content)

    def test_should_show_the_corporation_at_the_time_in_red(self):
        add_corporation_history(GM_ID, ALPHA_CORP_ID, LONG_AGO)
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        body = table_body(self.client.get(self.url))

        self.assertIn(f'<td class="text-danger">Corp {ALPHA_CORP_ID}</td>', body)

    def test_should_leave_the_filter_out_for_a_single_counterparty(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        response = self.client.get(self.url)

        self.assertNotContains(response, "data-eos-party-filter")

    def test_script_should_filter_only_its_own_table_by_the_ticked_boxes(self):
        script = read_static("gm-transactions.js")

        self.assertIn("DataTable.ext.search.push", script)
        self.assertIn("settings.nTable !== table", script)
        self.assertIn("dataset.eosParty", script)
        self.assertIn("dataTable.draw()", script)

    def test_should_say_so_while_the_job_has_not_run(self):
        with mock.patch.object(run_update_gm_report, "delay") as delay:
            response = self.client.get(self.url)

        delay.assert_called_once_with()
        self.assertContains(response, "data-eos-pending")
        self.assertNotContains(response, "table-eos-tax-gm")

    def test_should_queue_once_while_waiting(self):
        with mock.patch.object(run_update_gm_report, "delay") as delay:
            self.client.get(self.url)
            self.client.get(self.url)

        self.assertEqual(delay.call_count, 1)

    def test_script_should_keep_the_server_order_and_reload_while_pending(self):
        script = read_static("gm-transactions.js")

        self.assertIn("order: []", script)
        self.assertIn("[data-eos-pending]", script)
        self.assertIn("window.location.reload()", script)
