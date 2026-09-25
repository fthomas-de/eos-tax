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
        help_text=_(
            "Match payments by their reason code instead of by amount alone. "
            "Without it a payment is recognised by its amount only, so two "
            "corporations owing the same sum, or one corporation owing the "
            "same sum twice, cannot be told apart."
        ),
    )
    tax_change_min_points = models.DecimalField(
        verbose_name=_("Smallest move worth listing"),
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
    bot_run_min_ticks = models.PositiveSmallIntegerField(
        verbose_name=_("Shortest run listed"),
        default=18,
        validators=[MinValueValidator(2), MaxValueValidator(200)],
        help_text=_(
            "How many payouts in a row a character has to collect without a "
            "break before the run is listed. The game pays a ratter about "
            "every twenty minutes, so eighteen is roughly six hours."
        ),
    )
    bot_run_max_gaps = models.PositiveSmallIntegerField(
        verbose_name=_("Interruptions allowed"),
        default=1,
        validators=[MaxValueValidator(20)],
        help_text=_(
            "How many breaks a run may contain and still count as one. A "
            "daily downtime would otherwise cut every long night in two. Only "
            "a break under an hour can be forgiven; a longer one always ends "
            "the run."
        ),
    )
    bot_run_tick_tolerance = models.PositiveSmallIntegerField(
        verbose_name=_("Longest gap that still counts as the same tick"),
        default=25,
        validators=[MinValueValidator(1), MaxValueValidator(240)],
        help_text=_(
            "In minutes. The game pays about every twenty minutes and the tick "
            "slips, so a little more than twenty leaves room for that without "
            "calling an unbroken stretch broken."
        ),
    )
    bot_run_gap_minutes = models.PositiveSmallIntegerField(
        verbose_name=_("Longest break a run can survive"),
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(720)],
        help_text=_(
            "In minutes. A break longer than this ends the run whatever the "
            "allowance above says. Without a ceiling one allowance would weld "
            "a morning and an evening into a single twelve hour run."
        ),
    )
    bot_rhythm_busy_hours = models.PositiveSmallIntegerField(
        verbose_name=_("Length of the busy window"),
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(23)],
        help_text=_(
            "How many hours of the day count as the corporation's busy window. "
            "A character spread evenly over the clock lands on this share of "
            "any window, which is the floor the score measures down to."
        ),
    )
    bot_rhythm_min_payouts = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest character worth reading"),
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text=_(
            "Below this many payouts in the month a character has too little "
            "of a day to describe, and is left out of this reading."
        ),
    )
    bot_rhythm_corp_min_payouts = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest usable yardstick"),
        default=40,
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
        help_text=_(
            "How many payouts have to be left in the corporation once the "
            "character's own are taken out. Below this there is no rhythm to "
            "compare against, only noise, and the character is not scored."
        ),
    )
    bot_rhythm_purge_strong = models.BooleanField(
        verbose_name=_("Leave flagged characters out of the yardstick"),
        default=True,
        help_text=_(
            "A character flat enough to be listed is also part of their "
            "corporation's day, and drags it flat with them - which makes "
            "everybody else look ordinary. With this on the reading runs "
            "twice: once to find them, once with them taken out. A "
            "corporation that would fall below the floor above keeps the "
            "plain figure."
        ),
    )
    bot_rhythm_min_difference = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest difference listed"),
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_(
            "In percentage points. How much flatter than the rest of their "
            "corporation a character has to be before the list mentions them. "
            "A negative difference means more concentrated than the "
            "corporation, which is the opposite of what this looks for, so "
            "those are never listed whatever this says."
        ),
    )
    bot_clock_max_apart = models.PositiveSmallIntegerField(
        verbose_name=_("Distance counted as a full deviation"),
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text=_(
            "In hours. Twelve is as far apart as two times of day can be, so "
            "the default treats the whole clock as the scale. A smaller value "
            "makes the colouring reach red sooner."
        ),
    )
    bot_clock_purge_strong = models.BooleanField(
        verbose_name=_("Leave flagged characters out of the yardstick"),
        default=True,
        help_text=_(
            "The same for this reading: a character far enough from their "
            "corporation to be listed also pulls the corporation's own middle "
            "of the day towards themselves, which shortens everybody else's "
            "distance."
        ),
    )
    bot_clock_min_apart = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest distance listed"),
        default=3,
        validators=[MinValueValidator(0), MaxValueValidator(12)],
        help_text=_(
            "In hours. How far from their corporation a character's day has "
            "to sit before the list mentions them. A third of the scale above "
            "is where the colouring stops calling a distance unremarkable, so "
            "a threshold under that lets green rows into the list."
        ),
    )
    bot_clock_min_payouts = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest character worth reading"),
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text=_(
            "Below this many payouts in the month the middle of a character's "
            "day is wherever the noise landed, so they are left out."
        ),
    )
    bot_clock_corp_min_payouts = models.PositiveSmallIntegerField(
        verbose_name=_("Smallest usable yardstick"),
        default=40,
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
        help_text=_(
            "How many payouts have to be left in the corporation once the "
            "character's own are taken out, before its middle of the day is "
            "worth comparing against."
        ),
    )
    bot_clock_min_concentration = models.PositiveSmallIntegerField(
        verbose_name=_("Least concentrated day with a middle"),
        default=12,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_(
            "In percent. How closely the payouts have to gather around one "
            "time of day before that day has a middle: 100 when all of them "
            "fall into one hour, 0 for a day spread perfectly evenly. A day "
            "spread evenly over twelve hours comes out at 64, over sixteen at "
            "42, over twenty at 19. Below this - for the character or the "
            "rest of their corporation - the middle would be wherever the "
            "rounding put it, so the character is left out of this reading."
        ),
    )
    bot_hours_min_entries = models.PositiveSmallIntegerField(
        verbose_name=_("Entries before an hour counts as active"),
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text=_(
            "A single entry is noise - a stray bounty tick, one ESS payout. "
            "The game pays about every twenty minutes, so an hour of "
            "uninterrupted play holds three; two is deliberately tolerant, "
            "because play gets interrupted and a false negative costs less "
            "than accusing a player."
        ),
    )
    bot_min_hours_per_day = models.PositiveSmallIntegerField(
        verbose_name=_("Hours in a day before it counts"),
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text=_(
            "A day counts as suspicious when a character earned taxed income in "
            "more than this many different hours of that day."
        ),
    )
    bot_min_days_per_month = models.PositiveSmallIntegerField(
        verbose_name=_("Days in a month before a character is listed"),
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text=_(
            "A character is listed once it reaches this many suspicious days "
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
    payed = models.BooleanField(verbose_name=_("Paid"), default=False)
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

    amount_to_pay = models.BigIntegerField(
        verbose_name=_("Amount to pay"),
        default=0,
        help_text=_(
            "ISK owed to the alliance for this month, in whole ISK. Worked out from "
            "tax_value, tax_percentage and alliance_tax_rate whenever the row is "
            "written, and kept with them from then on - the page, the chart and the "
            "payment check read it rather than redoing the arithmetic."
        ),
    )
