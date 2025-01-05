from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls


class EosTaxMenuItem(MenuItemHook):
    """This class ensures only authorized users will see the menu entry"""

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _("Alliance PvE Tax"),
            "fa fa-credit-card",
            "eos_tax:index",
            navactive=["eos_tax:"],
        )

    def render(self, request):
        if request.user.has_perm("eos_tax.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return EosTaxMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "eos_tax", r"^eos_tax/")
