from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.framework.api.user import get_all_characters_from_user
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls
from eos_tax.db.payments import get_all_corps_for_user, get_open_payment_count
from .util import get_dates


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
        if not request.user.has_perm("eos_tax.basic_access"):
            return ""

        # `count` is Alliance Auth's own badge on the menu entry - the same one
        # hrapplications, srp and corptools use. None hides it, so a user with
        # nothing outstanding sees the entry exactly as before.
        admin = request.user.has_perm("eos_tax.admin_view")
        corps = get_all_corps_for_user(get_all_characters_from_user(request.user))
        due = get_open_payment_count(get_dates(), admin=admin, corps=corps)

        self.count = due if due else None

        return MenuItemHook.render(self, request)


@hooks.register("menu_item_hook")
def register_menu():
    return EosTaxMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "eos_tax", r"^eos_tax/")
