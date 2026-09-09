from decimal import Decimal

from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.models import MonthlyTax, TaxConfiguration
from eos_tax.util import get_amount_to_pay

from .test_views import create_user

TAXED_ALLIANCE_ID = 99000001
OTHER_ALLIANCE_ID = 99000002
BRAVO_CORP_ID = 98000001
ALPHA_CORP_ID = 98000002
OUTSIDER_CORP_ID = 98000003

YEAR = 2026

# mirrors a real configuration, so income and tax are not the same figure
TAX_RATE = 0.1


def create_alliance(alliance_id, name):
    return EveAllianceInfo.objects.create(
        alliance_id=alliance_id,
        alliance_name=name,
        alliance_ticker=name[:5].upper(),
    )


def create_corporation(corp_id, name, alliance):
    return EveCorporationInfo.objects.create(
        corporation_id=corp_id,
        corporation_name=name,
        corporation_ticker=name[:5].upper(),
        alliance=alliance,
        tax_rate=0.1,
        member_count=120,
    )


def create_tax_row(corp_id, name, month, tax_value=1_000_000_000, tax_percentage=10.0):
    return MonthlyTax.objects.create(
        corp_id=corp_id,
        corp_name=name,
        tax_value=tax_value,
        tax_percentage=tax_percentage,
        month=month,
        year=YEAR,
        payed=False,
        alliance_tax_rate=TAX_RATE,
    )


def build_world(blacklist=()):
    """Two corporations inside the taxed alliance, one outside it."""
    taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
    other = create_alliance(OTHER_ALLIANCE_ID, "Other Alliance")

    create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
    create_corporation(ALPHA_CORP_ID, "Alpha Corp", taxed)
    create_corporation(OUTSIDER_CORP_ID, "Outsider Corp", other)

    create_tax_row(BRAVO_CORP_ID, "Bravo Corp", month=1)
    create_tax_row(BRAVO_CORP_ID, "Bravo Corp", month=2, tax_value=2_000_000_000)
    create_tax_row(ALPHA_CORP_ID, "Alpha Corp", month=1, tax_value=500_000_000)
    create_tax_row(OUTSIDER_CORP_ID, "Outsider Corp", month=1)

    return configure(blacklist=blacklist)


def configure(blacklist=()):
    config = TaxConfiguration.get_solo()
    config.tax_rate = Decimal(str(TAX_RATE))
    config.save()
    config.tax_alliances.set(
        EveAllianceInfo.objects.filter(alliance_id=TAXED_ALLIANCE_ID)
    )
    config.corporation_blacklist.set(
        EveCorporationInfo.objects.filter(corporation_id__in=blacklist)
    )

    return config


class TestStatisticsAccess(EosTaxTestCase):
    def setUp(self):
        build_world()

    def test_should_reject_basic_access_on_the_page(self):
        self.client.force_login(
            create_user("member", 92000001, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertEqual(response.status_code, 302)

    def test_should_reject_basic_access_on_the_data_endpoint(self):
        self.client.force_login(
            create_user("member2", 92000002, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"])
        )

        response = self.client.get(reverse("eos_tax:statistics_data"), {"year": YEAR})

        self.assertEqual(response.status_code, 302)

    def test_should_allow_admin_view(self):
        self.client.force_login(
            create_user("boss", 92000003, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

        self.assertEqual(self.client.get(reverse("eos_tax:statistics")).status_code, 200)


class TestStatisticsData(EosTaxTestCase):
    def setUp(self):
        build_world()
        self.client.force_login(
            create_user("boss", 92000010, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"])
        )

    def payload(self, **params):
        params.setdefault("year", YEAR)
        response = self.client.get(reverse("eos_tax:statistics_data"), params)
        self.assertEqual(response.status_code, 200)

        return response.json()

    def test_should_return_twelve_month_labels(self):
        self.assertEqual(len(self.payload()["labels"]), 12)

    def test_should_only_return_corporations_of_taxed_alliances(self):
        names = [corp["name"] for corp in self.payload()["series"]]

        self.assertEqual(names, ["Alpha Corp", "Bravo Corp"])

    def test_should_spread_values_over_twelve_months(self):
        bravo = self.payload()["series"][1]

        self.assertEqual(len(bravo["tax"]), 12)
        self.assertEqual(bravo["tax"][2:], [0] * 10)

    def test_should_report_the_tax_due_per_month(self):
        bravo = self.payload()["series"][1]

        self.assertEqual(
            bravo["tax"][0], round(get_amount_to_pay(1_000_000_000, 10.0, TAX_RATE))
        )
        self.assertEqual(
            bravo["tax"][1], round(get_amount_to_pay(2_000_000_000, 10.0, TAX_RATE))
        )

    def test_should_report_the_member_count(self):
        """Alliance Auth keeps it from ESI - no need to scrape Dotlan."""
        bravo = self.payload()["series"][1]

        self.assertEqual(bravo["members"], 120)

    def test_should_report_gross_income_above_the_tax(self):
        bravo = self.payload()["series"][1]

        self.assertGreater(bravo["income_total"], bravo["tax_total"])
        self.assertEqual(bravo["tax_total"], sum(bravo["tax"]))

    def test_should_narrow_down_to_one_alliance(self):
        payload = self.payload(alliance=OTHER_ALLIANCE_ID)

        self.assertEqual(payload["series"], [])

    def test_should_not_repaint_when_a_corporation_drops_out(self):
        """Colour follows the corporation, never its rank in the current result.

        Bravo holds the first palette slot. Dropping it must not promote Alpha
        into that slot, or every filter change would recolour the chart.
        """
        before = {
            corp["name"]: corp["color_light"] for corp in self.payload()["series"]
        }

        configure(blacklist=[BRAVO_CORP_ID])
        after = {corp["name"]: corp["color_light"] for corp in self.payload()["series"]}

        self.assertNotIn("Bravo Corp", after)
        self.assertEqual(after["Alpha Corp"], before["Alpha Corp"])
        self.assertNotEqual(after["Alpha Corp"], before["Bravo Corp"])

    def test_should_give_neighbouring_corporations_different_colours(self):
        colours = [corp["color_light"] for corp in self.payload()["series"]]

        self.assertEqual(len(colours), len(set(colours)))

    def test_should_skip_blacklisted_corporations(self):
        configure(blacklist=[BRAVO_CORP_ID])

        names = [corp["name"] for corp in self.payload()["series"]]

        self.assertEqual(names, ["Alpha Corp"])

    def test_should_reject_a_non_numeric_year(self):
        response = self.client.get(reverse("eos_tax:statistics_data"), {"year": "abc"})

        self.assertEqual(response.status_code, 400)

    def test_should_reject_a_non_numeric_alliance(self):
        response = self.client.get(
            reverse("eos_tax:statistics_data"), {"year": YEAR, "alliance": "abc"}
        )

        self.assertEqual(response.status_code, 400)


class TestStatisticsPage(EosTaxTestCase):
    def setUp(self):
        self.user = create_user(
            "boss", 92000020, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )
        self.client.force_login(self.user)

    def test_should_offer_the_years_that_carry_data(self):
        build_world()
        MonthlyTax.objects.create(
            corp_id=BRAVO_CORP_ID, corp_name="Bravo Corp", tax_value=1,
            tax_percentage=10.0, month=5, year=YEAR - 1, payed=False,
        )

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, f'value="{YEAR}"')
        self.assertContains(response, f'value="{YEAR - 1}"')

    def test_should_offer_only_configured_alliances(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "Taxed Alliance")
        self.assertNotContains(response, "Other Alliance")

    def test_should_load_the_chart_bundle(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "chart.umd.min.js")
        self.assertContains(response, 'id="eos-tax-chart"')

    def test_should_offer_both_display_methods(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-chart-type"')
        self.assertContains(response, 'value="line"')
        self.assertContains(response, 'value="pie"')

    def test_should_hide_the_month_field_until_the_pie_is_picked(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-month-field"')
        self.assertContains(response, "hidden")

    def test_should_offer_the_share_threshold(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-min-share"')
        self.assertContains(response, 'value="2"')

    def test_should_ship_the_folding(self):
        """Shallow guard: the folding itself runs in the browser and is checked
        separately against the live figures."""
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "function fold(")
        self.assertContains(response, "function minShare()")

    def test_should_format_isk_with_dots(self):
        """The overview formats server side with dots; Intl would have followed
        the viewer's locale and printed commas on an English browser."""
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "function billions(")
        self.assertNotContains(response, "Intl.NumberFormat")

    def test_should_offer_the_key_figures(self):
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-figures"')

    def test_should_not_leak_template_comments(self):
        """A multi line {# #} is not a comment in Django - it renders as text."""
        build_world()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertNotContains(response, "the legend doubles as the table view")
        self.assertNotContains(response, "{#")

    def test_should_show_an_empty_state_without_any_data(self):
        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "No tax data recorded yet.")
        self.assertNotContains(response, 'id="eos-tax-chart"')
