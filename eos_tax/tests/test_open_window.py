"""Information windows in the reader's own EVE client, from the bots page."""

import inspect
from types import SimpleNamespace
from unittest import mock

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from eos_tax import views
from eos_tax.models import UiCharacter
from eos_tax.tests.base import EosTaxTestCase, read_static

from .factories import (
    BRAVO_CORP_ID,
    TAXED_ALLIANCE_ID,
    add_window_token,
    configure,
    create_alliance,
    create_alt,
    create_corporation,
    create_user,
)

TARGET_ID = 95000001


class OpenWindowTestCase(EosTaxTestCase):
    def setUp(self):
        taxed = create_alliance(TAXED_ALLIANCE_ID, "Taxed Alliance")
        create_corporation(BRAVO_CORP_ID, "Bravo Corp", taxed)
        configure()
        self.hunter = create_user(
            "hunter", 93200001, BRAVO_CORP_ID, "Bravo Corp", ["gm_bots_access"]
        )
        self.main = self.hunter.profile.main_character
        self.alt = create_alt(self.hunter, 93200002, "Hunter Alt")
        self.stranger = create_user("stranger", 93200003, BRAVO_CORP_ID, "Bravo Corp")
        self.client.force_login(self.hunter)

        patcher = mock.patch.object(views, "esi")
        self.esi = patcher.start()
        self.addCleanup(patcher.stop)
        self.call = self.esi.client.User_Interface.PostUiOpenwindowInformation

    def choose(self, character):
        UiCharacter.objects.create(user=self.hunter, character=character)

    def open(self):
        response = self.client.post(reverse("eos_tax:open_window", args=[TARGET_ID]))
        self.assertEqual(response.status_code, 200)

        return response.json()["message"]


class TestDropdown(OpenWindowTestCase):
    def test_should_offer_only_own_characters_with_a_window_token(self):
        add_window_token(self.hunter, self.alt)
        # a token without the scope, and someone else's character
        add_window_token(self.hunter, self.main, scope="esi-wallet.read_character_wallet.v1")
        add_window_token(self.stranger, self.stranger.profile.main_character)

        options = [c.character_id for c in views._ui_characters(self.hunter)]

        self.assertEqual(options, [self.alt.character_id])

    def test_should_mark_the_chosen_character(self):
        add_window_token(self.hunter, self.alt)
        self.choose(self.alt)

        body = self.client.get(reverse("eos_tax:bots")).content.decode()

        self.assertIn(f'value="{self.alt.character_id}" selected', body)
        self.assertIn(reverse("eos_tax:ui_character_add"), body)
        self.assertIn("eos_tax/js/open-window.", body)


class TestSelect(OpenWindowTestCase):
    url = reverse("eos_tax:ui_character_select")

    def test_should_save_an_own_character_with_a_token(self):
        add_window_token(self.hunter, self.alt)

        response = self.client.post(self.url, {"character_id": self.alt.character_id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UiCharacter.objects.get(user=self.hunter).character, self.alt)

    def test_should_refuse_a_character_it_does_not_offer(self):
        stranger_main = self.stranger.profile.main_character
        add_window_token(self.stranger, stranger_main)

        for character in (self.main, stranger_main):  # no token / not theirs
            with self.subTest(character=character.character_name):
                response = self.client.post(
                    self.url, {"character_id": character.character_id}
                )

                self.assertEqual(response.status_code, 400)
        self.assertFalse(UiCharacter.objects.exists())

    def test_should_refuse_a_non_number(self):
        response = self.client.post(self.url, {"character_id": "abc"})

        self.assertEqual(response.status_code, 400)

    def test_should_clear_the_choice_when_empty(self):
        self.choose(self.alt)

        self.client.post(self.url, {"character_id": ""})

        self.assertFalse(UiCharacter.objects.exists())


class TestAdd(OpenWindowTestCase):
    def add(self, token):
        request = RequestFactory().get(reverse("eos_tax:ui_character_add"))
        request.user = self.hunter
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        # past the SSO round trip, which a test cannot make
        inspect.unwrap(views.ui_character_add)(request, token)

        return [str(message) for message in get_messages(request)]

    def test_should_take_an_own_character(self):
        self.add(add_window_token(self.hunter, self.alt))

        self.assertEqual(UiCharacter.objects.get(user=self.hunter).character, self.alt)

    def test_should_refuse_someone_elses_character(self):
        stranger_main = self.stranger.profile.main_character
        # unsaved: saving a token makes Alliance Auth hand the character's
        # ownership to the token's user, the very case this guards against
        token = SimpleNamespace(
            character_id=stranger_main.character_id,
            character_name=stranger_main.character_name,
        )

        found = self.add(token)

        self.assertFalse(UiCharacter.objects.exists())
        self.assertIn("is not one of your characters", found[0])


class TestOpen(OpenWindowTestCase):
    def test_should_open_the_window_with_the_chosen_token(self):
        token = add_window_token(self.hunter, self.alt)
        self.choose(self.alt)

        message = self.open()

        self.call.assert_called_once_with(target_id=TARGET_ID, token=token)
        self.assertIn("Opened", message)

    def test_should_ask_for_a_character_first(self):
        message = self.open()

        self.call.assert_not_called()
        self.assertIn("Choose your in-game character", message)

    def test_should_say_when_the_token_is_gone(self):
        # chosen once, the token deleted since - or one of the scope's
        # siblings left behind
        add_window_token(self.hunter, self.alt, scope="esi-wallet.read_character_wallet.v1")
        self.choose(self.alt)

        message = self.open()

        self.call.assert_not_called()
        self.assertIn("add it again", message)

    def test_should_not_use_another_users_token(self):
        # the same character registered twice is not possible, but a token of
        # the character under another user is - and must not open anything
        add_window_token(self.stranger, self.alt)
        self.choose(self.alt)

        self.open()

        self.call.assert_not_called()

    def test_should_say_when_esi_refuses(self):
        add_window_token(self.hunter, self.alt)
        self.choose(self.alt)
        self.call.return_value.result.side_effect = Exception("520")

        with self.assertLogs("extensions.eos_tax.views", "WARNING"):
            message = self.open()

        self.assertIn("logged in to EVE", message)

    def test_should_refuse_get_and_readers_without_access(self):
        url = reverse("eos_tax:open_window", args=[TARGET_ID])

        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("eos_tax:ui_character_select")).status_code, 403
        )


class TestButtons(OpenWindowTestCase):
    row = SimpleNamespace(character_id=TARGET_ID, character_name="Ratter", main_name="")

    def test_should_sit_beside_every_listed_name(self):
        button = f'data-eos-open-window="{reverse("eos_tax:open_window", args=[TARGET_ID])}"'
        rendered = {
            # the first tab
            "bot-table": render_to_string(
                "eos_tax/partials/bot-table.html",
                {"groups": [{"characters": [self.row], "count": 1}], "gm_listed": []},
            ),
            # the other four
            "bot-character-cells": render_to_string(
                "eos_tax/partials/bot-character-cells.html", {"row": self.row}
            ),
        }

        for name, body in rendered.items():
            with self.subTest(template=name):
                self.assertIn(button, body)

    def test_script_should_catch_clicks_on_fetched_tabs(self):
        source = read_static("open-window.js")

        # a listener per button would miss every tab fetched later
        self.assertIn('document.addEventListener("click"', source)
        self.assertIn('closest("[data-eos-open-window]")', source)
