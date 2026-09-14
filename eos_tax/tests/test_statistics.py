from decimal import Decimal

from django.contrib.staticfiles.finders import find as find_static
from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.db.palette import _chart_palette
from eos_tax.models import MonthlyTax, TaxConfiguration
from eos_tax.util import get_amount_to_pay

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    OTHER_ALLIANCE_ID,
    OUTSIDER_CORP_ID,
    TAX_RATE,
    TAXED_ALLIANCE_ID,
    create_alliance,
    create_user,
)
from . import factories

YEAR = 2026


def create_corporation(corp_id, name, alliance):
    return factories.create_corporation(corp_id, name, alliance, member_count=120)


def create_tax_row(corp_id, name, month, tax_value=1_000_000_000, tax_percentage=10.0):
    """This page reads a whole year, so the month is always given."""
    return factories.create_tax_row(
        corp_id,
        name,
        month=month,
        year=YEAR,
        tax_value=tax_value,
        tax_percentage=tax_percentage,
        alliance_tax_rate=TAX_RATE,
    )


def read_statistics_js():
    """The rendered page only points at the (possibly hashed) static file, so
    the guards on its contents read the source directly instead."""
    path = find_static("eos_tax/js/statistics.js")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def build_fixture():
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


def build_world(blacklist=()):
    build_fixture()

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


class TestChartPalette(EosTaxTestCase):
    """Colours are midpoints of equal subcubes of the RGB cube.

    Rotating the hue alone kept producing colours that read as the same one;
    two different subcubes cannot. The order is farthest-first rather than the
    hue sort the source describes, because consecutive slots land on
    corporations that sit next to each other in the legend.
    """

    def test_should_never_repeat_a_colour(self):
        for count in (1, 2, 8, 27, 40, 64):
            palette = _chart_palette(count)

            self.assertEqual(len(palette), count)
            self.assertEqual(len(set(palette)), count, f"{count} colours")

    def test_should_keep_a_colour_stable_as_the_palette_grows(self):
        """A corporation must not be repainted because another one appeared."""
        self.assertEqual(_chart_palette(8)[0], _chart_palette(12)[0])

    def test_should_emit_valid_hex(self):
        for colour in _chart_palette(12):
            self.assertRegex(colour, r"^#[0-9a-f]{6}$")

    def test_should_avoid_the_grey_diagonal(self):
        """Where red, green and blue are equal the cube yields greys, and greys
        read as each other on a chart."""
        for colour in _chart_palette(20):
            channels = [int(colour[index:index + 2], 16) for index in (1, 3, 5)]

            self.assertGreaterEqual(max(channels) - min(channels), 40, colour)

    def test_should_survive_an_empty_request(self):
        self.assertEqual(_chart_palette(0), ())


class TestStatisticsAccess(EosTaxTestCase):
    @classmethod
    def setUpTestData(cls):
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
    @classmethod
    def setUpTestData(cls):
        build_fixture()
        cls.user = create_user(
            "boss", 92000010, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )

    def setUp(self):
        # two tests below reconfigure the blacklist, so the configuration
        # itself is rebuilt fresh every time instead of being shared
        configure()
        # self.client is rebuilt per test, so the login has to be too
        self.client.force_login(self.user)

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
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(
            "boss", 92000020, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
        )
        # enough to make `years` non empty: the eight tests below only need
        # the "has data" branch of the template, never a real figure from it.
        # A corp id of its own so it never collides with the row a test
        # builds itself; test_should_show_an_empty_state_without_any_data
        # deletes this row again before it runs.
        create_tax_row(98099999, "Filler Corp", month=1)

    def setUp(self):
        # self.client is rebuilt per test, so the login has to be too
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
        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "chart.umd.min.js")
        self.assertContains(response, 'id="eos-tax-chart"')

    def test_should_offer_both_display_methods(self):
        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-chart-type"')
        self.assertContains(response, 'value="line"')
        self.assertContains(response, 'value="pie"')

    def test_should_hide_the_month_field_until_the_pie_is_picked(self):
        response = self.client.get(reverse("eos_tax:statistics"))

        # the attribute on that element: "hidden" on its own also matches
        # the line of JavaScript that later shows the field again
        self.assertContains(response, 'id="eos-tax-month-field" hidden')

    def test_should_offer_the_share_threshold(self):
        response = self.client.get(reverse("eos_tax:statistics"))

        # value="2" alone also matches the year option value="2026"
        self.assertContains(response, 'id="eos-tax-min-share"')
        self.assertContains(response, 'step="0.5" value="2"')

    def test_should_ship_the_folding(self):
        """Shallow guard: the folding itself runs in the browser and is checked
        separately against the live figures. The logic lives in the static
        file now, not in the rendered page."""
        source = read_statistics_js()

        self.assertIn("function fold(", source)
        self.assertIn("function minShare()", source)

    def test_should_format_isk_with_dots(self):
        """The overview formats server side with dots; Intl would have followed
        the viewer's locale and printed commas on an English browser."""
        source = read_statistics_js()

        self.assertIn("function billions(", source)
        self.assertNotIn("Intl.NumberFormat", source)

    def test_should_load_the_script_as_a_static_file(self):
        """The 486 line block used to sit inline in the template. Now the page
        only points at the (hash named) static file and ships none of the
        logic itself."""
        response = self.client.get(reverse("eos_tax:statistics"))

        # the hash sits between the name and the extension, so this survives
        # collectstatic whether or not manifest hashing is in effect
        self.assertContains(response, "eos_tax/js/statistics")
        self.assertNotContains(response, "function fold(")

    def test_should_offer_the_key_figures(self):
        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, 'id="eos-tax-figures"')

    def test_should_not_leak_template_comments(self):
        """A multi line {# #} is not a comment in Django - it renders as text."""
        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertNotContains(response, "the legend doubles as the table view")
        self.assertNotContains(response, "{#")

    def test_should_show_an_empty_state_without_any_data(self):
        # setUpTestData seeds one row so the eight tests above see a
        # non empty `years` - this is the one test that needs none at all
        MonthlyTax.objects.all().delete()

        response = self.client.get(reverse("eos_tax:statistics"))

        self.assertContains(response, "No tax data recorded yet.")
        self.assertNotContains(response, 'id="eos-tax-chart"')
