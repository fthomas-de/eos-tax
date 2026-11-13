from esi.openapi_clients import ESIClientProvider

from allianceauth.eveonline import __esi_compatibility_date__

from eos_tax import VERSION

# the scope that lets ESI open a window in the reader's own EVE client
ESI_SCOPE_UI_OPEN_WINDOW = "esi-ui.open_window.v1"

# Alliance Auth's open_api_provider is cut down to its own operations and
# has no UI ones, so the in-game window needs a client of its own
esi = ESIClientProvider(
    __esi_compatibility_date__,
    "eos-tax",
    VERSION,
    "https://github.com/fthomas-de/eos-tax",
    operations=["PostUiOpenwindowInformation"],
)
