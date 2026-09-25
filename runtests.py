#!/usr/bin/env python
"""Run the test suite without an Alliance Auth instance, on testauth.

    python runtests.py eos_tax [manage.py test options]

testauth/settings/local.py names a database of its own, never a real Auth
one; the test runner creates test_<that name> next to it and drops it again.
MySQL and Redis on localhost have to run, as for Alliance Auth itself.
"""

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testauth.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # the command line itself, with "test" put in front of what was given.
    # This used to hand over the return value of list.insert - None - and
    # only worked because Django then falls back to reading sys.argv.
    execute_from_command_line([sys.argv[0], "test", *sys.argv[1:]])
