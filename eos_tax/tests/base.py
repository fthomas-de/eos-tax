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
