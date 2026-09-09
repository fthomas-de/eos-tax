import gettext
import pathlib
import re

from eos_tax.tests.base import EosTaxTestCase
from django.urls import reverse
from django.utils import translation

import eos_tax
from eos_tax.models import TaxConfiguration

from .test_views import BRAVO_CORP_ID, create_tax_row, create_user, enable_current_month

GERMAN = {"accept-language": "de"}

LOCALE_ROOT = pathlib.Path(eos_tax.__file__).parent / "locale"
PO_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(raw):
    return raw.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def read_po(path):
    """Minimal .po reader - enough to compare a catalogue against its build."""
    entries = []
    msgid = None
    parts = []
    section = None

    def flush():
        nonlocal msgid, parts, section
        if section == "msgstr" and msgid is not None:
            entries.append((msgid, _unescape("".join(parts))))
        msgid, parts, section = None, [], None

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            flush()
            section, parts = "msgid", PO_STRING.findall(line)
        elif line.startswith("msgstr "):
            msgid = _unescape("".join(parts))
            section, parts = "msgstr", PO_STRING.findall(line)
        elif line.startswith('"') and section:
            parts += PO_STRING.findall(line)
        else:
            flush()

    flush()

    return entries


class TestCatalogueIntegrity(EosTaxTestCase):
    """The compiled catalogues are committed, the way Alliance Auth and
    corptools do it - their wheels ship the .mo, there is no build hook and no
    deploy step.

    The risk of that approach is drift: an edited .po whose .mo was never
    rebuilt looks exactly like a missing translation, and nothing complains.
    These checks turn that into a failing test.
    """

    def catalogues(self):
        return sorted(LOCALE_ROOT.glob("*/LC_MESSAGES/django.po"))

    def test_should_ship_a_catalogue_per_language(self):
        found = {path.parents[1].name for path in self.catalogues()}

        self.assertEqual(found, {"de", "es", "fr_FR", "it_IT", "ko_KR", "ru"})

    def test_should_have_a_compiled_file_next_to_every_source(self):
        for po_path in self.catalogues():
            with self.subTest(locale=po_path.parents[1].name):
                self.assertTrue(
                    po_path.with_suffix(".mo").exists(),
                    "django.mo is missing - run compilemessages and commit it",
                )

    def test_should_have_no_untranslated_entry(self):
        for po_path in self.catalogues():
            locale = po_path.parents[1].name
            missing = [
                msgid for msgid, msgstr in read_po(po_path) if msgid and not msgstr
            ]

            with self.subTest(locale=locale):
                self.assertEqual(missing, [], f"{locale}: untranslated entries")

    def test_compiled_catalogue_should_match_its_source(self):
        """Catches the stale .mo: every string in the .po has to come back out
        of the compiled file."""
        for po_path in self.catalogues():
            locale = po_path.parents[1].name
            catalogue = gettext.translation(
                "django", localedir=str(LOCALE_ROOT), languages=[locale]
            )

            for msgid, msgstr in read_po(po_path):
                if not msgid or not msgstr:
                    continue

                with self.subTest(locale=locale, msgid=msgid[:40]):
                    self.assertEqual(
                        catalogue.gettext(msgid),
                        msgstr,
                        f"{locale}: django.mo is out of date, run compilemessages",
                    )


class TestGermanCatalogue(EosTaxTestCase):
    """Without a compiled catalogue every translate tag silently falls back to
    English, which looks exactly like a missing translation."""

    def setUp(self):
        self.user = create_user(
            "uebersetzer",
            95000001,
            BRAVO_CORP_ID,
            "Bravo Corp",
            ["basic_access", "admin_view"],
        )
        self.client.force_login(self.user)

    def test_should_translate_marked_strings(self):
        with translation.override("de"):
            self.assertEqual(str(translation.gettext("Overview")), "Übersicht")
            self.assertEqual(str(translation.gettext("Settings")), "Einstellungen")

    def test_should_translate_the_navigation(self):
        response = self.client.get(reverse("eos_tax:index"), headers=GERMAN)

        self.assertContains(response, "Übersicht")
        self.assertContains(response, "Einstellungen")

    def test_should_translate_the_overview_table(self):
        # the headers only exist once there is a row to show
        enable_current_month()
        create_tax_row(BRAVO_CORP_ID, "Bravo Corp", payed=False)

        response = self.client.get(reverse("eos_tax:index"), headers=GERMAN)

        self.assertContains(response, "Zu zahlen in ISK")
        self.assertContains(response, "Reason")

    def test_should_translate_the_payment_help(self):
        response = self.client.get(reverse("eos_tax:index"), headers=GERMAN)

        self.assertContains(response, "Wie zahle ich Steuern?")

    def test_should_translate_the_bots_page(self):
        response = self.client.get(reverse("eos_tax:bots"), headers=GERMAN)

        self.assertContains(response, "Anzeigen")
        self.assertContains(response, "Stundenblöcke")
        self.assertContains(
            response, "Kein Character hat in diesem Monat beide Schwellen"
        )

    def test_should_translate_the_settings_form(self):
        response = self.client.get(reverse("eos_tax:settings"), headers=GERMAN)

        self.assertContains(response, "Besteuerte Alliances")
        self.assertContains(response, "Holding Corporation")
        self.assertContains(response, "Steuersatz-Zeitplan")

    def test_should_translate_the_statistics_controls(self):
        TaxConfiguration.get_solo()  # the page needs the singleton
        response = self.client.get(reverse("eos_tax:statistics"), headers=GERMAN)

        self.assertContains(response, "Noch keine Steuerdaten erfasst.")

    def test_should_serve_every_shipped_language(self):
        """One distinctive word per catalogue - a missing or broken .mo would
        silently fall back to English and look like a translation gap."""
        expected = {
            "de": "Übersicht",
            "es": "Resumen",
            "fr-fr": "Aperçu",
            "it-it": "Panoramica",
            "ko-kr": "개요",
            "ru": "Обзор",
        }

        for code, word in expected.items():
            with self.subTest(language=code):
                response = self.client.get(
                    reverse("eos_tax:index"), headers={"accept-language": code}
                )
                self.assertContains(response, word)

    def test_should_leave_eve_jargon_in_english(self):
        """Alliance stays Alliance inside our own labels.

        Checking the whole page for the absence of a translated term does not
        work: Alliance Auth renders its own chrome through its own catalogues,
        so "Personnage" legitimately appears on a French page.
        """
        expected = {
            "de": "Besteuerte Alliances",
            "es": "Alliances gravadas",
            "fr-fr": "Alliances taxées",
            "it-it": "Alliances tassate",
            "ko-kr": "과세 대상 Alliance",
            "ru": "Облагаемые Alliances",
        }

        for code, label in expected.items():
            with self.subTest(language=code):
                response = self.client.get(
                    reverse("eos_tax:settings"), headers={"accept-language": code}
                )
                self.assertContains(response, label)
                self.assertContains(response, "Holding Corporation")

    def test_should_keep_english_untouched(self):
        response = self.client.get(
            reverse("eos_tax:index"), headers={"accept-language": "en"}
        )

        self.assertContains(response, "Overview")
        self.assertNotContains(response, "Übersicht")
