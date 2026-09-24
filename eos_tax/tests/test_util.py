"""Formatting helpers used across more than one reading.

`format_clock` and `format_duration` are tested next to the tab that
introduced them (`test_bot_signals.py`) because nothing else uses them yet.
`format_age` is different - the character list and the character page both
call it - so it gets a file of its own instead of attaching to either.
"""
import datetime

from django.utils import translation

from eos_tax.tests.base import EosTaxTestCase
from eos_tax.util import format_age


class TestFormatAge(EosTaxTestCase):
    """A character's age: one unit, not a calendar.

    A column has no room for "3 years, 2 months", and the day this reads as
    a bot detection signal - a character ratting round the clock a week
    after creation - the remainder never matters, only the order of
    magnitude.

    The units themselves are translated (gettext("d")/("mo")/("y")), and
    Django's active language is a thread-local another test's request can
    leave switched on - a request with an Accept-Language header activates
    it but nothing deactivates it again once the test method returns. This
    pins English regardless of what ran before it in the same process,
    rather than assuming a clean slate.
    """

    TODAY = datetime.date(2026, 9, 14)

    def setUp(self):
        translation.activate("en")
        self.addCleanup(translation.deactivate)

    def age(self, birthday):
        return format_age(birthday, today=self.TODAY)

    def test_should_say_nothing_for_an_unknown_birthday(self):
        self.assertEqual(self.age(None), "")

    def test_should_write_days_under_a_month(self):
        self.assertEqual(self.age(self.TODAY), "0 d")
        self.assertEqual(self.age(self.TODAY - datetime.timedelta(days=29)), "29 d")

    def test_should_write_months_from_thirty_days(self):
        self.assertEqual(self.age(self.TODAY - datetime.timedelta(days=30)), "1 mo")
        self.assertEqual(self.age(self.TODAY - datetime.timedelta(days=364)), "12 mo")

    def test_should_write_years_from_a_full_year(self):
        self.assertEqual(self.age(self.TODAY - datetime.timedelta(days=365)), "1 y")
        self.assertEqual(self.age(self.TODAY - datetime.timedelta(days=365 * 8)), "8 y")

    def test_should_say_nothing_for_a_birthday_in_the_future(self):
        """ESI has never handed this app a birthday after today, but a
        clock skew between the app and the database is not this function's
        problem to guess at - silence is safer than a negative age."""
        self.assertEqual(self.age(self.TODAY + datetime.timedelta(days=1)), "")
