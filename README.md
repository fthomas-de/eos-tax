# eos-tax

Alliance PvE tax tracking for [Alliance Auth](https://gitlab.com/allianceauth/allianceauth).

The app reads the corporation wallet journals that
[corptools](https://github.com/pvyParts/allianceauth-corp-tools) collects, works
out what every Corporation of a taxed Alliance owes for a month, and shows
whether it has paid.

## Requirements

| | |
|---|---|
| Alliance Auth | 5.2 or newer |
| allianceauth-corptools | 3.5 or newer, supplies the wallet journal |
| Python | 3.10 or newer |

corptools has to be installed **and pulling corporation wallets** - without
journal data this app has nothing to work with.

## Installation

```bash
pip install git+https://github.com/fthomas-de/eos-tax
```

Add `'eos_tax',` to `INSTALLED_APPS` in `myauth/settings/local.py`, then:

```bash
python ~/myauth/manage.py migrate
python ~/myauth/manage.py collectstatic --noinput
```

and restart your allianceserver.

### Recommended setting

The app keeps its configuration in a single database row. Without a cache every
read of it is a query:

```python
SOLO_CACHE = "default"
```

### Scheduling the update

Nothing is calculated until `eos_tax.tasks.run_update_alliance` runs. Add it
either in `local.py`:

```python
CELERYBEAT_SCHEDULE["eos_tax: update taxes"] = {
    "task": "eos_tax.tasks.run_update_alliance",
    "schedule": crontab(minute="0", hour="*/6"),
}
```

or as a periodic task in the Django admin under **Periodic Tasks**.

**Pick the interval deliberately.** The task fans out one subtask per
Corporation and per configured month. With a large Alliance and both months
switched on that is hundreds of subtasks per run - every few hours is plenty.

## Configuration

Configuration lives on the app's **Settings** page, not in `local.py`. On first
migration the historic `TAX_*` values are read out of `local.py` once and
carried into the database; from then on those lines have no effect and can be
removed.

| Setting | Meaning |
|---|---|
| Taxed alliances | Corporations of these Alliances are taxed |
| Holding Corporation | the single Corporation that receives the payments |
| Excluded corporations | never taxed, never listed |
| Base tax rate | share of the gross PvE income, in percent |
| Taxed journal types | wallet journal `ref_type`s counted as PvE income |
| Previous / running month | which months the task calculates |
| Match by Reason | match payments by their Reason code, not by amount alone |
| Bot detection thresholds | hours per day and days per month |

The Holding Corporation has to be known to Alliance Auth. A holding without
members never shows up on its own - import it once:

```bash
python manage.py shell -c "from allianceauth.eveonline.models import EveCorporationInfo; print(EveCorporationInfo.objects.create_corporation(YOUR_CORP_ID))"
```

The same applies to an Alliance that has not been seen yet; it can be added
under `/admin/eveonline/eveallianceinfo/`.

### Tax rate schedule

Below the base rate the Settings page holds a schedule of rate changes. Each
entry says *from this month on, the rate is X*, open ended:

| Valid from | Rate |
|---|---|
| 2026-09 | 7 % |
| 2026-10 | 10 % |

The newest entry that is not in the future wins, so a change can be entered
months ahead. Months before the first entry use the base rate. **Months that
were already calculated keep the rate they were charged with** - the applied
rate is stored per row, so a new entry never rewrites the past.

## Pages

**Overview** - what each Corporation owes for the configured months and whether
it has paid. Sortable columns, the Corporation column is searchable. Members see
their own Corporations, `admin_view` sees all.

**Statistics** - tax per Corporation over a year, either as a trend line or as
the share of a single month. The legend doubles as a table and its checkboxes
switch Corporations on and off. Beyond eight Corporations the line style carries
part of the identity, because colour alone stops being distinguishable.

**Bots** - characters whose taxed income looks automated: more than *X*
different hours of a day, on more than *Y* days of the month. Both thresholds
are configurable. When nothing crosses them, the ten longest days of the month
are listed instead, so the thresholds can be judged against real numbers. Each
character is listed with its main.

**Settings** - the configuration described above.

## Permissions

| Permission | Grants |
|---|---|
| `eos_tax.basic_access` | the Overview, limited to the user's own Corporations |
| `eos_tax.admin_view` | all Corporations, plus Statistics, Bots and Settings |

## Translations

Shipped in German, English, Spanish, French, Italian, Korean and Russian. EVE
terms stay in English throughout - Corporation, Alliance, Character, ISK, PvE,
Reason.

The compiled `.mo` files are part of the repository. If your deployment strips
them, run `python manage.py compilemessages` after installing, or every string
falls back to English.