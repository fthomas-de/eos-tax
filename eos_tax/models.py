from datetime import date
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger

from solo.models import SingletonModel

logger = get_extension_logger(__name__)

class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("basic_access", "Can view his corp data"), ("admin_view", "Can view all data"))


class TaxConfiguration(SingletonModel):
    """Runtime configuration, seeded once from the values in local.py.

    These used to be module constants read at import time, so every process
    kept its own copy and a change only took effect after restarting gunicorn
    and each celery worker. Read this through app_settings.get_config().
    """

    tax_alliances = models.ManyToManyField(
        EveAllianceInfo,
        blank=True,
        related_name="+",
        verbose_name=_("Taxed alliances"),
        help_text=_("Corporations of these alliances are taxed."),
    )
    tax_corporation = models.ForeignKey(
        EveCorporationInfo,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("Holding corporation"),
        help_text=_("The single corporation that receives the tax payments."),
    )
    corporation_blacklist = models.ManyToManyField(
        EveCorporationInfo,
        blank=True,
        related_name="+",
        verbose_name=_("Excluded corporations"),
        help_text=_("Never taxed and never listed, even inside a taxed alliance."),
    )
    tax_rate = models.DecimalField(
        verbose_name=_("Alliance tax rate"),
        max_digits=5,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text=_("Share of the gross PvE income a corporation owes. 0.1 means 10 percent."),
    )
    tax_types = models.JSONField(
        verbose_name=_("Taxed journal types"),
        default=list,
        blank=True,
        help_text=_("Wallet journal ref_types counted as PvE income, for example bounty_prizes."),
    )
    last_month = models.BooleanField(
        default=False,
        help_text=_("Include the previous month in calculations and on the overview."),
    )
    current_month = models.BooleanField(
        default=False,
        help_text=_("Include the running month in calculations and on the overview."),
    )
    use_reason = models.BooleanField(
        default=False,
        help_text=_("Match payments by their reason code instead of by amount alone."),
    )
    tax_change_min_points = models.DecimalField(
        verbose_name=_("Corp tax change: smallest move"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.45"),
        validators=[MinValueValidator(Decimal("0.01")),
                    MaxValueValidator(Decimal("100"))],
        help_text=_(
            "In percentage points of the share of the bounty that reaches the "
            "corporation. A move smaller than this is not listed, and days "
            "within it count as one level. Nine percent to ten is one point."
        ),
    )
    bot_min_hours_per_day = models.PositiveSmallIntegerField(
        verbose_name=_("Bot detection: hours per day"),
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text=_(
            "A day counts as suspicious when a character earned taxed income in "
            "more than this many different hours of that day."
        ),
    )
    bot_min_days_per_month = models.PositiveSmallIntegerField(
        verbose_name=_("Bot detection: days per month"),
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text=_(
            "A character is listed once it exceeds this many suspicious days "
            "within the selected month."
        ),
    )

    class Meta:
        verbose_name = _("Tax configuration")

    def __str__(self):
        return "Tax configuration"

    def rate_for(self, year: int, month: int) -> float:
        """Rate in effect for that month.

        Falls back to the base rate above when the schedule does not reach back
        that far, so months predating the first scheduled change keep working.
        """
        scheduled = (
            TaxRate.objects.filter(valid_from__lte=date(year, month, 1))
            .order_by("-valid_from")
            .first()
        )

        return float(scheduled.rate if scheduled else self.tax_rate)

    def alliance_ids(self):
        """EVE alliance ids - the relation stores Alliance Auth primary keys."""
        return list(self.tax_alliances.values_list("alliance_id", flat=True))

    def holding_corporation_id(self):
        """EVE id of the holding corporation, or None while none is configured."""
        return self.tax_corporation.corporation_id if self.tax_corporation else None

    def blacklisted_corporation_ids(self):
        return list(self.corporation_blacklist.values_list("corporation_id", flat=True))


class TaxRate(models.Model):
    """Alliance tax rate from one month onwards.

    Open ended on purpose: the newest entry that is not in the future wins.
    A schedule built this way cannot have gaps or overlapping windows, and a
    change can be entered months in advance.
    """

    valid_from = models.DateField(
        verbose_name=_("Valid from"),
        unique=True,
        help_text=_("First month this rate applies to. Stored as the first of that month."),
    )
    rate = models.DecimalField(
        verbose_name=_("Alliance tax rate"),
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text=_("Share of the gross PvE income. 0.1 means 10 percent."),
    )

    class Meta:
        ordering = ["-valid_from"]
        verbose_name = _("Tax rate")
        verbose_name_plural = _("Tax rate schedule")

    def __str__(self):
        return f"{self.valid_from:%Y-%m}: {self.rate}"

    def save(self, *args, **kwargs):
        # the tax is calculated per month, so a mid month start would be
        # ambiguous - normalise before it can reach the database
        self.valid_from = self.valid_from.replace(day=1)
        super().save(*args, **kwargs)


class MonthlyTax(models.Model):
    corp_id = models.IntegerField(verbose_name=_("Corporation ID"), blank=False)
    month = models.IntegerField(verbose_name=_("Taxed month"), blank=False, default=0)
    year = models.IntegerField(verbose_name=_("Taxed year"), blank=False, default=0)
    corp_name = models.CharField(verbose_name=_("Corporation name"), max_length=254, blank=True, default='')
    tax_value = models.BigIntegerField(verbose_name=_("Tax value"), blank=False, default=0)
    tax_percentage = models.FloatField(verbose_name=_("Tax percentage"), blank=False, default=0)
    payed = models.BooleanField(verbose_name=_("Payed"), default=False)
    class Meta:
        constraints = [
            # set_corp_tax already assumes one row per corporation and month;
            # the constraint makes that assumption enforceable and gives the
            # lookup an index at the same time
            models.UniqueConstraint(
                fields=["corp_id", "year", "month"],
                name="eos_tax_one_row_per_corp_and_month",
            ),
        ]
        indexes = [
            # the overview filters on a month, the statistics on a year
            models.Index(fields=["year", "month"], name="eos_tax_period_idx"),
        ]

    alliance_tax_rate = models.FloatField(
        verbose_name=_("Applied alliance tax rate"),
        default=0,
        help_text=_(
            "Alliance rate in effect when this row was calculated. Stored per row so "
            "changing the rate does not rewrite what past months were owed."
        ),
    )
