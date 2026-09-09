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

from django.test import TestCase, override_settings


@override_settings(SOLO_CACHE=None)
class EosTaxTestCase(TestCase):
    """Base class for every test in this app."""
