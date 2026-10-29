"""gm_bots_access: the bots lists and GM Transactions with everything on them,
and nothing else of the app."""

import datetime
import re
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import reverse

from eos_tax import progress
from eos_tax.auth_hooks import EosTaxMenuItem
from eos_tax.models import TaxConfiguration
from eos_tax.tasks import run_update_bot_reports, run_update_gm_report
from eos_tax.tests.base import EosTaxTestCase

from .factories import (
    BRAVO_CORP_ID,
    MONTH,
    TAXED_ALLIANCE_ID,
    YEAR,
    configure,
    create_alliance,
    create_corporation,
    create_tax_row,
    create_user,
    mid_month,
)


class GmBotsTestCase(EosTaxTestCase):
    def setUp(self):
        # the local memory cache outlives a test's transaction
        cache.clear()
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        configure()
        self.hunter = create_user(
            "hunter", 93100001, BRAVO_CORP_ID, "Bravo Corp", ["gm_bots_access"]
        )
        self.client.force_login(self.hunter)


class TestPages(GmBotsTestCase):
    def test_should_open_the_bots_pages(self):
        for name, args in (
            ("bots", []),
            ("bot_signal", ["runs"]),
            ("bot_detail", [93100001]),
            ("bot_signal_detail", ["runs", 93100001]),
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(f"eos_tax:{name}", args=args))

                self.assertEqual(response.status_code, 200)

    def test_should_open_gm_transactions(self):
        response = self.client.get(reverse("eos_tax:gm_transactions"))

        self.assertEqual(response.status_code, 200)

    def test_should_refuse_every_other_page(self):
        for name, args in (
            ("statistics", []),
            ("statistics_data", []),
            ("settings", []),
            ("tax_changes", []),
            ("tax_change_detail", [BRAVO_CORP_ID]),
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(f"eos_tax:{name}", args=args))

                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_should_send_the_overview_on_to_the_bots(self):
        """The menu entry points at the overview, which they may not see."""
        response = self.client.get(reverse("eos_tax:index"))

        self.assertRedirects(response, reverse("eos_tax:bots"))

    def test_should_still_refuse_a_user_without_any_permission(self):
        self.client.force_login(
            create_user("nobody", 93100002, BRAVO_CORP_ID, "Bravo Corp")
        )

        for name in ("index", "bots", "gm_transactions"):
            with self.subTest(page=name):
                response = self.client.get(reverse(f"eos_tax:{name}"))

                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])


class TestNavigation(GmBotsTestCase):
    def nav_bar(self):
        body = self.client.get(reverse("eos_tax:bots")).content.decode()
        return re.search(r'<ul id="nav-left".*?</ul>', body, re.S).group(0)

    def test_should_offer_only_the_two_pages(self):
        navbar = self.nav_bar()
        hrefs = re.findall(r'href="([^"]+)"', navbar)

        self.assertEqual(
            hrefs, [reverse("eos_tax:bots"), reverse("eos_tax:gm_transactions")]
        )

    def test_should_keep_every_entry_for_an_admin(self):
        self.client.force_login(
            create_user(
                "admin", 93100003, BRAVO_CORP_ID, "Bravo Corp",
                ["basic_access", "admin_view"],
            )
        )

        self.assertEqual(len(re.findall(r'href="', self.nav_bar())), 6)

    def test_should_show_the_menu_entry_without_a_badge(self):
        """Not even with a row of their Corporation due - as in TestMenuBadge."""
        self.enterContext(mid_month())
        config = TaxConfiguration.get_solo()
        config.last_month = True
        config.save()
        previous = datetime.datetime.now() - relativedelta(months=1)
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", month=previous.month, year=previous.year)
        request = RequestFactory().get(reverse("eos_tax:bots"))
        request.user = self.hunter
        item = EosTaxMenuItem()

        self.assertNotEqual(item.render(request), "")
        self.assertIsNone(item.count)


class TestWrites(GmBotsTestCase):
    def setUp(self):
        super().setUp()
        # no worker: the run stays queued, the way the button leaves it
        for task in (run_update_bot_reports, run_update_gm_report):
            patcher = patch.object(task, "delay")
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_should_offer_the_recalculate_buttons(self):
        for name in ("bots", "gm_transactions"):
            with self.subTest(page=name):
                response = self.client.get(reverse(f"eos_tax:{name}"))

                self.assertContains(response, "data-eos-recalculate-url")

    def test_should_queue_both_jobs(self):
        bots = self.client.post(
            reverse("eos_tax:bots_recalculate"), {"month": f"{YEAR}-{MONTH:02d}"}
        )
        gm = self.client.post(reverse("eos_tax:gm_transactions_recalculate"))

        self.assertEqual((bots.json(), gm.json()), ({"queued": True}, {"queued": True}))

    def test_should_let_the_note_through_to_its_own_checks(self):
        """A 400 for the bad id, not the 403 of the permission."""
        response = self.client.post(
            reverse("eos_tax:gm_transactions_note"),
            {"character_id": "x", "entry_id": "0", "text": ""},
        )

        self.assertEqual(response.status_code, 400)


class TestProgress(GmBotsTestCase):
    def finished_run(self, kind):
        run_id = progress.start_run(kind, [{"step": "hours"}])
        progress.set_job(run_id, progress.get_runs()[-1]["jobs"][0]["id"], progress.DONE)
        return run_id

    def test_should_show_only_the_bots_and_gm_runs(self):
        progress.start_run(progress.AUTOMATIC, [{"step": "hours"}])
        bots = progress.start_run(progress.BOTS, [{"step": "hours"}])
        gm = progress.start_run(progress.GM, [{"step": "hours"}])

        runs = self.client.get(reverse("eos_tax:progress")).json()["runs"]

        self.assertEqual([run["id"] for run in runs], [bots, gm])

    def test_should_show_an_admin_every_run(self):
        progress.start_run(progress.AUTOMATIC, [{"step": "hours"}])
        self.client.force_login(
            create_user("admin", 93100004, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        runs = self.client.get(reverse("eos_tax:progress")).json()["runs"]

        self.assertEqual(len(runs), 1)

    def test_should_dismiss_a_finished_gm_run(self):
        run_id = self.finished_run(progress.GM)

        response = self.client.post(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 200)

    def test_should_not_dismiss_a_tax_run(self):
        run_id = self.finished_run(progress.MANUAL)

        response = self.client.post(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 403)
        self.assertEqual([run["id"] for run in progress.get_runs()], [run_id])
