"""Helpers several pages share, tested with hand built values."""

from eos_tax.db.shared import level_for
from eos_tax.tests.base import EosTaxTestCase


class TestLevels(EosTaxTestCase):
    """How alarming a row is said to be, and where the bands sit."""

    def test_should_band_a_score_in_thirds(self):
        self.assertEqual(level_for(0.0), "low")
        self.assertEqual(level_for(0.34), "medium")
        self.assertEqual(level_for(0.67), "high")

    def test_should_let_the_top_band_be_moved(self):
        """A score measured against a configured threshold has to reach it,
        not two thirds of it."""
        self.assertEqual(level_for(0.8), "high")
        self.assertEqual(level_for(0.8, top=1.0), "medium")
        self.assertEqual(level_for(1.0, top=1.0), "high")
