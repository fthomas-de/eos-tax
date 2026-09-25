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
| Bot detection thresholds | one set per reading of the Bots page - hours and days, unbroken runs, the two Corporation comparisons - each with its own chapter on the settings page |

**Match by Reason is worth switching on.** Without it a payment is recognised
by its amount and nothing else - not by who sent it, and not by which month it
was for. Two Corporations that owe the same sum in a month, or one Corporation
that owes the same sum in two months, cannot be told apart, and a single
transfer can settle both. The Reason code shown on the Overview carries
`corporation/month/year`, which is what makes a payment identifiable.

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
different hours of a day, on at least *Y* days of the month. Both thresholds
are configurable. When nothing crosses them, the ten longest days of the month
are listed instead, so the thresholds can be judged against real numbers. Each
character is listed with its main.

**Corp Tax Changes** - Corporations whose *ingame* tax rate moved during the
year, with the daily curve behind each of them. The corporation wallet only
holds the Corporation's own cut, so the rate is not in it; it is recovered from
the kills listed in each bounty's `reason` against what the static data export
says those NPCs pay. A step in that share is the finding - the level on its own
also carries the system's bounty modifier. The number of systems behind a step
is what tells a rate change from a modifier drift: a Corporation switching its
rate moves every system on the same day. Requires the `eve_sde` app; without it
the page says so. Quick filters for the two extremes, 0 % and 100 %.

**Bots** has three more readings beside the thresholds, as tabs. Each is
computed only when its tab is opened, because most visits never leave the
first one.

*Unbroken runs* - the game pays a ratter about every twenty minutes, so an
uninterrupted stretch shows up as a chain of payouts and nothing else does.
This is the only reading that says nothing about *when* somebody plays, which
makes it the fair one across an alliance spanning several timezones. Two
settings: how long a run has to be to be listed, and how many interruptions it
may contain - a daily downtime would otherwise cut every long night in two.
Only a break under an hour can be forgiven; a longer one always ends the run.
When nothing clears the threshold the longest runs are listed anyway, so the
threshold can be judged against real numbers.

*Against the Corporation* - how much of a Character's income falls inside the
hours their own Corporation is busy. The Corporation is the yardstick and not
the alliance: the alliance holds Chinese, American, European and Russian
groups at once, so its day is flat and a round the clock script would look
ordinary against it. A Corporation usually sits in one timezone - one in the
journal puts 78 percent of its payouts into eight hours of the day.

*Off the Corporation clock* - how far a Character's day sits from their
Corporation's. Averaged the way a clock wraps, not read off the busiest hour:
out of a dozen payouts the busiest hour is wherever the noise landed, and it
moves on a single tick. Somebody genuinely living elsewhere looks exactly like
an account played by somebody else, so this is a hint and never an accusation.

Clicking a Character opens the same four readings for that one Character,
again a tab at a time. The hours-per-day matrix is unchanged; the other three
are drawn:

- *Unbroken runs* as a point per payout, day across and time of day down. Some-
  body who plays evenings draws a band, an uninterrupted stretch draws a
  vertical line, and the longest run is picked out in colour.
- *Against the Corporation* as the Character's hours against the rest of the
  Corporation's, in shares rather than counts - one Character never has the
  volume of a Corporation, and in counts their own day would be a flat line
  along the bottom. The Corporation's busiest eight hours are shaded.
- *Off the Corporation clock* round a clock face rather than along an axis,
  because the hours either side of midnight are neighbours and a straight
  axis puts them at opposite ends.

The last two are rankings rather than verdicts, and carry no threshold. There
is no number that separates a night shift from a script, so the list is
ordered and each row carries the Corporation's own figure beside it.

**Settings** - the configuration described above.

## Permissions

| Permission | Grants |
|---|---|
| `eos_tax.basic_access` | the Overview, limited to the user's own Corporations |
| `eos_tax.admin_view` | all Corporations, plus Statistics, Bots and Settings |

## Translations

Shipped in German, English, Spanish, French, Italian, Korean and Russian. EVE
terms stay in English throughout - Corporation, Alliance, wallet, bounty, ISK,
PvE, Reason, Character, and the ingame names of the journal types - lower
case in running text, capitalised in headings and column titles.

The rule is enforced by a test that reads every entry of every catalogue rather
than a few labels, because this is exactly the kind of thing that survives a
review: a translator writing a whole sentence reaches for the word their
language has, and `bounty` had quietly become Kopfgelder, recompensas, primes,
taglie, 현상금 and наград.

The compiled `.mo` files are part of the repository. If your deployment strips
them, run `python manage.py compilemessages` after installing, or every string
falls back to English.

## Development

The suite runs against a real Alliance Auth installation, so it needs one - it
is not a standalone package test:

```bash
python manage.py test eos_tax --keepdb
```

`--keepdb` matters: rebuilding the Alliance Auth schema costs minutes, running
the suite costs under a minute.

```bash
python manage.py test eos_tax --keepdb --parallel 4
```

roughly halves that; Django clones the test database per worker. More workers
are not better - on twelve cores, eight workers were slower than four, because
the database becomes the bottleneck rather than the CPU.

Two sessions testing at once will fight over the same clones. If you run
parallel Claude Code agents or two terminals, give each its own test database
by making the name configurable in your `local.py`:

```python
"TEST": {
    "CHARSET": "utf8mb4",
    "NAME": os.environ.get("EOS_TEST_DB", "test_aa_dev"),
},
```

Fixtures live in `eos_tax/tests/factories.py`. Add new ones there rather than
importing them from another test module.

### After adding a static file

The app's own JavaScript lives in `eos_tax/static/eos_tax/js/` and is loaded
with `{% sri_static %}`, the way Alliance Auth loads its own. That goes
through a manifest storage, so a template naming a file the manifest does not
know raises

```
ValueError: Missing staticfiles manifest entry for 'eos_tax/js/...'
```

which renders as a 500 and says nothing about the actual cause. Run

```bash
python manage.py collectstatic --noinput
```

after adding or renaming a script, before running the tests.