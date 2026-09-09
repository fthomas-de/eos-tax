import datetime
from datetime import date
from decimal import Decimal
from importlib import import_module

from django import forms
from django.db.utils import IntegrityError
from django.urls import reverse

from eos_tax.tests.base import EosTaxTestCase

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.db_connector import get_website_data
from eos_tax.forms import TaxConfigurationForm, journal_type_choices
from eos_tax.models import MonthlyTax, TaxConfiguration, TaxRate

from .test_views import create_user

BRAVO_CORP_ID = 98000001
ALLIANCE_ID = 99000001


# the migration module name starts with a digit, so it cannot be
# imported with a plain import statement
_guard = import_module(
    "eos_tax.migrations.0010_monthlytax_one_row_per_corp_and_month"
)
LISTED = _guard.LISTED
refuse_duplicates = _guard.refuse_duplicates


class TestSettingsAccess(EosTaxTestCase):
    def test_should_reject_basic_access(self):
        self.client.force_login(
            create_user("member", 93000001, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:settings"))

        self.assertEqual(response.status_code, 302)

    def test_should_allow_admin_view(self):
        self.client.force_login(
            create_user("boss", 93000002, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        response = self.client.get(reverse("eos_tax:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save settings")


class TestSettingsSeed(EosTaxTestCase):
    """Migration 0005 carries the local.py values over exactly once."""

    def test_should_have_created_the_singleton(self):
        self.assertEqual(TaxConfiguration.objects.count(), 1)

    def test_should_backfill_the_applied_rate_on_existing_rows(self):
        """Rows written before the rate was stored must not read as zero."""
        config = TaxConfiguration.get_solo()

        self.assertGreater(float(config.tax_rate), 0)


class TestSettingsForm(EosTaxTestCase):
    def setUp(self):
        self.client.force_login(
            create_user("boss", 93000010, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )
        self.alliance = EveAllianceInfo.objects.create(
            alliance_id=ALLIANCE_ID, alliance_name="Taxed Alliance", alliance_ticker="TAX"
        )
        self.corporation = EveCorporationInfo.objects.create(
            corporation_id=BRAVO_CORP_ID,
            corporation_name="Bravo Corp",
            corporation_ticker="BRVO",
            alliance=self.alliance,
            tax_rate=0.1,
        )

    def post(self, **overrides):
        data = {
            "tax_alliances": [self.alliance.pk],
            "tax_corporation": self.corporation.pk,
            "corporation_blacklist": [],
            "tax_rate": "10",
            "tax_types": ["bounty_prizes"],
            "last_month": "on",
            "current_month": "on",
            "bot_min_hours_per_day": "20",
            "bot_min_days_per_month": "12",
            # the rate schedule rides along in the same POST
            "form-TOTAL_FORMS": "0",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)

        return self.client.post(reverse("eos_tax:settings"), data)

    def test_should_save_the_configuration(self):
        response = self.post()
        config = TaxConfiguration.get_solo()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(config.tax_rate, Decimal("0.1000"))
        self.assertEqual(config.alliance_ids(), [ALLIANCE_ID])
        self.assertEqual(config.holding_corporation_id(), BRAVO_CORP_ID)
        self.assertEqual(config.tax_types, ["bounty_prizes"])
        self.assertTrue(config.last_month)
        self.assertTrue(config.current_month)
        self.assertFalse(config.use_reason)
        self.assertEqual(config.bot_min_hours_per_day, 20)
        self.assertEqual(config.bot_min_days_per_month, 12)

    def test_should_reject_more_than_twentyfour_hours_per_day(self):
        response = self.post(bot_min_hours_per_day="30")

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(TaxConfiguration.get_solo().bot_min_hours_per_day, 30)

    def test_should_offer_checkboxes_instead_of_a_multi_select(self):
        """A native <select multiple> only adds or drops an entry on ctrl-click."""
        # the exclusion list only offers Corporations of the taxed alliances,
        # so there has to be one for a checkbox to exist at all
        config = TaxConfiguration.get_solo()
        config.tax_alliances.set([self.alliance])

        form = TaxConfigurationForm(instance=config)

        for name in ("tax_alliances", "corporation_blacklist"):
            with self.subTest(field=name):
                self.assertIsInstance(
                    form.fields[name].widget, forms.CheckboxSelectMultiple
                )

        body = self.client.get(reverse("eos_tax:settings")).content.decode()

        self.assertRegex(body, r'<input[^>]*type="checkbox"[^>]*name="corporation_blacklist"')
        self.assertNotRegex(body, r'<select[^>]*name="corporation_blacklist"')

    def test_should_keep_the_checkbox_lists_compact(self):
        """The styling hooks onto Django auto_id values - if the widget ids ever
        change, the lists silently grow into one very tall column again."""
        body = self.client.get(reverse("eos_tax:settings")).content.decode()

        for field in ("tax_alliances", "corporation_blacklist"):
            with self.subTest(field=field):
                self.assertIn(f"#id_{field}", body)
                self.assertIn(f'<div id="id_{field}"', body)

        self.assertIn("overflow-y: auto", body)

    def test_should_allow_exactly_one_holding_corporation(self):
        """There is only ever one wallet the tax is paid into."""
        form = TaxConfigurationForm()

        self.assertNotIsInstance(
            form.fields["tax_corporation"].widget, forms.SelectMultiple
        )

        body = self.client.get(reverse("eos_tax:settings")).content.decode()

        self.assertNotRegex(body, r'<select[^>]*name="tax_corporation"[^>]*multiple')

    def test_should_allow_clearing_the_holding_corporation(self):
        self.post(tax_corporation="")

        self.assertIsNone(TaxConfiguration.get_solo().holding_corporation_id())

    def test_should_allow_clearing_a_selection(self):
        config = TaxConfiguration.get_solo()
        config.corporation_blacklist.set([self.corporation])

        self.post(corporation_blacklist=[])

        self.assertEqual(TaxConfiguration.get_solo().blacklisted_corporation_ids(), [])

    def test_should_allow_selecting_several_corporations(self):
        second = EveCorporationInfo.objects.create(
            corporation_id=98000009,
            corporation_name="Second Corp",
            corporation_ticker="SEC",
            alliance=self.alliance,
            tax_rate=0.1,
        )

        self.post(corporation_blacklist=[self.corporation.pk, second.pk])

        self.assertEqual(
            sorted(TaxConfiguration.get_solo().blacklisted_corporation_ids()),
            sorted([BRAVO_CORP_ID, 98000009]),
        )

    def test_should_reject_a_rate_above_hundred_percent(self):
        response = self.post(tax_rate="150")

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(TaxConfiguration.get_solo().tax_rate, Decimal("1.5000"))

    def test_should_take_the_rate_as_a_percentage(self):
        """7.5 on the form is 0.075 in the database - the calculation multiplies
        the gross income by the stored value."""
        self.post(tax_rate="7.5")

        self.assertEqual(TaxConfiguration.get_solo().tax_rate, Decimal("0.0750"))

    def test_should_show_a_stored_fraction_as_a_percentage(self):
        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.0700")
        config.save()

        form = TaxConfigurationForm(instance=config)

        self.assertEqual(str(form["tax_rate"].value()), "7")

    def test_should_reject_an_unknown_journal_type(self):
        response = self.post(tax_types=["not_a_ref_type"])

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("not_a_ref_type", TaxConfiguration.get_solo().tax_types)

    def test_should_offer_the_corptools_vocabulary(self):
        choices = dict(journal_type_choices())

        self.assertIn("bounty_prizes", choices)
        self.assertIn("agent_mission_reward", choices)

    def test_should_keep_a_configured_type_selectable(self):
        """A value corptools no longer lists must not silently disappear."""
        choices = dict(journal_type_choices(["some_custom_type"]))

        self.assertIn("some_custom_type", choices)


class TestTaxRateSchedule(EosTaxTestCase):
    """Planned transitions: the newest entry not in the future wins."""

    def test_should_fall_back_to_the_base_rate_without_a_schedule(self):
        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.1")
        config.save()

        self.assertAlmostEqual(config.rate_for(2026, 9), 0.1)

    def test_should_apply_the_newest_entry_that_has_started(self):
        TaxRate.objects.create(valid_from=date(2026, 9, 1), rate=Decimal("0.07"))
        TaxRate.objects.create(valid_from=date(2026, 10, 1), rate=Decimal("0.10"))

        config = TaxConfiguration.get_solo()

        self.assertAlmostEqual(config.rate_for(2026, 9), 0.07)
        self.assertAlmostEqual(config.rate_for(2026, 10), 0.10)

    def test_should_keep_a_rate_until_the_next_entry(self):
        TaxRate.objects.create(valid_from=date(2026, 9, 1), rate=Decimal("0.07"))

        config = TaxConfiguration.get_solo()

        self.assertAlmostEqual(config.rate_for(2027, 3), 0.07)

    def test_should_ignore_a_window_before_it_starts(self):
        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.2")
        config.save()
        TaxRate.objects.create(valid_from=date(2026, 10, 1), rate=Decimal("0.10"))

        self.assertAlmostEqual(config.rate_for(2026, 9), 0.2)

    def test_should_normalise_to_the_first_of_the_month(self):
        """A mid month start would be ambiguous for a monthly calculation."""
        rate = TaxRate.objects.create(valid_from=date(2026, 9, 17), rate=Decimal("0.07"))
        rate.refresh_from_db()

        self.assertEqual(rate.valid_from, date(2026, 9, 1))

    def test_should_reject_a_second_entry_for_the_same_month(self):
        TaxRate.objects.create(valid_from=date(2026, 9, 1), rate=Decimal("0.07"))

        with self.assertRaises(IntegrityError):
            TaxRate.objects.create(valid_from=date(2026, 9, 1), rate=Decimal("0.09"))


class TestTaxRateScheduleForm(EosTaxTestCase):
    def setUp(self):
        self.client.force_login(
            create_user("boss", 93000030, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def post(self, **overrides):
        data = {
            "tax_alliances": [],
            "tax_corporation": "",
            "corporation_blacklist": [],
            "tax_rate": "10",
            "tax_types": ["bounty_prizes"],
            "bot_min_hours_per_day": "20",
            "bot_min_days_per_month": "12",
            "form-TOTAL_FORMS": "0",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)

        return self.client.post(reverse("eos_tax:settings"), data)

    def test_should_show_the_schedule_table(self):
        response = self.client.get(reverse("eos_tax:settings"))

        self.assertContains(response, "Tax rate schedule")
        self.assertContains(response, 'name="form-0-valid_from"')
        self.assertContains(response, 'type="month"')

    def test_should_plan_september_and_october_in_one_go(self):
        response = self.post(**{
            "form-TOTAL_FORMS": "2",
            "form-0-valid_from": "2026-09",
            "form-0-rate": "7",
            "form-1-valid_from": "2026-10",
            "form-1-rate": "10",
        })

        self.assertEqual(response.status_code, 302)

        config = TaxConfiguration.get_solo()
        self.assertAlmostEqual(config.rate_for(2026, 8), 0.1)   # base rate
        self.assertAlmostEqual(config.rate_for(2026, 9), 0.07)
        self.assertAlmostEqual(config.rate_for(2026, 10), 0.10)
        self.assertAlmostEqual(config.rate_for(2026, 11), 0.10)

    def test_should_store_the_month_as_the_first_day(self):
        self.post(**{
            "form-TOTAL_FORMS": "1",
            "form-0-valid_from": "2026-09",
            "form-0-rate": "7",
        })

        self.assertEqual(TaxRate.objects.get().valid_from, date(2026, 9, 1))

    def test_should_store_the_schedule_rate_as_a_fraction(self):
        self.post(**{
            "form-TOTAL_FORMS": "1",
            "form-0-valid_from": "2026-09",
            "form-0-rate": "7",
        })

        self.assertEqual(TaxRate.objects.get().rate, Decimal("0.0700"))

    def test_should_reject_a_rate_above_hundred_percent(self):
        response = self.post(**{
            "form-TOTAL_FORMS": "1",
            "form-0-valid_from": "2026-09",
            "form-0-rate": "150",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TaxRate.objects.exists())

    def test_should_reject_two_entries_for_the_same_month(self):
        response = self.post(**{
            "form-TOTAL_FORMS": "2",
            "form-0-valid_from": "2026-09",
            "form-0-rate": "7",
            "form-1-valid_from": "2026-09",
            "form-1-rate": "9",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TaxRate.objects.exists())

    def test_should_ignore_an_untouched_empty_row(self):
        response = self.post(**{
            "form-TOTAL_FORMS": "1",
            "form-0-valid_from": "",
            "form-0-rate": "",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaxRate.objects.exists())


class TestConfigurationTakesEffect(EosTaxTestCase):
    """The whole point of the move: no restart of gunicorn or celery needed."""

    def setUp(self):
        self.client.force_login(
            create_user(
                "boss", 93000020, BRAVO_CORP_ID, "Bravo Corp", ["basic_access", "admin_view"]
            )
        )
        config = TaxConfiguration.get_solo()
        config.current_month = True
        config.tax_rate = Decimal("0.1")
        config.save()

        now = datetime.datetime.now()
        self.row = MonthlyTax.objects.create(
            corp_id=BRAVO_CORP_ID,
            corp_name="Bravo Corp",
            tax_value=1_000_000_000,
            tax_percentage=10.0,
            month=now.month,
            year=now.year,
            payed=False,
            alliance_tax_rate=0.1,
        )

    def test_should_apply_a_changed_rate_to_the_overview_title(self):
        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.25")
        config.save()

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "Taxes to pay: 25%")

    def test_should_apply_a_changed_month_switch(self):
        config = TaxConfiguration.get_solo()
        config.current_month = False
        config.save()

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "No tax data for the selected months.")

    def test_should_not_rewrite_history_when_the_rate_changes(self):
        """Past months keep the rate they were calculated with."""
        dates = [(self.row.month, self.row.year)]
        before = get_website_data(dates=dates, admin=True, corps=[])[0]["isk_to_pay_value"]

        config = TaxConfiguration.get_solo()
        config.tax_rate = Decimal("0.5")
        config.save()

        after = get_website_data(dates=dates, admin=True, corps=[])[0]["isk_to_pay_value"]

        self.assertEqual(before, after)


class TestExcludableCorporations(EosTaxTestCase):
    """Only Corporations of the taxed alliances can be excluded.

    Excluding anything else changes nothing, and on a real install the full
    list of everything Alliance Auth knows runs to hundreds of entries.
    """

    def setUp(self):
        self.taxed = EveAllianceInfo.objects.create(
            alliance_id=99000021, alliance_name="Taxed", alliance_ticker="TAX"
        )
        self.other = EveAllianceInfo.objects.create(
            alliance_id=99000022, alliance_name="Other", alliance_ticker="OTH"
        )
        self.inside = self.corporation("Inside Corp", 98000021, self.taxed)
        self.outside = self.corporation("Outside Corp", 98000022, self.other)

        self.config = TaxConfiguration.get_solo()
        self.config.tax_alliances.set([self.taxed])

    def corporation(self, name, corp_id, alliance):
        return EveCorporationInfo.objects.create(
            corporation_id=corp_id,
            corporation_name=name,
            corporation_ticker=name[:5].upper(),
            alliance=alliance,
            tax_rate=0.1,
        )

    def offered(self, form=None):
        form = form or TaxConfigurationForm(instance=self.config)

        return [
            entry.corporation_name
            for entry in form.fields["corporation_blacklist"].queryset
        ]

    def test_should_offer_a_corporation_of_the_taxed_alliance(self):
        self.assertIn("Inside Corp", self.offered())

    def test_should_leave_out_a_corporation_of_another_alliance(self):
        self.assertNotIn("Outside Corp", self.offered())

    def test_should_offer_nothing_without_a_taxed_alliance(self):
        self.config.tax_alliances.clear()

        self.assertEqual(self.offered(), [])

    def test_should_keep_an_already_excluded_corporation(self):
        """Narrowing the alliances must not quietly let one back in: dropping
        it from the queryset would drop it from the form, and the next save
        would un-exclude it."""
        self.config.corporation_blacklist.set([self.outside])

        self.assertIn("Outside Corp", self.offered())

    def test_should_follow_the_alliances_chosen_in_the_form(self):
        """Otherwise the choices lag a save behind when someone adds an
        alliance and excludes one of its Corporations in the same visit."""
        bound = TaxConfigurationForm(
            {"tax_alliances": [self.other.pk]}, instance=self.config
        )

        self.assertIn("Outside Corp", self.offered(bound))
        self.assertNotIn("Inside Corp", self.offered(bound))

    def test_should_not_repeat_a_corporation(self):
        """It is both in the alliance and already excluded."""
        self.config.corporation_blacklist.set([self.inside])

        self.assertEqual(self.offered().count("Inside Corp"), 1)


class TestUniquenessGuard(EosTaxTestCase):
    """Migration 0010 refuses to add the constraint to data that breaks it.

    Adding it blind fails inside the database naming a single row, with no way
    to find the rest, and MariaDB cannot roll the statement back.

    The rows are handed in rather than created: the test database already
    carries the constraint, so duplicates cannot be inserted there. The
    aggregation belongs to Django; what belongs here is the refusal and what it
    says. The path against a real database was checked by replaying the upgrade
    on a scratch database.
    """

    class Rows:
        """Stands in for the queryset chain the migration builds."""

        def __init__(self, rows):
            self.rows = rows

        def values(self, *args, **kwargs):
            return self

        def annotate(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def __iter__(self):
            return iter(self.rows)

    def registry(self, *entries):
        """An `apps` stand-in whose MonthlyTax reports these duplicates."""
        rows = [
            {"corp_id": corp_id, "year": year, "month": month, "rows": count}
            for corp_id, year, month, count in entries
        ]

        class Model:
            objects = self.Rows(rows)

        class Apps:
            def get_model(self, *args):
                return Model

        return Apps()

    def test_should_pass_on_clean_data(self):
        refuse_duplicates(self.registry(), None)  # no exception is the assertion

    def test_should_refuse_and_name_the_rows(self):
        with self.assertRaises(RuntimeError) as raised:
            refuse_duplicates(self.registry((98000001, 2026, 3, 2)), None)

        message = str(raised.exception)

        self.assertIn("98000001", message)
        self.assertIn("3/2026", message)
        self.assertIn("2 rows", message)
        self.assertIn("Nothing has been changed", message)

    def test_should_count_every_offending_combination(self):
        with self.assertRaises(RuntimeError) as raised:
            refuse_duplicates(
                self.registry((98000001, 2026, 3, 2), (98000002, 2026, 4, 3)), None
            )

        self.assertIn("2 corporation and month combinations", str(raised.exception))

    def test_should_summarise_beyond_the_listed_ones(self):
        """A long list in a terminal is unreadable, so it is cut with a count."""
        entries = tuple(
            (98001000 + offset, 2026, 5, 2) for offset in range(LISTED + 3)
        )

        with self.assertRaises(RuntimeError) as raised:
            refuse_duplicates(self.registry(*entries), None)

        self.assertIn("and 3 more", str(raised.exception))
