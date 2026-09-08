import datetime
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from eos_tax.models import MonthlyTax

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


# get_dates returns nothing unless at least one month is switched on
@mock.patch("eos_tax.util.CURRENT_MONTH", True)
class TestIndexAccess(TestCase):
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


@mock.patch("eos_tax.util.CURRENT_MONTH", True)
class TestIndexContent(TestCase):
    def setUp(self):
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


@mock.patch("eos_tax.util.CURRENT_MONTH", True)
class TestIndexMarkup(TestCase):
    """Guards the Bootstrap 5 rewrite against a relapse into Bootstrap 3."""

    BOOTSTRAP5_CLASSES = ["card-header", "card-title mb-0", "card-body", "table-responsive"]
    BOOTSTRAP3_CLASSES = ["panel panel-primary", "panel-heading", "panel-title", "panel-body"]

    def setUp(self):
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
        """Fetch inside the test method - a class level mock.patch does not
        cover setUp, so a request made there would see CURRENT_MONTH as False
        and never render the table."""
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
