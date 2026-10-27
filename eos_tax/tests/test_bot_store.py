"""The bots page lists as the job stores them, and when the job runs."""

from datetime import datetime
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.db.bot_store import get_stored_reports, store_bot_reports
from eos_tax.models import BotReport, TaxConfiguration
from eos_tax.tasks import (
    queue_bot_reports,
    run_update_alliance,
    run_update_bot_reports,
)
from eos_tax.tests.base import EosTaxTestCase
from eos_tax.views import _previous_and_running_month

from .factories import (
    BRAVO_CORP_ID,
    MONTH,
    RATTER_ID,
    YEAR,
    add_entries,
    build_corporations,
    configure,
    create_user,
    settings_numbers,
)


class TestStoredReports(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.divisions = build_corporations()

    def setUp(self):
        configure()
        for day in (1, 2):
            add_entries(self.divisions[BRAVO_CORP_ID], RATTER_ID, day, (0, 6, 12, 18))

    def test_should_give_back_what_the_job_stored(self):
        store_bot_reports(YEAR, MONTH)

        reports = get_stored_reports(YEAR, MONTH)

        self.assertEqual(set(reports), {"hours", "runs", "rhythm", "clock"})
        self.assertTrue(reports["hours"]["listed"])
        self.assertEqual(
            reports["hours"]["groups"][0]["characters"][0]["character_name"],
            "Busy Ratter",
        )
        self.assertIsNotNone(reports["hours"]["computed_at"])

    def test_should_bring_back_the_times_of_a_run_as_times(self):
        """JSON keeps them as text, which the date filter prints as nothing."""
        store_bot_reports(YEAR, MONTH)

        row = get_stored_reports(YEAR, MONTH, ["runs"])["runs"]["groups"][0]["characters"][0]

        self.assertIsInstance(row["started_at"], datetime)
        self.assertIsInstance(row["ended_at"], datetime)

    def test_should_keep_only_what_the_tab_shows(self):
        """Every scored row of the month would grow the table with the
        alliance, and the fifth tab must not pick from rows no tab shows."""
        store_bot_reports(YEAR, MONTH)

        for report in BotReport.objects.all():
            with self.subTest(signal=report.signal):
                self.assertEqual(set(report.report), {"listed", "groups", "stats"})

    def test_should_treat_a_month_never_computed_as_missing(self):
        self.assertIsNone(get_stored_reports(YEAR, MONTH))

    def test_should_treat_lists_from_other_settings_as_missing(self):
        store_bot_reports(YEAR, MONTH)
        config = TaxConfiguration.get_solo()
        config.bot_run_min_ticks += 1
        config.save()

        self.assertIsNone(get_stored_reports(YEAR, MONTH))

    def test_should_treat_lists_from_another_blacklist_as_missing(self):
        """Not a bot setting, but it decides whose journal is read at all."""
        store_bot_reports(YEAR, MONTH)
        TaxConfiguration.get_solo().corporation_blacklist.add(
            EveCorporationInfo.objects.get(corporation_id=BRAVO_CORP_ID)
        )

        self.assertIsNone(get_stored_reports(YEAR, MONTH))


class TestQueueing(EosTaxTestCase):
    def setUp(self):
        configure()
        self.addCleanup(cache.clear)

    def test_should_queue_a_month_only_once_while_it_runs(self):
        with mock.patch.object(run_update_bot_reports, "delay") as delay:
            queue_bot_reports([(MONTH, YEAR)])
            queue_bot_reports([(MONTH, YEAR)])

        delay.assert_called_once_with(month=MONTH, year=YEAR)

    def test_should_free_the_month_once_the_job_failed(self):
        """A month left locked would wait out the timeout before anyone
        could queue it again."""
        with mock.patch(
            "eos_tax.tasks.store_bot_reports", side_effect=RuntimeError("boom")
        ):
            with mock.patch.object(run_update_bot_reports, "delay"):
                queue_bot_reports([(MONTH, YEAR)])

            with self.assertRaises(RuntimeError):
                run_update_bot_reports(month=MONTH, year=YEAR)

        with mock.patch.object(run_update_bot_reports, "delay") as delay:
            queue_bot_reports([(MONTH, YEAR)])

        delay.assert_called_once()

    def test_should_compute_the_tax_months_with_the_tax_job(self):
        config = TaxConfiguration.get_solo()
        config.last_month = True
        config.current_month = True
        config.save()

        with mock.patch("eos_tax.tasks.queue_corporations"), \
                mock.patch.object(run_update_bot_reports, "delay") as delay:
            run_update_alliance()

        self.assertEqual(
            sorted(call.kwargs["month"] for call in delay.call_args_list),
            sorted(month for month, _year in _previous_and_running_month()),
        )


class TestWhileTheJobRuns(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
        build_corporations()
        configure()

    def setUp(self):
        self.addCleanup(cache.clear)
        self.client.force_login(
            create_user("boss", 94400001, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )
        # no worker: nothing comes back while the page is rendered
        patcher = mock.patch.object(run_update_bot_reports, "delay")
        self.delay = patcher.start()
        self.addCleanup(patcher.stop)
        self.month = {"month": f"{YEAR}-{MONTH:02d}"}

    def test_should_say_so_on_a_fetched_tab(self):
        for signal in ("runs", "audit"):
            with self.subTest(signal=signal):
                response = self.client.get(
                    reverse("eos_tax:bot_signal", args=[signal]), self.month
                )

                self.assertContains(response, "data-eos-pending")

    def test_should_say_so_on_the_first_tab(self):
        response = self.client.get(reverse("eos_tax:bots"), self.month)

        self.assertContains(response, "data-eos-pending")
        self.assertNotContains(response, "hour blocks")

    def test_should_queue_the_month_once_for_every_tab_that_asks(self):
        self.client.get(reverse("eos_tax:bots"), self.month)
        for signal in ("runs", "rhythm", "clock", "audit"):
            self.client.get(reverse("eos_tax:bot_signal", args=[signal]), self.month)

        self.delay.assert_called_once_with(month=MONTH, year=YEAR)


class TestSavingSettings(EosTaxTestCase):
    def setUp(self):
        self.addCleanup(cache.clear)
        self.client.force_login(
            create_user(
                "boss", 94400002, BRAVO_CORP_ID, "Bravo Corp",
                ["admin_view", "manage_settings"],
            )
        )
        self.alliance = EveAllianceInfo.objects.create(
            alliance_id=99000001, alliance_name="Taxed Alliance", alliance_ticker="TAX"
        )
        self.corporation = EveCorporationInfo.objects.create(
            corporation_id=BRAVO_CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRVO",
            alliance=self.alliance,
            tax_rate=0.1,
        )
        # a first save brings the configuration to what the form posts, so
        # the saves below change only what each test changes
        self.post()

    def post(self, **overrides):
        data = {
            **settings_numbers(),
            "tax_alliances": [self.alliance.pk],
            "tax_corporation": self.corporation.pk,
            "corporation_blacklist": [],
            "tax_rate": "10",
            "tax_types": ["bounty_prizes"],
            "last_month": "on",
            "current_month": "on",
            "tax_change_min_points": "0.45",
            "form-TOTAL_FORMS": "0",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)

        return self.client.post(reverse("eos_tax:settings"), data)

    def test_should_recompute_both_months_when_a_bot_setting_changed(self):
        ticks = TaxConfiguration._meta.get_field("bot_run_min_ticks").default

        with mock.patch("eos_tax.views.queue_bot_reports") as queue:
            response = self.post(bot_run_min_ticks=str(ticks + 1))

        self.assertEqual(response.status_code, 302)
        queue.assert_called_once_with(_previous_and_running_month())

    def test_should_leave_the_lists_alone_when_only_the_tax_changed(self):
        with mock.patch("eos_tax.views.queue_bot_reports") as queue:
            response = self.post(tax_rate="12")

        self.assertEqual(response.status_code, 302)
        queue.assert_not_called()
