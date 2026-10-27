"""The progress bar of the recalculation runs: what the tasks record, what
the endpoint hands the page, and the page parts that show it."""

from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse

from eos_tax import progress
from eos_tax.db.bot_store import READINGS
from eos_tax.db.gm_transactions import GM_STEPS
from eos_tax.tasks import (
    BOT_REPORT_LOCK,
    GM_REPORT_LOCK,
    queue_bot_reports,
    queue_corporations,
    queue_gm_report,
    run_update_alliance,
    run_update_bot_reports,
    run_update_corporation,
    run_update_gm_report,
)
from eos_tax.tests.base import EosTaxTestCase, read_static

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    MONTH,
    YEAR,
    OTHER_ALLIANCE_ID,
    OUTSIDER_CORP_ID,
    TAXED_ALLIANCE_ID,
    configure,
    create_alliance,
    create_corporation,
    create_user,
)


def two_jobs():
    return [
        {"corp_id": BRAVO_CORP_ID, "corp_name": "Bravo Corp", "month": 9, "year": 2026},
        {"corp_id": ALPHA_CORP_ID, "corp_name": "Alpha Corp", "month": 9, "year": 2026},
    ]


class ProgressTestCase(EosTaxTestCase):
    def setUp(self):
        # the local memory cache outlives a test's transaction
        cache.clear()


class TestRunRecord(ProgressTestCase):
    """progress.py on its own: a run, its jobs and their states."""

    def only_run(self):
        runs = progress.get_runs()
        self.assertEqual(len(runs), 1)

        return runs[0]

    def test_should_start_every_job_as_queued(self):
        progress.start_run(progress.MANUAL, two_jobs())

        run = self.only_run()

        self.assertEqual(run["kind"], progress.MANUAL)
        self.assertEqual([job["state"] for job in run["jobs"]], ["queued", "queued"])
        self.assertEqual((run["finished"], run["total"], run["percent"]), (0, 2, 0))
        self.assertFalse(run["complete"])

    def test_should_keep_the_state_of_jobs_finishing_side_by_side(self):
        run_id = progress.start_run(progress.AUTOMATIC, two_jobs())

        with progress.tracked(run_id, BRAVO_CORP_ID, 9, 2026) as outcome:
            outcome["result"] = {"ok": True}
        with progress.tracked(run_id, ALPHA_CORP_ID, 9, 2026) as outcome:
            outcome["result"] = {"ok": True}

        run = self.only_run()

        self.assertEqual([job["state"] for job in run["jobs"]], ["done", "done"])
        self.assertEqual(run["percent"], 100)
        self.assertTrue(run["complete"])

    def test_should_show_a_job_as_running_inside_the_block(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        with progress.tracked(run_id, BRAVO_CORP_ID, 9, 2026):
            states = [job["state"] for job in self.only_run()["jobs"]]

        self.assertEqual(states, ["running", "queued"])

    def test_should_count_a_calculation_with_nothing_to_do_as_skipped(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        with progress.tracked(run_id, BRAVO_CORP_ID, 9, 2026) as outcome:
            outcome["result"] = {"ok": False, "reason": "no_entries"}

        job = self.only_run()["jobs"][0]

        self.assertEqual((job["state"], job["detail"]), ("skipped", "no_entries"))

    def test_should_mark_a_job_failed_and_raise_on(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        with self.assertRaises(ValueError):
            with progress.tracked(run_id, BRAVO_CORP_ID, 9, 2026):
                raise ValueError("journal broken")

        run = self.only_run()

        self.assertEqual(run["jobs"][0]["state"], "failed")
        self.assertIn("journal broken", run["jobs"][0]["detail"])
        self.assertEqual(run["counts"]["failed"], 1)

    def test_should_ignore_a_job_queued_without_a_run(self):
        # a subtask from before the upgrade, still in the broker
        with progress.tracked(None, BRAVO_CORP_ID, 9, 2026) as outcome:
            outcome["result"] = {"ok": True}

        self.assertEqual(progress.get_runs(), [])

    def test_should_drop_an_expired_run_from_the_index(self):
        expired = progress.start_run(progress.MANUAL, two_jobs())
        kept = progress.start_run(progress.MANUAL, two_jobs())
        cache.delete(progress._run_key(expired))

        self.assertEqual([run["id"] for run in progress.get_runs()], [kept])
        self.assertEqual(cache.get(progress.INDEX_KEY), [kept])

    def test_should_keep_both_runs_when_two_start(self):
        first = progress.start_run(progress.AUTOMATIC, two_jobs())
        second = progress.start_run(progress.MANUAL, two_jobs())

        self.assertEqual([run["id"] for run in progress.get_runs()], [first, second])

    def test_should_take_a_withdrawn_run_off(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        progress.withdraw(run_id)

        self.assertEqual(progress.get_runs(), [])


class TestTasks(ProgressTestCase):
    """The tasks register what they queue and report how it went."""

    def setUp(self):
        super().setUp()
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        other = create_alliance(OTHER_ALLIANCE_ID, "Other Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        create_corporation(OUTSIDER_CORP_ID, "Outsider Corp", other)
        configure()

    def test_should_register_the_periodic_run_with_every_corporation_and_month(self):
        dates = [(8, 2026), (9, 2026)]

        with patch("eos_tax.tasks.get_dates", return_value=dates), \
                patch("eos_tax.tasks.run_update_corporation.delay") as delay:
            run_update_alliance()

        run = progress.get_runs()[0]

        self.assertEqual(run["kind"], progress.AUTOMATIC)
        self.assertEqual(
            [(job["corp_name"], job["month"]) for job in run["jobs"]],
            [("Bravo Corp", 8), ("Bravo Corp", 9)],
        )
        self.assertEqual(delay.call_count, 2)
        delay.assert_any_call(corp_id=BRAVO_CORP_ID, month=8, year=2026, run_id=run["id"])

    def test_should_take_the_run_off_when_the_broker_is_down(self):
        with patch("eos_tax.tasks.run_update_corporation.delay", side_effect=OSError("broker")):
            with self.assertRaises(OSError):
                queue_corporations([(BRAVO_CORP_ID, "Bravo Corp")], [(9, 2026)], progress.MANUAL)

        self.assertEqual(progress.get_runs(), [])

    def test_should_report_the_subtask_done(self):
        run_id = progress.start_run(progress.AUTOMATIC, two_jobs()[:1])

        with patch("eos_tax.tasks.update_corp", return_value={"ok": True}):
            run_update_corporation(corp_id=BRAVO_CORP_ID, month=9, year=2026, run_id=run_id)

        self.assertEqual(progress.get_runs()[0]["jobs"][0]["state"], "done")

    def test_should_report_the_subtask_failed(self):
        run_id = progress.start_run(progress.AUTOMATIC, two_jobs()[:1])

        with patch("eos_tax.tasks.update_corp", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_update_corporation(corp_id=BRAVO_CORP_ID, month=9, year=2026, run_id=run_id)

        self.assertEqual(progress.get_runs()[0]["jobs"][0]["state"], "failed")


class TestEndpoints(ProgressTestCase):
    """The JSON the bar polls, and taking a finished run off."""

    def setUp(self):
        super().setUp()
        self.client.force_login(
            create_user(
                "boss", 93000051, BRAVO_CORP_ID, "Bravo Corp",
                ["basic_access", "admin_view", "manage_settings"],
            )
        )

    def finished_run(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs()[:1])
        with progress.tracked(run_id, BRAVO_CORP_ID, 9, 2026) as outcome:
            outcome["result"] = {"ok": True}

        return run_id

    def test_should_hand_out_the_runs(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        data = self.client.get(reverse("eos_tax:progress")).json()

        self.assertIn("now", data)
        self.assertEqual([run["id"] for run in data["runs"]], [run_id])
        self.assertEqual(data["runs"][0]["jobs"][1]["corp_name"], "Alpha Corp")

    def test_should_refuse_a_member(self):
        self.client.force_login(
            create_user("member", 93000052, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:progress"))

        self.assertEqual(response.status_code, 302)

    def test_should_dismiss_a_finished_run(self):
        run_id = self.finished_run()

        response = self.client.post(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(progress.get_runs(), [])

    def test_should_not_dismiss_for_admin_view_alone(self):
        """Taking a run off hides it from every admin, so it is a write."""
        run_id = self.finished_run()
        self.client.force_login(
            create_user("auditor", 93000055, BRAVO_CORP_ID, "Bravo Corp", ["basic_access", "admin_view"])
        )

        response = self.client.post(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(progress.get_runs()), 1)

    def test_should_not_dismiss_a_run_still_going(self):
        run_id = progress.start_run(progress.MANUAL, two_jobs())

        response = self.client.post(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(progress.get_runs()), 1)

    def test_should_reject_dismissing_by_get(self):
        run_id = self.finished_run()

        response = self.client.get(reverse("eos_tax:progress_dismiss", args=[run_id]))

        self.assertEqual(response.status_code, 405)


class TestRecalculateButton(ProgressTestCase):
    """The settings page's runs show up on the bar like the periodic one."""

    def setUp(self):
        super().setUp()
        self.client.force_login(
            create_user(
                "boss", 93000053, BRAVO_CORP_ID, "Bravo Corp",
                ["basic_access", "admin_view", "manage_settings"],
            )
        )
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        configure()

    def post(self, **data):
        return self.client.post(reverse("eos_tax:settings_recalculate"), data)

    def test_should_register_recalculating_all_as_a_manual_run(self):
        with patch("eos_tax.tasks.run_update_corporation.delay"):
            self.post(corp_id="all", month="9", year="2026")

        run = progress.get_runs()[0]

        self.assertEqual(run["kind"], progress.MANUAL)
        self.assertEqual([(job["corp_name"], job["month"], job["year"]) for job in run["jobs"]],
                         [("Bravo Corp", 9, 2026)])

    def test_should_register_one_corporation_as_a_finished_run_of_one(self):
        self.post(corp_id=str(BRAVO_CORP_ID), month="9", year="2026")

        run = progress.get_runs()[0]

        self.assertEqual(run["total"], 1)
        # no journal in this test: update_corp skips it for want of entries
        self.assertEqual(run["jobs"][0]["state"], "skipped")
        self.assertTrue(run["complete"])


class TestPageParts(ProgressTestCase):
    """The bar is on every page for admins and nowhere for members."""

    def setUp(self):
        super().setUp()
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        configure()

    def page(self, permissions, name="eos_tax:index"):
        self.client.force_login(
            create_user("viewer", 93000054, BRAVO_CORP_ID, "Bravo Corp", permissions)
        )

        return self.client.get(reverse(name)).content.decode()

    def test_should_show_the_bar_to_an_admin(self):
        body = self.page(["basic_access", "admin_view"])

        self.assertIn('id="eos-tax-progress"', body)
        self.assertIn("eos_tax/js/progress.", body)

    def test_should_offer_dismiss_only_with_manage_settings(self):
        # the script adds the Dismiss button only when the url is there
        viewer = self.page(["basic_access", "admin_view"])
        self.client.force_login(
            create_user(
                "manager", 93000056, BRAVO_CORP_ID, "Bravo Corp",
                ["basic_access", "admin_view", "manage_settings"],
            )
        )
        managing = self.client.get(reverse("eos_tax:index")).content.decode()

        self.assertNotIn("data-eos-tax-progress-dismiss-url", viewer)
        self.assertIn("data-eos-tax-progress-dismiss-url", managing)
        self.assertIn('label("progress-dismiss-url")', read_static("progress.js"))

    def test_should_not_show_the_bar_to_a_member(self):
        body = self.page(["basic_access"])

        self.assertNotIn('id="eos-tax-progress"', body)
        self.assertNotIn("eos_tax/js/progress.", body)

    def test_should_keep_the_page_scripts_next_to_the_bar(self):
        # the pages moved their scripts into a block inside the base's own;
        # a page that still overrode extra_javascript would drop one of them
        overview = self.page(["basic_access", "admin_view"])
        settings_page = self.client.get(reverse("eos_tax:settings")).content.decode()

        self.assertIn("eos_tax/js/overview.", overview)
        self.assertIn("eos_tax/js/progress.", settings_page)
        self.assertIn("eos_tax/js/settings.", settings_page)

    def test_should_poll_again_after_the_recalculate_button(self):
        self.assertIn('"eos-tax:progress-poll"', read_static("settings.js"))
        self.assertIn('"eos-tax:progress-poll"', read_static("progress.js"))


def failing(*args):
    raise RuntimeError("boom")


class TestStepRuns(ProgressTestCase):
    """The bots and GM jobs show up step by step, however they were queued."""

    def setUp(self):
        super().setUp()
        configure()

    def only_run(self):
        runs = progress.get_runs()
        self.assertEqual(len(runs), 1)

        return runs[0]

    def states(self):
        return [(job["step"], job["state"]) for job in self.only_run()["jobs"]]

    def test_should_register_the_bots_job_as_its_four_readings(self):
        with patch.object(run_update_bot_reports, "delay") as delay:
            queue_bot_reports([(MONTH, YEAR)])

        run = self.only_run()

        self.assertEqual(run["kind"], progress.BOTS)
        self.assertEqual(run["period"], f"{YEAR}-{MONTH:02d}")
        self.assertEqual(
            [job["step"] for job in run["jobs"]],
            ["hours", "runs", "rhythm", "clock"],
        )
        delay.assert_called_once_with(month=MONTH, year=YEAR, run_id=run["id"])

    def test_should_mark_every_reading_done(self):
        # EosTaxTestCase runs the job in place
        queue_bot_reports([(MONTH, YEAR)])

        self.assertEqual(self.states(), [(step, "done") for step in READINGS])
        self.assertTrue(self.only_run()["complete"])

    def test_should_skip_the_readings_after_a_failed_one(self):
        """Left queued they would keep the bar polling for an hour."""
        with patch.object(run_update_bot_reports, "delay"):
            queue_bot_reports([(MONTH, YEAR)])
        run = self.only_run()

        with patch.dict("eos_tax.db.bot_store.READINGS", {"runs": failing}):
            with self.assertRaises(RuntimeError):
                run_update_bot_reports(month=MONTH, year=YEAR, run_id=run["id"])

        self.assertEqual(self.states(), [
            ("hours", "done"), ("runs", "failed"),
            ("rhythm", "skipped"), ("clock", "skipped"),
        ])
        self.assertEqual(self.only_run()["jobs"][2]["detail"], progress.STEP_FAILED)
        self.assertTrue(self.only_run()["complete"])

    def test_should_register_the_gm_job_as_its_steps(self):
        queue_gm_report()

        run = self.only_run()

        self.assertEqual((run["kind"], run["period"]), (progress.GM, ""))
        self.assertEqual(self.states(), [(step, "done") for step in GM_STEPS])

    def test_should_skip_the_gm_steps_after_the_journal_search_failed(self):
        with patch.object(run_update_gm_report, "delay"):
            queue_gm_report()
        run = self.only_run()

        with patch("eos_tax.db.gm_transactions.find_gm_transactions", side_effect=failing):
            with self.assertRaises(RuntimeError):
                run_update_gm_report(run_id=run["id"])

        self.assertEqual(self.states(), [("transactions", "failed"), ("characters", "skipped")])

    def test_should_not_register_a_job_already_queued(self):
        with patch.object(run_update_bot_reports, "delay"), \
                patch.object(run_update_gm_report, "delay"):
            self.assertEqual(queue_bot_reports([(MONTH, YEAR)]), 1)
            self.assertEqual(queue_bot_reports([(MONTH, YEAR)]), 0)
            self.assertTrue(queue_gm_report())
            self.assertFalse(queue_gm_report())

        self.assertEqual(len(progress.get_runs()), 2)

    def test_should_take_the_run_off_and_free_the_lock_when_the_broker_is_down(self):
        """Otherwise the button would answer "already being calculated" for
        fifteen minutes about a job nobody ever got."""
        for task, queue, lock in (
            (run_update_bot_reports, lambda: queue_bot_reports([(MONTH, YEAR)]),
             BOT_REPORT_LOCK.format(year=YEAR, month=MONTH)),
            (run_update_gm_report, queue_gm_report, GM_REPORT_LOCK),
        ):
            with self.subTest(task=task.name):
                with patch.object(task, "delay", side_effect=OSError("broker")):
                    with self.assertRaises(OSError):
                        queue()

                self.assertEqual(progress.get_runs(), [])
                self.assertIsNone(cache.get(lock))

    def test_should_read_a_run_stored_without_a_period(self):
        """Runs the version before left in the cache have none."""
        run_id = progress.start_run(progress.MANUAL, two_jobs())
        key = f"{progress.PREFIX}:run:{run_id}"
        stored = cache.get(key)
        del stored["period"]
        cache.set(key, stored)

        self.assertEqual(self.only_run()["period"], "")


class TestJobButtons(ProgressTestCase):
    """The recalculate buttons of the bots page and GM Transactions."""

    def setUp(self):
        super().setUp()
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        configure()
        self.manager = create_user(
            "boss", 93000057, BRAVO_CORP_ID, "Bravo Corp",
            ["basic_access", "admin_view", "manage_settings"],
        )
        self.viewer = create_user(
            "auditor", 93000059, BRAVO_CORP_ID, "Bravo Corp", ["basic_access", "admin_view"]
        )
        self.client.force_login(self.manager)
        # no worker: the run stays queued, the way the button leaves it
        for task in (run_update_bot_reports, run_update_gm_report):
            patcher = patch.object(task, "delay")
            patcher.start()
            self.addCleanup(patcher.stop)

    def post_bots(self, month=f"{YEAR}-{MONTH:02d}"):
        return self.client.post(reverse("eos_tax:bots_recalculate"), {"month": month})

    def post_gm(self):
        return self.client.post(reverse("eos_tax:gm_transactions_recalculate"))

    def test_should_queue_the_month_once(self):
        first = self.post_bots().json()
        second = self.post_bots().json()

        self.assertEqual((first, second), ({"queued": True}, {"queued": False}))
        self.assertEqual(
            [(run["kind"], run["period"]) for run in progress.get_runs()],
            [(progress.BOTS, f"{YEAR}-{MONTH:02d}")],
        )

    def test_should_queue_the_gm_job_once(self):
        first = self.post_gm().json()
        second = self.post_gm().json()

        self.assertEqual((first, second), ({"queued": True}, {"queued": False}))
        self.assertEqual([run["kind"] for run in progress.get_runs()], [progress.GM])

    def test_should_not_start_the_tax_run(self):
        """Only the page's own job - not run_update_alliance."""
        with patch("eos_tax.tasks.run_update_corporation.delay") as corporation:
            self.post_bots()
            self.post_gm()

        corporation.assert_not_called()

    def test_should_refuse_a_month_it_cannot_read(self):
        for month in ("", "2026-13", "september", "9999-12"):
            with self.subTest(month=month):
                self.assertEqual(self.post_bots(month).status_code, 400)

        self.assertEqual(progress.get_runs(), [])

    def test_should_refuse_admin_view_alone(self):
        self.client.force_login(self.viewer)

        self.assertEqual(self.post_bots().status_code, 403)
        self.assertEqual(self.post_gm().status_code, 403)
        self.assertEqual(progress.get_runs(), [])

    def test_should_refuse_a_get(self):
        self.assertEqual(self.client.get(reverse("eos_tax:bots_recalculate")).status_code, 405)
        self.assertEqual(
            self.client.get(reverse("eos_tax:gm_transactions_recalculate")).status_code, 405
        )

    def test_should_offer_the_button_only_with_manage_settings(self):
        pages = {
            "eos_tax:bots": reverse("eos_tax:bots_recalculate"),
            "eos_tax:gm_transactions": reverse("eos_tax:gm_transactions_recalculate"),
        }
        for page, url in pages.items():
            with self.subTest(page=page):
                self.client.force_login(self.manager)
                managing = self.client.get(reverse(page)).content.decode()
                self.client.force_login(self.viewer)
                viewing = self.client.get(reverse(page)).content.decode()

                self.assertIn(f'data-eos-recalculate-url="{url}"', managing)
                self.assertIn("eos_tax/js/recalculate.", managing)
                self.assertNotIn("data-eos-recalculate-url", viewing)

    def test_should_recalculate_the_month_on_screen(self):
        body = self.client.get(
            reverse("eos_tax:bots"), {"month": "2026-03"}
        ).content.decode()

        self.assertIn('data-eos-recalculate-month="2026-03"', body)

    def test_script_should_post_the_month_and_wake_the_bar(self):
        script = read_static("recalculate.js")

        self.assertIn('body.set("month", box.dataset.eosRecalculateMonth)', script)
        self.assertIn('"eos-tax:progress-poll"', script)


class TestStepLabels(ProgressTestCase):
    """The bar names every step of both jobs; a step without its label
    would show its bare key."""

    def test_should_name_every_step(self):
        self.client.force_login(
            create_user("viewer", 93000058, BRAVO_CORP_ID, "Bravo Corp",
                        ["basic_access", "admin_view"])
        )
        body = self.client.get(reverse("eos_tax:index")).content.decode()

        for step in [*READINGS, *GM_STEPS]:
            with self.subTest(step=step):
                self.assertIn(f"data-eos-tax-step-{step}=", body)
        for kind in (progress.BOTS, progress.GM):
            self.assertIn(f"data-eos-tax-label-{kind}=", body)
        self.assertIn(f"data-eos-tax-reason-{progress.STEP_FAILED}=", body)

    def test_script_should_list_steps_by_their_label(self):
        script = read_static("progress.js")

        self.assertIn('label("step-" + job.step)', script)
        self.assertIn("run.period", script)
