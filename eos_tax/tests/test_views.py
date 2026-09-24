import datetime
import html
import json
import re

from dateutil.relativedelta import relativedelta
from django.test import RequestFactory

from django.contrib.auth.models import Permission, User
from eos_tax.tests.base import EosTaxTestCase, read_static
from django.urls import reverse

from eos_tax.auth_hooks import EosTaxMenuItem
from eos_tax.models import MonthlyTax, TaxConfiguration
from eos_tax.util import get_amount_to_pay

from .factories import (
    ALPHA_CORP_ID,
    BRAVO_CORP_ID,
    create_tax_row,
    create_user,
    enable_current_month,
)


class TestIndexAccess(EosTaxTestCase):
    def test_should_redirect_anonymous_user(self):
        response = self.client.get(reverse("eos_tax:index"))

        self.assertEqual(response.status_code, 302)

    def test_should_redirect_user_without_main_character(self):
        user = User.objects.create_user("nomain", "nomain@example.com", "password")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="eos_tax", codename="basic_access"
            )
        )
        self.client.force_login(user)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("dashboard", response["Location"])

    def test_should_redirect_user_without_permission(self):
        user = create_user("noperm", 91000003, BRAVO_CORP_ID, "Bravo Corp")
        self.client.force_login(user)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertEqual(response.status_code, 302)

    def test_should_grant_access_with_basic_access(self):
        user = create_user(
            "basic", 91000004, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"]
        )
        self.client.force_login(user)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertEqual(response.status_code, 200)


class TestIndexContent(EosTaxTestCase):
    def setUp(self):
        enable_current_month()
        self.user = create_user(
            "admin",
            91000001,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)

    def test_should_show_empty_state_without_data(self):
        response = self.client.get(reverse("eos_tax:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tax data for the selected months.")
        self.assertNotContains(response, "<tbody>")

    def test_should_sort_unpaid_before_paid(self):
        """Which also covers both being listed at all - index() would raise
        rather than report a missing Corporation. Fetched with paid rows
        included: Outstanding only, the default, would leave Alpha Corp with
        nothing to be sorted against."""
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"), {"paid": "1"})
        self.assertContains(response, "Bravo Corp")
        self.assertContains(response, "Alpha Corp")

        body = response.content.decode()

        self.assertLess(body.index("Bravo Corp"), body.index("Alpha Corp"))

    def test_should_hide_other_corporations_without_admin_view(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=False)
        basic_user = create_user(
            "member", 91000002, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"]
        )
        self.client.force_login(basic_user)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "Bravo Corp")
        self.assertNotContains(response, "Alpha Corp")


class TestOutstandingOnly(EosTaxTestCase):
    """The overview's paid/unpaid toggle - modelled on the one in
    eos-invoices: outstanding only by default, a link brings paid rows
    back rather than a client side re-filter of rows never sent."""

    def setUp(self):
        enable_current_month()
        self.user = create_user(
            "toggle",
            91000006,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)

    def test_should_hide_paid_rows_by_default(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "Bravo Corp")
        self.assertNotContains(response, "Alpha Corp")

    def test_should_show_paid_rows_on_request(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"), {"paid": "1"})

        self.assertContains(response, "Bravo Corp")
        self.assertContains(response, "Alpha Corp")

    def test_should_highlight_outstanding_only_by_default(self):
        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, '<a href="?" class="btn btn-primary">')
        self.assertContains(response, '<a href="?paid=1" class="btn btn-outline-primary">')

    def test_should_highlight_including_paid_on_request(self):
        response = self.client.get(reverse("eos_tax:index"), {"paid": "1"})

        self.assertContains(response, '<a href="?" class="btn btn-outline-primary">')
        self.assertContains(response, '<a href="?paid=1" class="btn btn-primary">')

    def test_should_explain_nothing_outstanding_when_everything_is_paid(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "Nothing outstanding.")
        self.assertNotContains(response, "No tax data for the selected months.")

    def test_should_explain_no_data_when_nothing_was_calculated_at_all(self):
        """Distinct from "nothing outstanding" - there is nothing to filter
        in the first place, calculated or not."""
        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "No tax data for the selected months.")
        self.assertNotContains(response, "Nothing outstanding.")

    def test_should_keep_showing_everything_paid_when_requested(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"), {"paid": "1"})

        self.assertContains(response, "Bravo Corp")
        self.assertNotContains(response, "Nothing outstanding.")


class TestIndexMarkup(EosTaxTestCase):
    """Guards the Bootstrap 5 rewrite against a relapse into Bootstrap 3."""

    BOOTSTRAP5_CLASSES = ["card-header", "card-title mb-0", "card-body", "table-responsive"]
    BOOTSTRAP3_CLASSES = ["panel panel-primary", "panel-heading", "panel-title", "panel-body"]

    def setUp(self):
        enable_current_month()
        user = create_user(
            "markup",
            91000005,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(user)
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)

    def render_page(self):
        return self.client.get(reverse("eos_tax:index")).content.decode()

    def test_should_use_bootstrap5_classes(self):
        body = self.render_page()

        for css_class in self.BOOTSTRAP5_CLASSES:
            with self.subTest(css_class=css_class):
                self.assertIn(css_class, body)

    def test_should_not_contain_bootstrap3_classes(self):
        body = self.render_page()

        for css_class in self.BOOTSTRAP3_CLASSES:
            with self.subTest(css_class=css_class):
                self.assertNotIn(css_class, body)

    def test_should_close_every_table_tag(self):
        body = self.render_page()

        self.assertEqual(body.count("<table"), body.count("</table>"))
        self.assertEqual(body.count("<thead>"), body.count("</thead>"))
        self.assertEqual(body.count("<tbody>"), body.count("</tbody>"))


class TestOverviewTable(EosTaxTestCase):
    """The table is sorted and filtered client side by DataTables.

    Formatted cells therefore need an unformatted ``data-order`` value, or
    "5.000.000.000" and "1/2026" get compared as plain text.
    """

    def setUp(self):
        enable_current_month()
        user = create_user(
            "sorter",
            91000010,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(user)
        self.row = create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)

    def overview(self):
        return self.client.get(reverse("eos_tax:index"))

    def test_should_give_the_table_an_id(self):
        self.assertContains(self.overview(), 'id="table-eos-tax"')

    def test_should_load_datatables_assets(self):
        """The versioned path, not the file name: the static manifest hashes
        the name into dataTables.min.<hash>.js."""
        response = self.overview()

        self.assertContains(response, "DataTables/2.3.8/js/dataTables.min")
        self.assertContains(response, "DataTables/2.3.8/css/dataTables.bootstrap5.min")

    def test_should_expose_numeric_sort_value_for_isk(self):
        expected = int(get_amount_to_pay(self.row.tax_value, self.row.tax_percentage))

        self.assertContains(self.overview(), f'data-order="{expected}"')

    def test_should_expose_chronological_sort_value_for_period(self):
        expected = self.row.year * 100 + self.row.month

        self.assertContains(self.overview(), f'data-order="{expected}"')

    def test_should_expose_boolean_sort_value_for_payed(self):
        """The whole cell, not the value: data-order="1" is also the start of
        data-order="10.0" in the rate column and of the ISK amount. Fetched
        with paid rows included, or the payed=True row Alpha Corp needs for
        this would not be on the page at all."""
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"), {"paid": "1"})

        self.assertContains(response, '<td data-order="0">')
        self.assertContains(response, '<td data-order="1">')

    def test_should_not_localize_sort_values(self):
        """A German locale would otherwise render the tax rate as "10,0"."""
        response = self.client.get(reverse("eos_tax:index"), headers={"accept-language": "de"})

        self.assertNotContains(response, 'data-order="10,0"')

    def test_should_render_no_table_without_data(self):
        MonthlyTax.objects.all().delete()

        self.assertNotContains(self.overview(), 'id="table-eos-tax"')

    def test_should_make_exactly_the_corporation_column_searchable(self):
        """Shallow guard: overlapping columnDefs once made every column
        unsearchable, which emptied the table on any keystroke. This only
        checks the config in the source, not the browser behaviour."""
        script = read_static("overview.js")

        self.assertEqual(script.count("searchable: true"), 1)
        self.assertEqual(script.count("searchable: false"), 6)
        self.assertNotIn('targets: "_all"', script)

    def test_should_load_its_script_from_a_static_file(self):
        """The checks above read the file; this is what ties it to the page."""
        self.assertContains(self.overview(), "eos_tax/js/overview")

    def test_should_show_the_applied_alliance_tax_rate(self):
        """The rate is stored as a fraction and shown as a percentage."""
        self.row.alliance_tax_rate = 0.07
        self.row.save()

        self.assertContains(
            self.overview(),
            '<td class="d-none d-md-table-cell" data-order="7.0">7.0%</td>',
            html=False,
        )

    def test_should_fall_back_to_the_scheduled_rate_for_old_rows(self):
        """Rows written before the rate was stored per row carry a zero."""
        self.row.alliance_tax_rate = 0
        self.row.save()
        expected = TaxConfiguration.get_solo().rate_for(self.row.year, self.row.month) * 100

        self.assertContains(self.overview(), f'>{float("%.2f" % expected)}%</td>')

    def test_should_offer_a_copy_button_for_the_reason(self):
        """The reason has to reach the ingame transfer character for character."""
        previous = datetime.datetime.now() - relativedelta(months=1)
        config = TaxConfiguration.get_solo()
        config.last_month = True
        config.save()
        row = create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=False)
        row.month = previous.month
        row.year = previous.year
        row.save()

        response = self.overview()
        reason = f"{ALPHA_CORP_ID}/{previous.month}/{previous.year}"

        self.assertContains(response, f'data-clipboard-text="{reason}"')
        self.assertContains(response, "clipboard.min.js")

    def test_should_not_offer_a_copy_button_without_a_reason(self):
        """The running month has no reason yet, so there is nothing to copy.

        Asserted on the data attribute, not the class: the class also appears
        in the script that initialises Clipboard.js, on every page.
        """
        response = self.overview()

        self.assertNotContains(response, "data-clipboard-text")

    def test_should_swap_the_icon_style_for_the_success_check(self):
        """Font Awesome Free has no regular check. Leaving fa-regular in place
        drew a placeholder box instead of a tick.

        Shallow guard on the emitted script, not on the browser behaviour."""
        script = read_static("overview.js")

        self.assertIn('replace("fa-regular", "fa-solid")', script)
        self.assertIn('replace("fa-solid", "fa-regular")', script)

    def test_should_mark_a_corporation_without_ingame_tax(self):
        """At zero percent nothing reaches the corporation wallet, so the row
        owing nothing says nothing about what the corporation earned."""
        self.row.tax_percentage = 0
        self.row.save()

        response = self.overview()

        self.assertContains(response, "text-danger")
        self.assertContains(response, "fa-triangle-exclamation")

    def test_should_leave_a_taxing_corporation_unmarked(self):
        response = self.overview()

        self.assertNotContains(response, "fa-triangle-exclamation")

    def test_should_search_case_insensitively(self):
        self.assertIn("caseInsensitive: true", read_static("overview.js"))


class TestMenuBadge(EosTaxTestCase):
    """The badge is Alliance Auth's own `count` on the menu item."""

    def setUp(self):
        previous = datetime.datetime.now() - relativedelta(months=1)
        config = TaxConfiguration.get_solo()
        config.last_month = True
        config.save()

        self.row = create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        self.row.month = previous.month
        self.row.year = previous.year
        self.row.save()

    def rendered_for(self, permissions):
        user = create_user(
            "badge", 95000010, BRAVO_CORP_ID, "Bravo Corp", permissions
        )
        request = RequestFactory().get(reverse("eos_tax:index"))
        request.user = user

        item = EosTaxMenuItem()
        item.render(request)

        return item

    def test_should_count_what_is_due(self):
        self.assertEqual(self.rendered_for(["basic_access"]).count, 1)

    def test_should_hide_the_badge_with_nothing_due(self):
        """None, not zero - Alliance Auth renders a zero as a badge."""
        self.row.payed = True
        self.row.save()

        self.assertIsNone(self.rendered_for(["basic_access"]).count)

    def test_should_render_nothing_without_access(self):
        user = create_user("outsider", 95000011, BRAVO_CORP_ID, "Bravo Corp", [])
        request = RequestFactory().get(reverse("eos_tax:index"))
        request.user = user

        self.assertEqual(EosTaxMenuItem().render(request), "")


class TestHelpBlock(EosTaxTestCase):
    def setUp(self):
        self.client.force_login(
            create_user(
                "helper",
                91000006,
                BRAVO_CORP_ID,
                "Bravo Corp",
                ["basic_access", "admin_view"],
            )
        )

    def test_should_show_payment_help_only_on_overview(self):
        overview = self.client.get(reverse("eos_tax:index"))
        settings_page = self.client.get(reverse("eos_tax:settings"))

        self.assertContains(overview, "How to pay taxes?")
        self.assertNotContains(settings_page, "How to pay taxes?")


class TestNavigationOnDetailPages(EosTaxTestCase):
    """A detail page keeps its own section lit.

    navactive matches the resolved view name, so a detail view under a section
    does not light that section unless it is named. Losing the highlight is
    worst exactly here: the way back out of a detail page is a link, and the
    navbar is where a reader looks for it.
    """

    def setUp(self):
        self.client.force_login(
            create_user(
                "navdetail", 97000040, BRAVO_CORP_ID, "Bravo Corp", ["admin_view"]
            )
        )

    def active_entries(self, url):
        """The navbar entries drawn as current, by their text."""
        body = self.client.get(url).content.decode()

        return re.findall(
            r'aria-current="page">\s*([^<]+?)\s*</a>', body
        )

    def test_should_light_bots_on_a_character_detail(self):
        entries = self.active_entries(
            reverse("eos_tax:bot_detail", args=[2100000001])
        )

        self.assertIn("Bots", entries)

    def test_should_light_corp_tax_changes_on_a_corporation_detail(self):
        entries = self.active_entries(
            reverse("eos_tax:tax_change_detail", args=[BRAVO_CORP_ID])
        )

        self.assertIn("Corp Tax Changes", entries)

    def test_should_light_exactly_one_section(self):
        """Naming several views must not light several entries."""
        entries = self.active_entries(
            reverse("eos_tax:bot_detail", args=[2100000001])
        )

        self.assertEqual(len(entries), 1)


class TestScriptConfiguration(EosTaxTestCase):
    """Each page hands its own script the strings it needs.

    A static file cannot reach the catalogue, so the view builds a dictionary
    and the page emits it as json_script. Renaming either end breaks the page
    only in the browser - the response still renders, so nothing here would
    fail without this.
    """

    ELEMENT = 'id="eos-tax-config"'

    def setUp(self):
        self.client.force_login(
            create_user(
                "scripts", 97000030, BRAVO_CORP_ID, "Bravo Corp",
                ["basic_access", "admin_view"],
            )
        )
        enable_current_month()

    def config(self, name):
        response = self.client.get(reverse(f"eos_tax:{name}"))
        body = response.content.decode()

        self.assertIn(self.ELEMENT, body, f"{name} carries no configuration")

        raw = body.split(self.ELEMENT, 1)[1].split(">", 1)[1].split("</script>", 1)[0]

        return json.loads(html.unescape(raw))

    def test_should_give_the_overview_its_search_labels(self):
        config = self.config("index")

        self.assertEqual(
            sorted(config), ["searchLabel", "searchPlaceholder"]
        )

    def test_should_give_corp_tax_changes_its_search_labels(self):
        config = self.config("tax_changes")

        self.assertEqual(
            sorted(config), ["searchLabel", "searchPlaceholder"]
        )

    def test_should_give_the_statistics_its_url_and_texts(self):
        config = self.config("statistics")

        self.assertEqual(config["dataUrl"], reverse("eos_tax:statistics_data"))
        self.assertEqual(
            sorted(config["text"]),
            ["corporations", "covered", "empty", "error", "income", "loading",
             "other", "shown", "tax"],
        )

    def test_should_translate_what_it_hands_over(self):
        """The strings stay lazy until the response renders, so they arrive in
        the reader's language rather than in the one the worker started in."""
        response = self.client.get(
            reverse("eos_tax:index"), headers={"accept-language": "de"}
        )
        body = response.content.decode()
        raw = body.split(self.ELEMENT, 1)[1].split(">", 1)[1].split("</script>", 1)[0]

        self.assertEqual(
            json.loads(html.unescape(raw))["searchPlaceholder"],
            "Nach Corporation-Namen filtern",
        )


class TestNarrowScreens(EosTaxTestCase):
    """What the overview drops on a phone, and what it must not drop.

    The overview is the only page without admin_view, so it is the one every
    member opens on a telephone. Seven columns do not fit; the four that carry
    the purpose of the page - which Corporation, how much, for which month,
    the reason to copy and whether it is paid - stay.
    """

    def setUp(self):
        self.user = create_user(
            "member", 97000001, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"]
        )
        enable_current_month()
        self.row = create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        self.client.force_login(self.user)

    def overview(self):
        return self.client.get(reverse("eos_tax:index"))

    def test_should_hide_the_two_rate_columns(self):
        body = self.overview().content.decode()

        for label in ("Ingame Corp Tax", "Alliance Tax"):
            with self.subTest(column=label):
                self.assertIn(
                    f'<th scope="col" class="d-none d-md-table-cell">{label}</th>',
                    body,
                )

    def test_should_keep_the_columns_the_page_is_for(self):
        body = self.overview().content.decode()

        for label in ("Corporation", "Amount to pay in Isk", "Month", "Reason",
                      "Payed"):
            with self.subTest(column=label):
                self.assertIn(f'<th scope="col">{label}</th>', body)

    def test_should_keep_the_zero_rate_warning_where_it_stays_visible(self):
        """The hidden rate column carried the red marking; the Corporation
        cell carries it too, and that one is never hidden."""
        self.row.tax_percentage = 0
        self.row.save()

        body = self.overview().content.decode()

        self.assertIn("fa-triangle-exclamation", body)
        self.assertIn('<th scope="row" class="text-danger">', body)


class TestNavigation(EosTaxTestCase):
    PAGES = ["index", "statistics", "settings"]

    def setUp(self):
        self.user = create_user(
            "navigator",
            91000009,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)

    def nav_bar(self, page):
        """Return only the left hand app navbar, so the sidebar cannot match."""
        body = self.client.get(reverse(f"eos_tax:{page}")).content.decode()
        match = re.search(r'<ul id="nav-left".*?</ul>', body, re.S)
        self.assertIsNotNone(match, "navbar container not found")

        return match.group(0)

    def nav_entry(self, navbar, page):
        href = reverse(f"eos_tax:{page}")
        for entry in re.finditer(r'<li class="nav-item">.*?</li>', navbar, re.S):
            if f'href="{href}"' in entry.group(0):
                return entry.group(0)

        return ""

    def test_should_show_all_three_entries_on_every_page(self):
        for page in self.PAGES:
            navbar = self.nav_bar(page)
            for entry in self.PAGES:
                with self.subTest(page=page, entry=entry):
                    self.assertNotEqual(self.nav_entry(navbar, entry), "")

    def test_should_label_the_entries(self):
        navbar = self.nav_bar("index")

        for label in ("Overview", "Statistics", "Settings"):
            with self.subTest(label=label):
                self.assertIn(label, navbar)

    def test_should_colour_only_the_current_entry(self):
        for page in self.PAGES:
            navbar = self.nav_bar(page)

            for entry in self.PAGES:
                with self.subTest(page=page, entry=entry):
                    markup = self.nav_entry(navbar, entry)
                    if entry == page:
                        self.assertIn("text-warning", markup)
                        self.assertNotIn("text-white-50", markup)
                    else:
                        self.assertIn("text-white-50", markup)
                        self.assertNotIn("text-warning", markup)

    def test_should_mark_the_current_entry_for_screen_readers(self):
        for page in self.PAGES:
            navbar = self.nav_bar(page)

            for entry in self.PAGES:
                with self.subTest(page=page, entry=entry):
                    markup = self.nav_entry(navbar, entry)
                    if entry == page:
                        self.assertIn('aria-current="page"', markup)
                    else:
                        self.assertNotIn("aria-current", markup)

    def test_should_render_plain_links_instead_of_buttons(self):
        navbar = self.nav_bar("index")

        self.assertNotIn("btn btn-", navbar)

    def test_should_hide_admin_pages_without_admin_view(self):
        """Statistics and settings are admin only - do not offer dead links."""
        self.client.force_login(
            create_user(
                "member-only", 91000011, BRAVO_CORP_ID, "Bravo Corp", ["basic_access"]
            )
        )

        navbar = self.nav_bar("index")

        self.assertNotEqual(self.nav_entry(navbar, "index"), "")
        self.assertEqual(self.nav_entry(navbar, "statistics"), "")
        self.assertEqual(self.nav_entry(navbar, "settings"), "")
