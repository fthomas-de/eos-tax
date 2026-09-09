from django.conf import settings

# These are no longer read at runtime. They only seed the database configuration
# the first time migration 0005 runs, so an existing install keeps behaving the
# way its local.py described. Afterwards the settings page is the single source
# of truth and changes here have no effect.
DEFAULT_LAST_MONTH = getattr(settings, "LAST_MONTH", False)
DEFAULT_CURRENT_MONTH = getattr(settings, "CURRENT_MONTH", False)
DEFAULT_TAX_ALLIANCES = getattr(settings, "TAX_ALLIANCES", [])
DEFAULT_TAX_CORPORATIONS = getattr(settings, "TAX_CORPORATIONS", [])
DEFAULT_CORPORATION_BLACKLIST = getattr(settings, "CORPORATION_BLACKLIST", [])
DEFAULT_TAX_RATE = getattr(settings, "TAX_RATE", 1)
DEFAULT_TAX_TYPES = getattr(settings, "TAX_TYPES", ["bounty_prizes"])
DEFAULT_USE_REASON = getattr(settings, "USE_REASON", False)


def get_config():
    """The editable configuration.

    Call this where the value is needed. Binding it at import time would give
    every process its own frozen copy, and an edit on the settings page would
    only surface after restarting gunicorn and every celery worker.
    """
    from eos_tax.models import TaxConfiguration

    return TaxConfiguration.get_solo()
