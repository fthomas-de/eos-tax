import datetime
import re

from dateutil.relativedelta import relativedelta

from django.contrib.auth.models import Permission, User
from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from eos_tax.models import MonthlyTax, TaxConfiguration
from eos_tax.util import get_amount_to_pay

BRAVO_CORP_ID = 98000001
ALPHA_CORP_ID = 98000002


def create_user(username, character_id, corporation_id, corporation_name, permissions=()):
    """Build a user AA will actually let through to an app view.

    Every url registered through a UrlHook is wrapped in
    ``main_character_required``, so a user without an owned main character is
    redirected to the dashboard regardless of their permissions.
    """
    user = User.objects.create_user(username, f"{username}@example.com", "password")

    character = EveCharacter.objects.create(
        character_id=character_id,
        character_name=f"{username} character",
        corporation_id=corporation_id,
        corporation_name=corporation_name,
        corporation_ticker=corporation_name[:5].upper(),
    )
    CharacterOwnership.objects.create(
        character=character, user=user, owner_hash=f"owner-hash-{character_id}"
    )
    user.profile.main_character = character
    user.profile.save()

    for codename in permissions:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="eos_tax", codename=codename)
        )

    return User.objects.get(pk=user.pk)  # drop the cached permissions


def enable_current_month():
    """The overview shows nothing unless at least one month is switched on."""
    config = TaxConfiguration.get_solo()
    config.current_month = True
    config.save()

    return config


def create_tax_row(corp_id, corp_name, payed, tax_value=1_000_000_000, tax_percentage=10.0):
    now = datetime.datetime.now()

    return MonthlyTax.objects.create(
        corp_id=corp_id,
        corp_name=corp_name,
        tax_value=tax_value,
        tax_percentage=tax_percentage,
        month=now.month,
        year=now.year,
        payed=payed,
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

    def test_should_list_every_corporation_for_admin(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.client.get(reverse("eos_tax:index"))

        self.assertContains(response, "Bravo Corp")
        self.assertContains(response, "Alpha Corp")

    def test_should_sort_unpaid_before_paid(self):
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        body = self.client.get(reverse("eos_tax:index")).content.decode()

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
        create_tax_row(ALPHA_CORP_ID, "Alpha Corp", payed=True)

        response = self.overview()

        self.assertContains(response, 'data-order="0"')
        self.assertContains(response, 'data-order="1"')

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
        checks the emitted config, not the browser behaviour."""
        body = self.overview().content.decode()

        self.assertEqual(body.count("searchable: true"), 1)
        self.assertEqual(body.count("searchable: false"), 6)
        self.assertNotIn('targets: "_all"', body)

    def test_should_show_the_applied_alliance_tax_rate(self):
        """The rate is stored as a fraction and shown as a percentage."""
        self.row.alliance_tax_rate = 0.07
        self.row.save()

        self.assertContains(self.overview(), '<td data-order="7.0">7.0%</td>', html=False)

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
        body = self.overview().content.decode()

        self.assertIn('replace("fa-regular", "fa-solid")', body)
        self.assertIn('replace("fa-solid", "fa-regular")', body)

    def test_should_search_case_insensitively(self):
        self.assertContains(self.overview(), "caseInsensitive: true")


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
