"""The GM transactions page: GM bookings and wallets below zero."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from corptools.models import CharacterAudit

from eos_tax.db.gm_transactions import (
    FLAGGED_PARTY,
    _parties_of,
    clean_note,
    find_account_in_alliance,
    find_gm_transactions,
    find_in_alliance,
    get_gm_page,
    get_stored_gm_report,
    sides,
    store_gm_report,
)
from eos_tax.models import GM_NOTE_LENGTH, GmNote, GmReport
from eos_tax.tasks import GM_REPORT_LOCK, run_update_gm_report
from eos_tax.tests.base import EosTaxTestCase, read_static, table_body

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    LONG_AGO,
    OTHER_ALLIANCE_ID,
    OUTSIDER_CORP_ID,
    TAXED_ALLIANCE_ID,
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
MAIN_ID = 2100000105
ALT_ID = 2100000106
STRANGER_ID = 2100000107

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
        # unknown, not "left"
        self.assertIsNone(row["in_alliance"])

    def test_should_take_the_alliance_membership_from_the_job(self):
        """As of the calculation, for a wallet below zero as much as for a
        transaction."""
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()
        EveCharacter.objects.filter(character_id__in=[GM_ID, BROKE_ID]).update(
            alliance_id=TAXED_ALLIANCE_ID
        )
        store_gm_report()
        # left after the job ran: the page still shows the job's answer
        EveCharacter.objects.filter(character_id=GM_ID).update(alliance_id=None)

        rows = {row["character_id"]: row for row in get_gm_page(get_stored_gm_report())["rows"]}

        self.assertIs(rows[GM_ID]["in_alliance"], True)
        self.assertIs(rows[BROKE_ID]["in_alliance"], True)

    def test_should_take_the_whole_account_from_the_job(self):
        """Out of the alliance on this character, still in on the main."""
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        user = create_user("vaseline", MAIN_ID, BRAVO_CORP_ID, "Bravo Corp")
        CharacterOwnership.objects.create(
            character=self.gm.character, user=user, owner_hash="gm-owner-hash"
        )
        EveCharacter.objects.filter(character_id=MAIN_ID).update(
            alliance_id=TAXED_ALLIANCE_ID
        )

        row = self.page()["rows"][0]

        self.assertIs(row["in_alliance"], True)

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


class TestInAlliance(GmTestCase):
    """Alliance Auth's character against corptools' history, the newer wins."""

    def setUp(self):
        super().setUp()
        self.config = configure()

    def character(self, character_id, alliance_id, updated):
        if character_id != GM_ID:
            add_character_audit(character_id, True)
        EveCharacter.objects.filter(character_id=character_id).update(
            alliance_id=alliance_id, last_updated_affiliations=updated
        )

    def test_should_take_alliance_auth_without_a_history(self):
        self.character(GM_ID, TAXED_ALLIANCE_ID, _at(1))
        self.character(BROKE_ID, OTHER_ALLIANCE_ID, _at(1))
        self.character(DEEPER_ID, None, None)

        self.assertEqual(
            find_in_alliance([GM_ID, BROKE_ID, DEEPER_ID], self.config),
            {GM_ID: True, BROKE_ID: False, DEEPER_ID: False},
        )

    def test_should_take_the_history_when_it_is_newer(self):
        # Alliance Auth still has the old alliance; the move came after
        self.character(GM_ID, TAXED_ALLIANCE_ID, _at(1))
        add_corporation_history(GM_ID, BRAVO_CORP_ID, LONG_AGO)
        add_corporation_history(GM_ID, OUTSIDER_CORP_ID, _at(2))
        # and the way back in
        self.character(BROKE_ID, OTHER_ALLIANCE_ID, _at(1))
        add_corporation_history(BROKE_ID, BRAVO_CORP_ID, _at(2))

        self.assertEqual(
            find_in_alliance([GM_ID, BROKE_ID], self.config),
            {GM_ID: False, BROKE_ID: True},
        )

    def test_should_take_alliance_auth_when_it_is_newer_or_as_new(self):
        self.character(GM_ID, OTHER_ALLIANCE_ID, _at(3))
        add_corporation_history(GM_ID, BRAVO_CORP_ID, _at(2))
        # looked at the very second the record starts: it saw the move
        self.character(BROKE_ID, TAXED_ALLIANCE_ID, _at(2))
        add_corporation_history(BROKE_ID, OUTSIDER_CORP_ID, _at(2))

        self.assertEqual(
            find_in_alliance([GM_ID, BROKE_ID], self.config),
            {GM_ID: False, BROKE_ID: True},
        )

    def test_should_take_the_history_when_alliance_auth_never_updated(self):
        self.character(GM_ID, TAXED_ALLIANCE_ID, None)
        add_corporation_history(GM_ID, OUTSIDER_CORP_ID, LONG_AGO)

        self.assertEqual(find_in_alliance([GM_ID], self.config), {GM_ID: False})

    def test_should_count_a_corporation_that_left_as_out(self):
        """Its tax rows keep it under "Corporations in the Alliance"; its
        members are out all the same."""
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp")
        self.character(GM_ID, TAXED_ALLIANCE_ID, _at(1))
        add_corporation_history(GM_ID, ALPHA_CORP_ID, _at(2))

        self.assertEqual(find_in_alliance([GM_ID], self.config), {GM_ID: False})

    def test_should_leave_out_a_character_nobody_knows(self):
        self.assertEqual(find_in_alliance([CLEAN_ID], self.config), {})


class TestAccountInAlliance(GmTestCase):
    """Any character of the account in the alliance counts for each of them."""

    def setUp(self):
        super().setUp()
        self.config = configure()
        user = create_user("vaseline", MAIN_ID, BRAVO_CORP_ID, "Bravo Corp")
        create_alt(user, ALT_ID, "Vaseline Alt")

    def alliance(self, character_id, alliance_id):
        EveCharacter.objects.filter(character_id=character_id).update(
            alliance_id=alliance_id, last_updated_affiliations=_at(1)
        )

    def test_should_count_the_account_in_when_another_character_is(self):
        self.alliance(MAIN_ID, OTHER_ALLIANCE_ID)
        self.alliance(ALT_ID, TAXED_ALLIANCE_ID)

        self.assertEqual(
            find_account_in_alliance([MAIN_ID, ALT_ID], self.config),
            {MAIN_ID: True, ALT_ID: True},
        )

    def test_should_count_the_account_out_when_every_character_is(self):
        self.alliance(MAIN_ID, OTHER_ALLIANCE_ID)
        self.alliance(ALT_ID, None)

        self.assertEqual(
            find_account_in_alliance([ALT_ID], self.config), {ALT_ID: False}
        )

    def test_should_not_borrow_from_another_account(self):
        create_user("stranger", STRANGER_ID, BRAVO_CORP_ID, "Bravo Corp")
        self.alliance(STRANGER_ID, TAXED_ALLIANCE_ID)
        # nobody owns the GM's character: an account of its own
        self.alliance(GM_ID, None)

        self.assertEqual(
            find_account_in_alliance([GM_ID, MAIN_ID], self.config),
            {GM_ID: False, MAIN_ID: False},
        )

    def test_should_leave_out_an_account_nobody_knows(self):
        self.assertEqual(find_account_in_alliance([CLEAN_ID], self.config), {})


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

    def test_should_show_the_note_second_and_age_and_main_after_the_character(self):
        """Header and cells move together - one without the other puts every
        value under the wrong title."""
        EveCharacter.objects.filter(character_id=GM_ID).update(
            birthday=date.today() - timedelta(days=400)
        )
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        response = self.client.get(self.url)
        header = response.content.decode().split("<thead>")[1].split("</thead>")[0]
        titles = [cell.split(">", 1)[1].split("<", 1)[0] for cell in header.split("<th ")[1:]]
        before_character, after_character = table_body(response).split("</th>", 1)
        cells = after_character.split("</td>")

        self.assertEqual(
            titles[:7],
            ["In the Alliance", "Note", "Date", "Character", "Age", "Main", "Corporation"],
        )
        self.assertNotIn("Transaction for", titles)
        self.assertIn("data-eos-note-character", before_character.split("</td>")[1])
        self.assertIn(_at(3).strftime("%Y-%m-%d %H:%M"), before_character.split("</td>")[2])
        self.assertIn('data-order="400">1 y', cells[0])
        self.assertIn("not registered", cells[1])

    def test_should_show_the_corporations_in_the_alliance_before_the_alliance(self):
        EveCharacter.objects.filter(character_id=GM_ID).update(alliance_name="Ours")
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))

        response = self.client.get(self.url)
        header = response.content.decode().split("<thead>")[1].split("</thead>")[0]
        titles = [cell.split(">", 1)[1].split("<", 1)[0] for cell in header.split("<th ")[1:]]
        cells = table_body(response).split("</th>", 1)[1].split("</td>")

        self.assertEqual(titles[8:10], ["Corporations in the Alliance", "Alliance"])
        # after the Character: Age, Main, Corporation, at the time, then these two
        self.assertIn('class="d-none d-lg-table-cell">', cells[4])
        self.assertIn('class="d-none d-md-table-cell">Ours', cells[5])

    def test_should_show_isk_as_whole_numbers_and_sort_by_the_exact_value(self):
        self.gm.balance = Decimal("1500.49")
        self.gm.save()
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1234567.89"), _at(3))

        body = table_body(self.client.get(self.url))

        self.assertIn('data-order="-1234567.89">-1,234,568</td>', body)
        self.assertIn('data-order="1500.49">1,500</td>', body)

    def test_should_warn_only_for_a_character_still_in_the_alliance(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()
        EveCharacter.objects.filter(character_id=GM_ID).update(
            alliance_id=TAXED_ALLIANCE_ID
        )

        rows = table_body(self.client.get(self.url)).split("</tr>")

        # the first cell of each row, the transaction before the wallet
        self.assertIn('data-order="1"', rows[0].split("</td>")[0])
        self.assertIn(
            '<i class="fa-solid fa-circle-exclamation text-danger" aria-hidden="true"></i>',
            rows[0].split("</td>")[0],
        )
        self.assertIn('<td data-order="0">', rows[1].split("</td>")[0])
        self.assertNotIn("fa-circle-exclamation", rows[1])

    def test_should_show_a_dash_when_the_job_did_not_look(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        GmReport.objects.create(
            pk=1,
            report={"transactions": find_gm_transactions()},
            computed_at=_at(4),
        )

        first_cell = table_body(self.client.get(self.url)).split("</td>")[0]

        self.assertIn('data-order="">&mdash;', first_cell)

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

    def test_should_tick_only_gm_x_and_mark_it_red(self):
        add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        add_wallet_entry(self.gm, BANK_TEXT, Decimal("-2"), _at(4))

        content = self.client.get(self.url).content.decode()
        boxes = content.split("data-eos-party-filter", 1)[1].split("</fieldset>", 1)[0]
        gm_box, bank_box = (
            boxes.split(f'value="{name}"', 1)[0].rsplit("<input", 1)[1]
            for name in ("GM X", "EVE Central Bank")
        )

        self.assertIn("checked", gm_box)
        self.assertNotIn("checked", bank_box)
        self.assertIn('class="form-check-label text-danger fw-semibold"', boxes)
        self.assertEqual(boxes.count("text-danger"), 1)

    def test_script_should_start_from_the_ticked_boxes(self):
        """Started from every box, the script would show the rows of the
        unticked ones until the first click."""
        script = read_static("gm-transactions.js")

        self.assertIn("let shownParties = ticked();", script)
        self.assertIn("return each.checked;", script)
        self.assertLess(
            script.index("dataTable.draw();"), script.index('addEventListener("change"')
        )

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

        delay.assert_called_once_with(run_id=mock.ANY)
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


class TestFlaggedParty(EosTaxTestCase):
    """_parties_of on hand-built rows: GM X alone ticked when it is there."""

    def parties(self, *names):
        return [
            (party["name"], party["checked"], party["flagged"])
            for party in _parties_of([{"counterparty": name} for name in names])
        ]

    def test_should_tick_only_gm_x_when_it_is_there(self):
        self.assertEqual(FLAGGED_PARTY, "GM X")
        self.assertEqual(
            self.parties("EVE Central Bank", "GM X", "GM Y", ""),
            [("EVE Central Bank", False, False), ("GM X", True, True),
             ("GM Y", False, False), ("", False, False)],
        )

    def test_should_tick_every_box_without_gm_x(self):
        self.assertEqual(
            self.parties("EVE Central Bank", "GM Y", ""),
            [("EVE Central Bank", True, False), ("GM Y", True, False), ("", True, False)],
        )

    def test_should_match_the_name_exactly(self):
        """The user's choice: "GM X" itself, not every GM."""
        self.assertEqual(
            self.parties("gm x", "GM Xavier"),
            [("gm x", True, False), ("GM Xavier", True, False)],
        )


class TestCleanNote(EosTaxTestCase):
    def test_should_trim_and_keep_line_breaks(self):
        self.assertEqual(clean_note("  paid back\r\nsee ticket  "), "paid back\nsee ticket")

    def test_should_drop_control_and_direction_characters(self):
        """A right-to-left override would make the tooltip read backwards."""
        self.assertEqual(clean_note("paid\u202e 5\x00\u200b\t"), "paid 5")

    def test_should_keep_markup_as_text(self):
        """Escaping is the template's job - the note keeps what was typed."""
        self.assertEqual(clean_note("<b>x</b>"), "<b>x</b>")

    def test_should_refuse_more_than_the_limit(self):
        self.assertEqual(len(clean_note("x" * GM_NOTE_LENGTH)), GM_NOTE_LENGTH)

        with self.assertRaises(ValueError):
            clean_note("x" * (GM_NOTE_LENGTH + 1))


class TestGmNotes(GmTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user(
            "admin", 2100000198, BRAVO_CORP_ID, "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)
        self.url = reverse("eos_tax:gm_transactions")
        self.note_url = reverse("eos_tax:gm_transactions_note")
        self.first = add_wallet_entry(self.gm, GM_TEXT, Decimal("-1"), _at(3))
        self.second = add_wallet_entry(self.gm, BANK_TEXT, Decimal("-2"), _at(4))
        store_gm_report()

    def tearDown(self):
        cache.clear()

    def save(self, text, entry_id=None, character_id=GM_ID):
        return self.client.post(self.note_url, {
            "character_id": character_id,
            "entry_id": self.first.entry_id if entry_id is None else entry_id,
            "text": text,
        })

    def note_cells(self):
        """The second cell of each row, the newest transaction first."""
        return [
            row.split("</td>")[1]
            for row in table_body(self.client.get(self.url)).split("</tr>")[:-1]
        ]

    def test_should_store_the_note_of_one_row_only(self):
        response = self.save("refund asked")

        self.assertEqual(response.json(), {"text": "refund asked"})
        second, first = self.note_cells()
        self.assertIn('title="refund asked"', first)
        self.assertIn('data-eos-note="refund asked"', first)
        self.assertIn('title="Add a note"', second)
        self.assertEqual(GmNote.objects.get().updated_by, self.user)

    def test_should_replace_the_note_and_remove_it_when_empty(self):
        self.save("first")
        self.save("second")

        self.assertEqual(GmNote.objects.get().text, "second")

        self.assertEqual(self.save("   ").json(), {"text": ""})
        self.assertFalse(GmNote.objects.exists())

    def test_should_escape_the_note_on_the_page(self):
        self.save('"><script>alert(1)</script>')

        cell = self.note_cells()[1]

        self.assertNotIn("<script>", cell)
        self.assertIn("&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;", cell)

    def test_should_answer_with_the_cleaned_note(self):
        """The page shows what was stored, not what was typed."""
        self.assertEqual(self.save(" a\u202eb ").json(), {"text": "ab"})

    def test_should_refuse_a_note_over_the_limit(self):
        response = self.save("x" * (GM_NOTE_LENGTH + 1))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(GmNote.objects.exists())

    def test_should_refuse_a_row_the_page_does_not_list(self):
        self.assertEqual(self.save("x", entry_id=999999).status_code, 400)
        # the wallet row of a character whose wallet is not below zero
        self.assertEqual(self.save("x", entry_id=0).status_code, 400)
        self.assertEqual(self.save("x", entry_id="abc").status_code, 400)
        self.assertFalse(GmNote.objects.exists())

    def test_should_note_a_wallet_below_zero_without_a_transaction(self):
        broke = add_character_audit(BROKE_ID, True, name="Broke Pilot")
        broke.balance = Decimal("-10.00")
        broke.save()

        self.assertEqual(self.save("owes", entry_id=0, character_id=BROKE_ID).status_code, 200)

        self.assertIn('title="owes"', self.note_cells()[2])

    def test_should_refuse_without_admin_view(self):
        user = create_user("basic", 2100000197, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        self.client.force_login(user)

        self.assertEqual(self.save("x").status_code, 403)
        self.assertFalse(GmNote.objects.exists())

    def test_should_refuse_a_get(self):
        self.assertEqual(self.client.get(self.note_url).status_code, 405)

    def test_should_offer_the_popup_with_save_and_cancel(self):
        body = self.client.get(self.url).content.decode()
        popup = body.split('id="eos-tax-gm-note"')[1].split("</textarea>")[0]

        self.assertIn(f'maxlength="{GM_NOTE_LENGTH}"', popup)
        self.assertIn("data-eos-note-save", body)
        self.assertIn('data-bs-dismiss="modal">', body)
        self.assertIn(f'data-eos-note-url="{self.note_url}"', body)

    def test_script_should_handle_the_note_as_text_only(self):
        script = read_static("gm-transactions.js")

        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)
        self.assertIn("textContent = button.dataset.eosNoteName", script)
        self.assertIn("button.title = data.text", script)
