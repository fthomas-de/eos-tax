"""Shared test case for this app.

django-solo keeps the configuration singleton in the cache backend named by
``SOLO_CACHE``, which a real install sets. A ``TestCase`` rolls its transaction
back but the cache keeps what was written, so a configuration saved in one test
survived into the next and still pointed at a corporation that no longer
existed - the next ``save()`` then failed on the foreign key.

Production commits its transactions, so the leak is an artefact of the test
harness rather than a defect in the app. The cache is switched off here instead
of being cleared in every ``setUp``.
"""

import html
import json
import pathlib

from django.test import TestCase, override_settings

import eos_tax


@override_settings(SOLO_CACHE=None)
class EosTaxTestCase(TestCase):
    """Base class for every test in this app."""


def read_static(name):
    """The source of one of the app's own script files.

    The tests that check a DataTables config or a Font Awesome class swap
    always read source rather than drive a browser; the source just moved out
    of the template. Reading the file the template names keeps them honest -
    a page that stopped loading the script would still pass, which is why the
    pages assert the reference separately.
    """
    path = pathlib.Path(eos_tax.__file__).parent / "static/eos_tax/js" / name

    return path.read_text(encoding="utf-8")


def json_script(body, element_id):
    """The value of a `{{ x|json_script:"..." }}` element, parsed as JSON.

    Parsed rather than grepped: a chart's data attribute can hold the right
    characters as a substring of something else entirely, and a `canvas`
    with an empty script beside it is a chart that stays blank without the
    server ever finding out. Three modules carried their own copy of this.
    """
    marker = f'id="{element_id}"'
    parts = body.split(marker, 1)
    assert len(parts) == 2, f"no element with {marker} in the page"

    raw = parts[1].split(">", 1)[1].split("</script>", 1)[0]

    return json.loads(html.unescape(raw))


def read_stylesheet():
    """The app's one stylesheet - the rules that used to sit in <style>
    blocks of their own templates."""
    path = pathlib.Path(eos_tax.__file__).parent / "static/eos_tax/css/eos_tax.css"

    return path.read_text(encoding="utf-8")


def table_body(response):
    """The rows of the first table on a page, as markup.

    Alliance Auth's sidebar prints the main's Corporation before the
    content, so a name asserted against the whole page is found there
    whatever the table holds - every test user sits in a Corporation.
    """
    body = response.content.decode()

    if "<tbody>" not in body:
        return ""

    return body.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
