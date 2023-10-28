from django.conf import settings

# put your app settings here



LAST_MONTH = getattr(settings, "LAST_MONTH", False)
CURRENT_MONTH = getattr(settings, "CURRENT_MONTH", False)
TAX_ALLIANCES = getattr(settings, "TAX_ALLIANCES", [])
TAX_RATE = getattr(settings, "TAX_RATE", 1)
TAX_TYPES = getattr(settings, "TAX_TYPES", ["bounty_prizes"])