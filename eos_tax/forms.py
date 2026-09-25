from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from eos_tax.models import TaxConfiguration, TaxRate

try:
    # corptools keeps the PvE journal vocabulary in one place; reusing it keeps
    # the two apps from drifting apart. It is an internal constant, so fall back
    # to the historic default if it ever moves.
    from corptools.constants.wallet import PVE_GLANCE_STATS
except ImportError:  # pragma: no cover - depends on the corptools version
    PVE_GLANCE_STATS = {"ratting": {"ref_types": ["bounty_prizes"]}}


def journal_type_choices(selected=None):
    """Selectable wallet journal ref_types.

    Anything already configured stays selectable even when corptools no longer
    lists it, so an existing setup is never silently narrowed.
    """
    known = {
        ref_type
        for stat in PVE_GLANCE_STATS.values()
        for ref_type in stat.get("ref_types", [])
    }
    known.update(selected or [])

    return [(ref_type, ref_type.replace("_", " ")) for ref_type in sorted(known)]


class PercentField(forms.DecimalField):
    """Entered as a percentage, stored as a fraction.

    The calculation multiplies the gross income by this value and every
    MonthlyTax row already carries a fraction, so the database keeps 0.07 while
    the form shows and accepts 7.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 5)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", Decimal("0"))
        kwargs.setdefault("max_value", Decimal("100"))
        kwargs.setdefault(
            "widget", forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"})
        )
        super().__init__(**kwargs)

    def prepare_value(self, value):
        # a stored fraction becomes a percentage for display; a redisplayed form
        # already holds the raw string the user typed, so leave that alone
        if not isinstance(value, (Decimal, float, int)):
            return value

        percent = (Decimal(str(value)) * 100).quantize(Decimal("0.01"))

        # drop the decimals when there are none - "7" reads better than "7.00".
        # normalize() is not an option here, it would turn 100 into 1E+2.
        return percent.to_integral_value() if percent == percent.to_integral_value() else percent

    def clean(self, value):
        # validators run on the entered percentage, the conversion happens after
        cleaned = super().clean(value)

        if cleaned in self.empty_values:
            return cleaned

        return (cleaned / Decimal("100")).quantize(Decimal("0.0001"))


class TaxConfigurationForm(forms.ModelForm):
    tax_rate = PercentField(label=_("Base tax rate (%)"))
    tax_types = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=TaxConfiguration._meta.get_field("tax_types").verbose_name,
        help_text=TaxConfiguration._meta.get_field("tax_types").help_text,
    )

    class Meta:
        model = TaxConfiguration
        fields = [
            "tax_alliances",
            "tax_corporation",
            "corporation_blacklist",
            "tax_rate",
            "tax_types",
            "last_month",
            "current_month",
            "use_reason",
            "tax_change_min_points",
            "bot_hours_min_entries",
            "bot_min_hours_per_day",
            "bot_min_days_per_month",
            "bot_run_min_ticks",
            "bot_run_max_gaps",
            "bot_run_tick_tolerance",
            "bot_run_gap_minutes",
            "bot_rhythm_busy_hours",
            "bot_rhythm_min_payouts",
            "bot_rhythm_corp_min_payouts",
            "bot_rhythm_purge_strong",
            "bot_rhythm_min_difference",
            "bot_clock_max_apart",
            "bot_clock_min_payouts",
            "bot_clock_corp_min_payouts",
            "bot_clock_purge_strong",
            "bot_clock_min_apart",
            "bot_clock_min_concentration",
        ]
        # a native <select multiple> only takes a second entry - or gives one up -
        # on ctrl-click, which nobody discovers. Checkboxes say what they do.
        widgets = {
            "tax_alliances": forms.CheckboxSelectMultiple,
            "corporation_blacklist": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        configured = self.instance.tax_types if self.instance.pk else []
        self.fields["tax_types"].choices = journal_type_choices(configured)
        self.fields["corporation_blacklist"].queryset = self._excludable()
        self.fields["corporation_blacklist"].help_text = _(
            "Corporations of the taxed alliances. Excluding any other "
            "corporation would change nothing."
        )

        # said on the form rather than on the model, so explaining the schedule
        # does not cost a migration
        self.fields["tax_rate"].help_text = _(
            "Base rate, used for months before the first scheduled change below."
        )

    def clean(self):
        """A tick tolerance above the break ceiling would silence the ceiling.

        The run walk asks "is this gap still a tick?" before it asks "is this
        break short enough to forgive?", so a tolerance of two hours against a
        one hour ceiling never reaches the second question and every gap under
        two hours becomes invisible - including the ones the ceiling exists to
        end a run on.
        """
        cleaned = super().clean()

        tolerance = cleaned.get("bot_run_tick_tolerance")
        ceiling = cleaned.get("bot_run_gap_minutes")

        if tolerance and ceiling and tolerance > ceiling:
            self.add_error(
                "bot_run_tick_tolerance",
                _(
                    "Has to stay at or below the longest break a run can "
                    "survive, otherwise that ceiling never applies."
                ),
            )

        return cleaned

    def _chosen_alliances(self):
        """Alliance ids from the submitted form, or from what is stored.

        Reading the submission first keeps the choices from lagging a save
        behind when someone adds an alliance and excludes one of its
        Corporations in the same visit.
        """
        if self.is_bound:
            key = self.add_prefix("tax_alliances")

            # a request binds a QueryDict, which has getlist; a plain dict is
            # just as valid a way to bind a form and does not
            if hasattr(self.data, "getlist"):
                submitted = self.data.getlist(key)
            else:
                submitted = self.data.get(key) or []

                if isinstance(submitted, (str, int)):
                    submitted = [submitted]

            if submitted:
                return list(
                    EveAllianceInfo.objects.filter(pk__in=submitted).values_list(
                        "alliance_id", flat=True
                    )
                )

        if not self.instance.pk:
            return []

        return list(
            self.instance.tax_alliances.values_list("alliance_id", flat=True)
        )

    def _excludable(self):
        """Corporations worth offering for exclusion.

        Those of the taxed alliances - excluding anything else changes nothing -
        plus whatever is already excluded, so that narrowing the alliances never
        quietly un-excludes a Corporation nobody meant to let back in.
        """
        corporations = EveCorporationInfo.objects.filter(
            alliance__alliance_id__in=self._chosen_alliances()
        )

        if self.instance.pk:
            corporations = corporations | self.instance.corporation_blacklist.all()

        return corporations.distinct().order_by("corporation_name")


class MonthInput(forms.DateInput):
    """A month picker - the tax is calculated per month, so a day would only
    invite ambiguity."""

    input_type = "month"


class TaxRateForm(forms.ModelForm):
    valid_from = forms.DateField(
        label=TaxRate._meta.get_field("valid_from").verbose_name,
        widget=MonthInput(format="%Y-%m"),
        input_formats=["%Y-%m"],
    )
    rate = PercentField(label=_("Rate (%)"))

    class Meta:
        model = TaxRate
        fields = ["valid_from", "rate"]


TaxRateFormSet = forms.modelformset_factory(
    TaxRate,
    form=TaxRateForm,
    extra=1,
    can_delete=True,
)


class TaxConfigurationAdminForm(forms.ModelForm):
    """Keeps the admin fallback speaking percent as well - entering 7 there and
    getting 700 percent would be a nasty trap."""

    tax_rate = PercentField(label=_("Base tax rate (%)"))

    class Meta:
        model = TaxConfiguration
        fields = "__all__"


class TaxRateAdminForm(forms.ModelForm):
    rate = PercentField(label=_("Rate (%)"))

    class Meta:
        model = TaxRate
        fields = "__all__"
