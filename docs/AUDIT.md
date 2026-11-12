# Audit: programming errors and security

| | |
|---|---|
| Date | 2026-11-11 |
| Commit | `373ab7c1fb3304eb42cf7eee67f126be0207c742` (Release 0.4.20), clean working tree |
| Scope | All non-test code of `eos_tax`: `views.py`, `urls.py`, `models.py`, `forms.py`, `tasks.py`, `progress.py`, `util.py`, `app_settings.py`, `admin.py`, `auth_hooks.py`, `db/*.py`, every template, every script in `static/eos_tax/js/`, migrations 0001-0034, `pyproject.toml`. Tests were read only to name the gaps. There are no signals, managers or management commands in this app. |
| Method | Read only. Every finding was followed from its entry point (URL or task) to its effect. Nothing was run: no tests, no database, no `makemigrations --check`. Alliance Auth, corptools and `eve_sde` were not read (other repositories were off limits), so statements about them rest on how this app calls them. |

**Implemented on 2026-11-12** in the working tree, uncommitted: TAX-01 to
TAX-09 and FU-01, each with its tests seen failing first. Deviations from the
plan below: TAX-05 has one test per endpoint with a sub-test per year instead
of two tests; TAX-07 got a second test (`test_should_keep_a_filled_table`).
The suite without the translation tag ran green (800 tests, kept test
database); `--fresh` and the catalogues are left to the commit. Migration 0035
was applied to `aa_dev` on 2026-11-12.

Status: **CONFIRMED** = the whole path was read and the trigger can be named.
**PLAUSIBLE** = depends on something that could not be checked here, named in the finding.

## Findings

| ID | Severity | Type | File | Summary | Status |
|---|---|---|---|---|---|
| TAX-01 | High | Logic / fraud | `eos_tax/util.py` | One transfer naming several reason codes settles several rows in full | CONFIRMED |
| TAX-02 | Medium | Period boundary | `eos_tax/tasks.py` | A payment seen after its month left the task's window is never recognised | CONFIRMED |
| TAX-03 | Low | Race condition | `eos_tax/db/payments.py` | Two parallel calculations of one row can take "paid" back | CONFIRMED |
| TAX-04 | Low | Logic | `eos_tax/util.py`, `eos_tax/db/payments.py` | The first calculation of a month never finds its payment | CONFIRMED |
| TAX-05 | Low | DoS / GET that writes | `eos_tax/views.py` | Any of ~120,000 months in the URL queues a bots job and stores four rows | CONFIRMED |
| TAX-06 | Low | Input validation | `eos_tax/views.py` | Recalculate accepts any corporation id, also outside the taxed alliances | CONFIRMED |
| TAX-07 | Low | Stale cache | `eos_tax/db/tax_changes.py` | NPC bounties cached for the life of the process, an empty answer included | CONFIRMED |
| TAX-08 | Low | Validation | `eos_tax/models.py` | Admin: a mid-month `valid_from` for an existing month ends in a 500 | CONFIRMED |
| TAX-09 | Low | i18n | `eos_tax/db/bot_store.py` | Ages on the bots lists are stored in the worker's language | PLAUSIBLE |

No Critical finding. No XSS, SQL injection, open redirect, missing permission check or
CSRF gap was found - see "Checked and fine".

The verify commands run from `~/aa-dev/working/myauth`, one module per call
(`eos-test` takes one label). Every new test has to be seen failing against the
unfixed code first, as `CLAUDE.md` demands.

---

## TAX-01 - One transfer naming several reason codes settles several rows (High)

**Where**: `eos_tax/util.py:213-217`, `find_payment`, branch `if config.use_reason:`.

**What happens**: A Corporation owes 1,000,000,000 ISK for September and
1,000,000,000 ISK for October. Its director makes **one** transfer of
1,000,000,000 ISK to the holding Corporation with the reason
`98000001/9/2026 98000001/10/2026` (33 characters, the game allows 40). The
September row finds the transfer because its code is contained in the reason;
the October row finds the same transfer for the same reason. Both rows are
marked paid, both show the amount in green ("paid to the ISK"), and the
alliance received half of what it was owed. The same works across two
Corporations (`98000001/9/2026 98000002/9/2026`). Paid is never taken back, so
the rows stay paid even after the fault is fixed.

Second, smaller effect of the same line: the code is matched as a substring, so
`198000001/9/2026` (a Corporation whose id ends in another one's) or
`98000001/9/20261` also count for `98000001/9/2026`.

**Cause**:

```python
        payments = _one_side(list(
            journal.filter(reason__icontains=f"{corp_id}/{month}/{year}")
            .values("date", "amount")
        ))
```

Each row asks on its own whether its code occurs in a reason. Nothing checks
that the reason names this code only.

**Fix**:

1. `eos_tax/util.py`, add to the imports at the top:

   ```python
   import re
   ```

2. `eos_tax/util.py`, below `DONATION_TYPES = [...]`:

   ```python
   # a reason code as the overview hands it out: corporation id/month/year
   REASON_CODE = re.compile(r"\d+/\d+/\d+")
   ```

3. `eos_tax/util.py`, replace the block shown under Cause with:

   ```python
        code = f"{corp_id}/{month}/{year}"
        # the database narrows, this decides: a transfer naming two codes
        # counted in full for both rows, and a code that is only the tail
        # of a longer one matched as well. Words around the code are fine
        payments = _one_side([
            row for row in
            journal.filter(reason__icontains=code).values("date", "amount", "reason")
            if set(REASON_CODE.findall(row["reason"])) == {code}
        ])
   ```

   `_one_side` only reads `date` and `amount`, the extra key does no harm.

4. `CHANGELOG.md`, `[Unreleased]`: one entry (what was wrong, why this is the fix).
5. `README.md`: where the reason code is explained, add that a transfer must
   carry exactly one code. No translation strings change in this minimal fix
   (see Open question Q3 for a hint on the page).

No migration.

**Test**: `eos_tax/tests/test_payments.py`, class `TestCorpHasPayedReasonMatching`
(its `setUp` already owes `OWED`, configures the holding and switches
`use_reason` on):

- `test_should_not_count_a_transfer_naming_two_codes`:
  `self.pay(OWED, reason=f"{CORP_ID}/{MONTH}/{YEAR} {OTHER_CORP_ID}/{MONTH}/{YEAR}")`,
  then `self.assertFalse(self.has_payed())`. Red before the fix (True).
- `test_should_not_take_the_tail_of_a_longer_code`:
  `self.pay(OWED, reason=f"1{CORP_ID}/{MONTH}/{YEAR}")`, `assertFalse`. Red before.
- `test_should_accept_words_around_the_code`:
  `self.pay(OWED, reason=f"tax {CORP_ID}/{MONTH}/{YEAR} thanks")`, `assertTrue`.
  Green before and after - it guards against a fix that is too strict.

**Verify**: `eos-test eos_tax.tests.test_payments`

**Risk / depends on**: A transfer that honestly names two codes (two months paid
at once) no longer counts for either row; the payer has to transfer once per
code. A reason that contains another `number/number/number` (a date such as
`3/11/2026`) beside the code is refused too. Rows already settled by such a
transfer stay paid - find them by hand in the holding's journal if that matters
(reasons with two codes). Do this before TAX-04, which edits the same function.

---

## TAX-02 - A payment seen after its month left the window is never recognised (Medium)

**Where**: `eos_tax/tasks.py:115-127`, `run_update_alliance`; the window comes
from `eos_tax/util.py:19-32`, `get_dates`.

**What happens**: The task recalculates only the previous and the running month.
September's row is looked at for the last time by the last run of October. The
README schedules the task every six hours, and corptools imports the wallet
journal with its own delay. A Corporation that transfers its September tax on
31 October at 21:00 EVE is imported after the 18:00 run; the next run at 00:00
on 1 November calculates October and November only. September stays unpaid for
good, although the money is in the holding's wallet - the only way out is a
manual recalculation of that Corporation and month on the settings page, which
nobody is told to do. The same happens to every payment made later than that.

**Cause**:

```python
    queue_corporations(corporations, get_dates(), progress.AUTOMATIC)
```

Nothing but `get_dates()` decides which rows are checked for a payment.

**Fix** (three months back - decided by the user on 2026-11-12, see Q1):

1. `eos_tax/tasks.py`, add to the imports:

   ```python
   from datetime import datetime

   from dateutil.relativedelta import relativedelta
   from django.db.models import Q

   from eos_tax.models import MonthlyTax
   ```

2. `eos_tax/tasks.py`, above `queue_corporations`:

   ```python
   # How many months back an unpaid row is still recalculated. A transfer made
   # on the last evening before its month drops out of get_dates() reaches the
   # journal after the last run that looked at it.
   OVERDUE_MONTHS = 3


   def overdue_jobs(dates):
       """Unpaid rows of the months before the calculated ones, as
       (corp_id, corp_name, month, year)."""
       earliest = datetime.now() - relativedelta(months=OVERDUE_MONTHS)
       rows = MonthlyTax.objects.filter(payed=False).filter(
           Q(year__gt=earliest.year)
           | Q(year=earliest.year, month__gte=earliest.month)
       ).exclude(corp_id__in=get_config().blacklisted_corporation_ids())

       return [
           (row.corp_id, row.corp_name, row.month, row.year)
           for row in rows
           if (row.month, row.year) not in dates
       ]
   ```

3. `eos_tax/tasks.py`, `queue_corporations`: change the signature and add the
   extra jobs after the list comprehension.

   Before:

   ```python
   def queue_corporations(corporations, dates, kind):
   ```

   ```python
       jobs = [
           {"corp_id": corp_id, "corp_name": corp_name, "month": month, "year": year}
           for corp_id, corp_name in corporations
           for month, year in dates
       ]
       if not jobs:
           return None
   ```

   After:

   ```python
   def queue_corporations(corporations, dates, kind, extra=()):
   ```

   ```python
       jobs = [
           {"corp_id": corp_id, "corp_name": corp_name, "month": month, "year": year}
           for corp_id, corp_name in corporations
           for month, year in dates
       ]
       # single rows beyond that grid - see overdue_jobs
       jobs += [
           {"corp_id": corp_id, "corp_name": corp_name, "month": month, "year": year}
           for corp_id, corp_name, month, year in extra
       ]
       if not jobs:
           return None
   ```

   Add to the docstring: `extra: (corp_id, corp_name, month, year) jobs beyond that grid.`

4. `eos_tax/tasks.py`, `run_update_alliance`. Before:

   ```python
       queue_corporations(corporations, get_dates(), progress.AUTOMATIC)
       # the same months, so the bots page keeps pace with the tax rows
       queue_bot_reports(get_dates())
   ```

   After:

   ```python
       dates = get_dates()
       queue_corporations(
           corporations, dates, progress.AUTOMATIC, overdue_jobs(dates)
       )
       # the same months, so the bots page keeps pace with the tax rows
       queue_bot_reports(dates)
   ```

5. `CHANGELOG.md`, `[Unreleased]`. No migration, no strings. The Celery task
   signatures do not change, so no worker contract breaks - restart the
   workers anyway so they load the new `run_update_alliance`.

**Test**: `eos_tax/tests/test_progress.py`, class `TestTasks` (add the imports
`datetime`, `relativedelta`, `create_tax_row`):

- `test_should_recalculate_an_unpaid_row_of_an_earlier_month`: build
  `old = datetime.now() - relativedelta(months=2)`, `create_tax_row(BRAVO_CORP_ID,
  "Bravo Corp", month=old.month, year=old.year)`, patch `eos_tax.tasks.get_dates`
  to return `[(now.month, now.year)]` and `run_update_corporation.delay`, call
  `run_update_alliance()`, then
  `delay.assert_any_call(corp_id=BRAVO_CORP_ID, month=old.month, year=old.year, run_id=run["id"])`.
  Red before the fix.
- `test_should_leave_a_paid_row_of_an_earlier_month_alone`: the same with
  `payed=True`; assert no call carries `month=old.month`.
- `test_should_leave_a_row_beyond_the_window_alone`: unpaid, five months back;
  assert no call for it.

**Verify**: `eos-test eos_tax.tests.test_progress`

**Risk / depends on**: The whole row is recalculated, not only its payment
(`update_corp` is the one code path), so an old month's amount can still move
when a journal entry or a corporation history arrives late - exactly as it does
today during the following month. The overview still shows only the months of
`get_dates()`; whether older unpaid rows should be visible is Open question Q2.
Independent of the other findings.

---

## TAX-03 - Two parallel calculations of one row can take "paid" back (Low)

**Where**: `eos_tax/db/payments.py:33-92`, `set_corp_tax`.

**What happens**: The periodic task and the settings page's recalculate button
(or two task runs that overlap) calculate the same Corporation and month at
once. Both load the row with `payed=False`. One found the payment and saves
`payed=True`; the other, whose payment check ran a moment earlier and found
nothing, saves its whole stale copy over it - `payed=False`, `amount_paid`
empty. The rule "a row once marked paid is never unmarked" is broken. The
window is the few milliseconds between the read and the `save()`, and the next
run repairs it as long as the payment still matches - not after a rate
correction, the case the rule exists for.

**Cause**:

```python
    selected_corp = (
        MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
        or MonthlyTax(corp_id=corp_id, month=month, year=year)
    )
    ...
    selected_corp.payed=selected_corp.payed or payed
    ...
    selected_corp.save()
```

Read, decide, write - without a lock and with a `save()` of every column.

**Fix**:

1. `eos_tax/db/payments.py`, change the import line
   `from django.db.models import Q` and add one above it:

   ```python
   from django.db import transaction
   from django.db.models import Q
   ```

2. Put the decorator on the function:

   ```python
   @transaction.atomic
   def set_corp_tax(corp_id: int, ...):
   ```

3. Lock the row while it is read. Before:

   ```python
        MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
   ```

   After:

   ```python
        # locked until the save below: a parallel run that read the row
        # before this one wrote it would save its stale "unpaid" over it
        MonthlyTax.objects.select_for_update()
        .filter(corp_id=corp_id, month=month, year=year).first()
   ```

4. `CHANGELOG.md`, `[Unreleased]`. No migration.

**Test**: `eos_tax/tests/test_payments.py`, class `TestPaidIsNeverTakenBack`:
`test_should_lock_the_row_while_it_decides`. Create a row with `create_tax_row`,
call `set_corp_tax(...)` inside
`with CaptureQueriesContext(connection) as queries:` (imports
`from django.db import connection`, `from django.test.utils import CaptureQueriesContext`)
and assert `any("FOR UPDATE" in query["sql"] for query in queries)`. Red before
the fix. A real two-thread race is not worth its flakiness here.

**Verify**: `eos-test eos_tax.tests.test_payments`

**Risk / depends on**: Two workers creating the same new row at once already
fail today (unique constraint, `IntegrityError`); with the lock one of them can
fail with a MySQL deadlock error instead. Either way the job shows as failed on
the bar and the next run writes the row. Independent of the other findings.

---

## TAX-04 - The first calculation of a month never finds its payment (Low)

**Where**: `eos_tax/util.py:188-190`, `find_payment`; called from
`eos_tax/db/payments.py:663-669`, `update_corp`, before the row is written.

**What happens**: An admin recalculates a month that has no row yet - an older
month after the app was installed, or a Corporation that joined late - and the
Corporation has already paid. `update_corp` asks `find_payment` first; that
finds no row, returns "nothing" without looking at the journal, and the log
says "No payment with this reason found". The row is written unpaid. For the
previous and the running month the next task run corrects it; for any other
month nothing does until somebody presses Recalculate a second time.

**Cause**:

```python
    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data:
        return nothing
```

The amount to compare against is read off the stored row, and on the first run
there is none.

**Fix**:

1. `eos_tax/util.py`, signature of `find_payment`. Before:

   ```python
   def find_payment(corp_id:int, month:int, year:int, config=None, corp_name:str = None) -> dict:
   ```

   After:

   ```python
   def find_payment(corp_id:int, month:int, year:int, config=None, corp_name:str = None, amount_to_pay:int = None) -> dict:
   ```

   Add to the docstring: `amount_to_pay is only used while the month has no row
   yet: the figure the caller is about to store for it.`

2. `eos_tax/util.py`, replace from `tax_data = ...` down to and including the
   line `amount_to_pay = tax_data.amount_to_pay`. Before:

   ```python
    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data:
        return nothing

    config = config or get_config()
    holding_corp_id = config.holding_corporation_id()

    if not holding_corp_id:
        # nothing configured that a payment could have gone to
        return {**nothing, "payed": tax_data.payed}

    # the figure the overview shows, read off the same row - worked out here
    # a second time it could disagree with the page by a rounding step, and
    # a payment of exactly what the page said would then not match
    amount_to_pay = tax_data.amount_to_pay
   ```

   After:

   ```python
    tax_data = MonthlyTax.objects.filter(corp_id=corp_id, month=month, year=year).first()
    if not tax_data and amount_to_pay is None:
        return nothing

    already_paid = bool(tax_data and tax_data.payed)
    config = config or get_config()
    holding_corp_id = config.holding_corporation_id()

    if not holding_corp_id:
        # nothing configured that a payment could have gone to
        return {**nothing, "payed": already_paid}

    # the figure the overview shows, read off the same row - worked out here
    # a second time it could disagree with the page by a rounding step, and
    # a payment of exactly what the page said would then not match. A month
    # without a row has no figure on the page yet and takes the caller's
    if tax_data:
        amount_to_pay = tax_data.amount_to_pay
   ```

3. `eos_tax/util.py`, further down. Before:

   ```python
    payed = tax_data.payed or match is not None
   ```

   After:

   ```python
    payed = already_paid or match is not None
   ```

4. `eos_tax/db/payments.py`, `update_corp`. Before:

   ```python
    overall_ratted = int(tax_sum)
    payment = find_payment(
        corp_id=corp_id,
        month=month,
        year=year,
        config=config,
        corp_name=corp_info.corporation_name,
    )
    payed = payment["payed"]
    logger.info(f"dbcon update_corp3: {corp_info.corporation_name} ({corp_id}): payed {payed} - {month}/{year}")

    gross_income = income["gross_income"]
   ```

   After:

   ```python
    overall_ratted = int(tax_sum)
    gross_income = income["gross_income"]
    payment = find_payment(
        corp_id=corp_id,
        month=month,
        year=year,
        config=config,
        corp_name=corp_info.corporation_name,
        # only for a month without a row yet; the same figure set_corp_tax
        # stores below - keep the two formulas equal
        amount_to_pay=round(gross_income * alliance_tax_rate),
    )
    payed = payment["payed"]
    logger.info(f"dbcon update_corp3: {corp_info.corporation_name} ({corp_id}): payed {payed} - {month}/{year}")
   ```

5. `CHANGELOG.md`, `[Unreleased]`. No migration, no strings.

**Test**: `eos_tax/tests/test_payments.py`, new class
`TestUpdateCorpFindsThePaymentOnTheFirstRun(PaymentsTestCase)`, one test
`test_should_mark_a_month_paid_on_its_first_calculation`: set
`self.config.tax_rate = Decimal("0.15")`, `use_reason = True`,
`tax_corporation = create_corporation(HOLDING_CORP_ID, "Holding Corp", None)`,
save; `self.bounty(500_000_000, day=10)`; create one
`CorporationWalletJournalEntry` like `TestUpdateCorpRecordsThePayment.pay`
does (`ref_type="player_donation"`, `second_party_id=HOLDING_CORP_ID`,
`reason=REASON`, `amount=-10**12`, dated `YEAR`/`MONTH`/12); call
`update_corp(CORP_ID, MONTH, YEAR)` **once**; assert `self.row().payed` and
`self.row().amount_paid == 10**12`. Red before the fix.
`TestCorpHasPayedWithoutARow.test_should_report_unpayed_without_a_row` must
stay green (no row and no amount handed in is still "nothing").

**Verify**: `eos-test eos_tax.tests.test_payments`

**Risk / depends on**: After TAX-01 (same function). `find_payment` has one
caller outside the tests (`update_corp`); the tests call it with three
arguments, which keeps working.

---

## TAX-05 - Any month in the URL queues a bots job and stores four rows (Low)

**Where**: `eos_tax/views.py:592-606`, `_selected_month`; reached through
`bots` (`views.py:651`), `bot_signal` (`views.py:892`) -> `_stored_reports`
(`views.py:873-887`) -> `queue_bot_reports`; and `bots_recalculate`
(`views.py:712-727`).

**What happens**: A user holding `admin_view` or `gm_bots_access` opens
`/eos_tax/bots/?month=1500-03`, or `?month=2090-01`. The month has no stored
lists, so the **GET** queues a Celery job, registers a run on every admin's
progress bar and stores four `BotReport` rows for a month nobody can have
earned in. Every month from year 1 to 9998 is accepted - about 120,000 jobs and
480,000 rows for a loop over the URL. A link somebody is made to click queues
one job per click.

**Cause**:

```python
    if not MIN_YEAR <= selected.year <= MAX_YEAR:
        return datetime.now()

    return selected
```

The range only protects `datetime` from overflowing, not the job queue.

**Fix**:

1. `eos_tax/views.py`, below `MAX_YEAR = 9998`:

   ```python
   # EVE went live in May 2003 - no wallet journal is older
   FIRST_YEAR = 2003
   ```

2. `_selected_month`. Before:

   ```python
    if not MIN_YEAR <= selected.year <= MAX_YEAR:
        return datetime.now()
   ```

   After:

   ```python
    # a month nobody can have earned in would still queue the bots job and
    # store four empty lists - one job per hand written url
    if selected.year < FIRST_YEAR or selected > datetime.now():
        return datetime.now()
   ```

   Change the docstring's second paragraph to say that the range is the months
   a journal can exist for, which also keeps `strptime`'s 9999-12 out.

3. `bots_recalculate`. Before:

   ```python
    if not MIN_YEAR <= selected.year <= MAX_YEAR:
        return HttpResponseBadRequest(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
   ```

   After:

   ```python
    if selected.year < FIRST_YEAR or selected > datetime.now():
        return HttpResponseBadRequest("no journal can exist for that month")
   ```

   `MIN_YEAR` and `MAX_YEAR` stay - `_selected_year` and `settings_recalculate`
   still use them.

4. `CHANGELOG.md`, `[Unreleased]`. No migration, no strings.

**Test**: `eos_tax/tests/test_views.py`, class `TestYearsOutOfRange` (add
`BotReport` to the import from `eos_tax.models`):

- `test_should_not_compute_a_month_in_the_future`:
  `year = datetime.date.today().year + 1`;
  `self.client.get(reverse("eos_tax:bots"), {"month": f"{year}-01"})`; assert
  status 200, the page contains today's `%Y-%m`, and
  `BotReport.objects.filter(year=year).exists()` is False. Red before the fix
  (the test base runs the job in place, so the rows exist).
- `test_should_not_compute_a_month_before_the_game`: the same with `1999-01`
  and `BotReport.objects.filter(year=1999)`.

**Verify**: `eos-test eos_tax.tests.test_views`, then
`eos-test eos_tax.tests.test_progress` (its
`test_should_refuse_a_month_it_cannot_read` posts `9999-12` and must stay 400).

**Risk / depends on**: A test that asks for a month later than the day it runs
on would now fall back to the running month. None was found (the fixtures use
2026-06 and 2026-09), but grep the tests for `"month":` before committing.
Independent of the other findings.

---

## TAX-06 - Recalculate accepts any corporation id (Low)

**Where**: `eos_tax/views.py:526-541`, `settings_recalculate`, single
Corporation branch.

**What happens**: A user with `manage_settings` posts `corp_id=<id>` by hand
for a Corporation Alliance Auth knows but that is in no taxed alliance. The
select on the page only offers the taxed alliances' Corporations; the endpoint
does not check. If corptools holds that Corporation's journal, `update_corp`
writes a `MonthlyTax` row for it. `get_website_data` and
`get_open_payment_count` filter by month and blacklist only, so the row appears
on the admins' overview with a reason code and counts in the menu badge while
its month is shown - and the app offers no way to delete a row.

**Cause**:

```python
    try:
        corp_id = int(corp_id)
    except ValueError:
        return HttpResponseBadRequest("corp_id must be an integer or 'all'")

    # a run of one, so the bar on another admin's page shows it as well
```

**Fix**:

1. `eos_tax/views.py`, between the `except` block and the comment
   `# a run of one, ...` shown above, insert:

   ```python
    # only what the selection offers: a hand written id wrote a row for a
    # Corporation the alliance does not tax, which the overview and the
    # menu badge then counted as owed
    if not EveCorporationInfo.objects.filter(
        corporation_id=corp_id,
        alliance__alliance_id__in=config.alliance_ids(),
    ).exists():
        return HttpResponseBadRequest(
            "corp_id is not a corporation of the taxed alliances"
        )
   ```

2. The lookup of `corp_name` right below keeps its `or str(corp_id)` fallback
   untouched.
3. `CHANGELOG.md`, `[Unreleased]`. No migration, no strings (the script shows
   its own "Could not recalculate this month." for any failure).

**Test**: `eos_tax/tests/test_settings.py`, class `TestSettingsRecalculate`:
`test_should_refuse_a_corporation_outside_the_taxed_alliances`. Create
`EveCorporationInfo.objects.create(corporation_id=98000777,
corporation_name="Outsider", corporation_ticker="OUT", member_count=1,
tax_rate=0.1)` without an alliance (copy the required fields from
`factories.create_corporation` if the model demands more), post
`corp_id="98000777", month="9", year="2026"`, assert status 400 and no
`MonthlyTax` row for that id. Red before the fix (200).

**Verify**: `eos-test eos_tax.tests.test_settings`

**Risk / depends on**: A Corporation that has left the alliance can no longer
be recalculated one at a time (the select did not offer it before either).
Blacklisted Corporations of a taxed alliance stay allowed - the task writes
their rows too, by an earlier decision. Independent of the other findings.

---

## TAX-07 - NPC bounties cached for the life of the process (Low)

**Where**: `eos_tax/db/tax_changes.py:86-103`, `_npc_bounties`.

**What happens**: The Corp Tax Changes page is opened before the static data
export is loaded (or `eve_sde` is installed later). `_npc_bounties()` returns
`{}`, and `lru_cache` keeps that answer until the gunicorn worker is restarted:
that worker keeps saying the feature cannot run, while a worker that started
later shows data - the page flips between the two on reload. The same cache
keeps an old export after an update: payouts with a new NPC type are dropped
(`_full_bounty` returns None) until every worker restarts.

**Cause**:

```python
@lru_cache(maxsize=1)
def _npc_bounties():
    ...
    except ImportError:
        logger.warning("eos_tax: eve_sde is not installed, no corp tax changes")
        return {}

    return dict(
        TypeDogma.objects.filter(dogma_attribute_id=BOUNTY_ATTRIBUTE_ID)
        ...
```

**Fix**:

1. `eos_tax/db/tax_changes.py`: remove `from functools import lru_cache`, add
   `from django.core.cache import cache`.

2. Above `_npc_bounties`:

   ```python
   NPC_BOUNTIES_KEY = "eos_tax:npc_bounties"
   # an hour: spares the page the table, and an export loaded since shows up
   # without restarting anything
   NPC_BOUNTIES_SECONDS = 60 * 60
   ```

3. Replace the function (the docstring stays):

   ```python
   def _npc_bounties():
       """...unchanged docstring..."""
       bounties = cache.get(NPC_BOUNTIES_KEY)
       if bounties:
           return bounties

       try:
           from eve_sde.models import TypeDogma
       except ImportError:
           logger.warning("eos_tax: eve_sde is not installed, no corp tax changes")
           return {}

       bounties = dict(
           TypeDogma.objects.filter(dogma_attribute_id=BOUNTY_ATTRIBUTE_ID)
           .exclude(value=None)
           .values_list("item_type_id", "value")
       )
       # an empty answer is not kept: the process-wide cache that stood here
       # held on to "no export" until the worker was restarted
       if bounties:
           cache.set(NPC_BOUNTIES_KEY, bounties, NPC_BOUNTIES_SECONDS)

       return bounties
   ```

4. `CHANGELOG.md`, `[Unreleased]`. No migration, no strings.

**Test**: `eos_tax/tests/test_tax_changes.py`, new class
`TestBountyCache(EosTaxTestCase)`, `test_should_ask_again_after_an_empty_answer`.
Imports: `sys`, `from types import SimpleNamespace`,
`from django.core.cache import cache`,
`from eos_tax.db.tax_changes import _npc_bounties`. Body:

```python
        getattr(_npc_bounties, "cache_clear", lambda: None)()
        cache.clear()
        self.addCleanup(cache.clear)

        def export(rows):
            model = mock.MagicMock()
            model.objects.filter.return_value.exclude.return_value \
                .values_list.return_value = rows
            return {
                "eve_sde": mock.MagicMock(),
                "eve_sde.models": SimpleNamespace(TypeDogma=model),
            }

        with mock.patch.dict(sys.modules, export([])):
            self.assertEqual(_npc_bounties(), {})

        with mock.patch.dict(sys.modules, export([(NPC_TYPE_ID, 1000.0)])):
            self.assertEqual(_npc_bounties(), {NPC_TYPE_ID: 1000.0})
```

Red before the fix (the second call returns the cached `{}`). Every other test
of the module patches `_npc_bounties` itself and is not touched.

**Verify**: `eos-test eos_tax.tests.test_tax_changes`

**Risk / depends on**: The table (a few thousand numbers) now travels through
the cache once per call instead of sitting in process memory - two calls per
page view. Independent of the other findings.

---

## TAX-08 - Admin: a mid-month `valid_from` for an existing month ends in a 500 (Low)

**Where**: `eos_tax/models.py:386-390`, `TaxRate.save`; reached through
`eos_tax/admin.py:17-21`, `TaxRateAdmin`.

**What happens**: The schedule holds `2026-09-01`. A staff user adds a rate in
the Django admin with `valid_from = 2026-09-17`. The form's uniqueness check
compares the day as typed, finds nothing, and `save()` then turns the date into
`2026-09-01` - the database's unique constraint refuses it and the admin
answers with a server error instead of a form error. The settings page is not
affected: its month picker only ever submits the first of a month.

**Cause**:

```python
    def save(self, *args, **kwargs):
        # the tax is calculated per month, so a mid month start would be
        # ambiguous - normalise before it can reach the database
        self.valid_from = self.valid_from.replace(day=1)
        super().save(*args, **kwargs)
```

The normalisation happens after validation.

**Fix**:

1. `eos_tax/models.py`, class `TaxRate`, above `save` (keep `save` as it is -
   `objects.create()` does not validate):

   ```python
    def clean(self):
        # before the uniqueness check, which otherwise compares the day as
        # typed and lets a second entry for the month through to the
        # database's own constraint - a server error in the admin
        if self.valid_from:
            self.valid_from = self.valid_from.replace(day=1)
   ```

2. `CHANGELOG.md`, `[Unreleased]`. A method only: no migration (confirm with
   the `Checks` command of `## Release`).

**Test**: `eos_tax/tests/test_settings.py`, class `TestTaxRateSchedule` (import
`TaxRateAdminForm` from `eos_tax.forms`):
`test_should_refuse_a_second_entry_for_the_month_in_the_admin`:
`TaxRate.objects.create(valid_from=date(2026, 9, 1), rate=Decimal("0.07"))`,
`form = TaxRateAdminForm({"valid_from": "2026-09-17", "rate": "9"})`,
`self.assertFalse(form.is_valid())`, `self.assertIn("valid_from", form.errors)`.
Red before the fix (the form is valid).

**Verify**: `eos-test eos_tax.tests.test_settings`

**Risk / depends on**: None known. Independent of the other findings.

---

## TAX-09 - Ages on the bots lists are stored in the worker's language (Low, PLAUSIBLE)

**Where**: `eos_tax/db/shared.py:225`, `grouped` (`row["age"] = format_age(...)`),
stored by `eos_tax/db/bot_store.py:82-106` and read back by `_restored`
(`bot_store.py:109-116`); shown by `partials/bot-table.html:43` and
`partials/bot-character-cells.html:26`.

**What happens**: The bots job runs in a Celery worker, where no reader's
language is active. `format_age` translates the unit there ("y", "mo", "d") and
the finished text is stored in `BotReport`. A reader with German or Korean
selected sees the instance's default language in the Age column of the four
stored lists, while the same column on GM Transactions and on the audit tab
(both format at request time) is in their language. `util.format_age_days`
says why the GM page stores days instead - the bots lists were left out.

PLAUSIBLE, not CONFIRMED: it only shows if the catalogues translate these units
differently from English and the worker runs in another language than the
reader - the `.po` files were not compared.

**Cause**:

```python
        row["age"] = format_age(ages.get(row["character_id"]))
```

(stored as text; `row["age_days"]` beside it holds the number).

**Fix**:

1. `eos_tax/db/bot_store.py`, add the import:

   ```python
   from eos_tax.util import format_age_days
   ```

2. `_restored`. Before:

   ```python
        for row in group["characters"]:
            for key in DATETIME_KEYS:
                if isinstance(row.get(key), str):
                    row[key] = parse_datetime(row[key])
   ```

   After:

   ```python
        for row in group["characters"]:
            for key in DATETIME_KEYS:
                if isinstance(row.get(key), str):
                    row[key] = parse_datetime(row[key])

            # the job wrote the age in the worker's language; the days it
            # stored beside it say it in the reader's
            if row.get("age_days") is not None:
                row["age"] = format_age_days(row["age_days"])
   ```

3. `CHANGELOG.md`, `[Unreleased]`. No migration, no new strings.

**Test**: `eos_tax/tests/test_bot_store.py`, beside
`test_should_bring_back_the_times_of_a_run_as_times`:
`test_should_write_the_age_from_the_stored_days`. Store one `BotReport` row for
a month and signal `"hours"` with `fingerprint=settings_fingerprint()` (import
it from `eos_tax.db.bot_store`), `computed_at=timezone.now()` and
`report={"listed": True, "stats": {}, "groups": [{"characters": [{"age": "stale",
"age_days": 400}]}]}`; read it with `get_stored_reports(year, month, ["hours"])`
and assert the row's `age` equals `format_age_days(400)` and is not `"stale"`.
Red before the fix.

**Verify**: `eos-test eos_tax.tests.test_bot_store`

**Risk / depends on**: Rows stored before `age_days` existed keep their text.
The same cause applies to `duration` (runs tab) and `apart_for` (clock tab),
which are stored as text built with the units "h" and "min"; they are left out
because the stored numbers beside them are rounded to a tenth of an hour - see
Open question Q6.

---

## Implementation order

1. **TAX-01** - own commit. The only finding that costs the alliance ISK.
2. **TAX-04** - own commit, after TAX-01 (both edit `find_payment`).
3. **TAX-03** - own commit (`set_corp_tax`).
4. **TAX-02** - own commit. Q1 is decided; Q2 and Q7 are still open but do
   not block it.
5. **TAX-05** and **TAX-06** - one commit, both tighten what `views.py` accepts.
6. **TAX-07**, **TAX-08**, **TAX-09** - one commit each or one together; they
   touch three unrelated files and none depends on another.

Run at most the module named under Verify while working; the full suite and the
translation tests run at `/commit`. No finding needs a migration; only a
decision in Q3 or Q6 could add translation strings.

## Checked and fine

- **Permissions**: every view in `urls.py` carries `login_required` and a permission check; the fetched write endpoints answer 403 (`raise_exception=True`). `settings` refuses a POST without `manage_settings` before any form is built.
- **Object level**: the overview limits a `basic_access` user to the Corporations of their own characters (`get_all_corps_for_user` -> `corp_id__in`); the menu badge uses the same list. Bots, GM, statistics and tax-change pages take ids from the URL but are open to `admin_view` / `gm_bots_access` only, who may see every character and Corporation by design.
- **GM notes and ticks**: `_is_listed` refuses a row the page does not show; `clean_note` trims, limits to 160 and drops control and format characters; the note reaches the page escaped and the script as text only.
- **Progress endpoints**: a `gm_bots_access` user gets and may dismiss only bots and GM runs; a run still going cannot be dismissed.
- **CSRF**: every state-changing endpoint is `require_POST` behind Django's middleware; every script that posts (`progress.js`, `gm-transactions.js`, `recalculate.js`, `settings.js`) sends `X-CSRFToken`. The GETs that queue a job are bounded by a cache lock per job (TAX-05 is the one exception).
- **XSS**: no `mark_safe`, `|safe`, `format_html` or `autoescape off` anywhere. The two `innerHTML` sinks (`bots.js`, `settings.js`) insert fragments rendered by Django templates with auto-escaping. `progress.js`, `statistics.js` and `gm-transactions.js` build DOM with `textContent`. Data for scripts travels through `json_script`. `?search=` and `?tab=` only reach DataTables' search and a regex-checked selector.
- **SQL**: ORM only; no `raw`, `extra`, `RawSQL` or cursor. No `eval`, `pickle`, `yaml`, `subprocess`.
- **Open redirect**: the only redirects are `reverse()` targets with a server-formatted month.
- **ESI / tokens / outgoing requests**: the app holds no token and asks for no scope; its two ESI calls (`get_corporation`, `get_affiliations`) are public endpoints through Alliance Auth's provider. No webhook, no user-supplied URL, nothing token-like in a log line.
- **Parameter validation**: year, month, alliance, corp, character and entry ids are parsed with `int()`/`strptime` and answered with 400 or a fallback; `show` is checked against a fixed list; an unknown tab name is a 404.
- **Forms**: `TaxConfigurationForm` and `TaxRateForm` list their fields; the rate fields are bounded 0-100 percent, every threshold carries min/max validators; `tax_types` only accepts offered choices. The two `fields = "__all__"` forms are admin-only.
- **Model defaults**: no default is read from settings at import time (`default=list`, constants); `app_settings.DEFAULT_*` only seeded migration 0005.
- **Delete cascades**: `MonthlyTax` holds plain ids, the two foreign keys are `SET_NULL`; no code deletes or changes an Alliance Auth or corptools row.
- **Paid is never taken back**: `set_corp_tax` is the only writer of `payed`, `amount_paid`, `paid_at`; apart from the race in TAX-03 it only ever adds.
- **Time**: journal ranges, day and hour buckets are explicit UTC (`_month_range`, `TruncDate`/`ExtractHour` with `tzinfo=utc`). `datetime.now()` in `get_dates`, `is_payable` and the views is UTC as long as Django's `TIME_ZONE` is `"UTC"`, which Alliance Auth's base settings set - do not change it for this instance.
- **Period boundaries**: half-open month ranges, December rolls into January, `relativedelta` for the previous month; a payment before its month is ignored.
- **Money arithmetic**: journal amounts stay `Decimal` until they are cut to whole ISK; the reconciliation sums floats, whose error stays far below one ISK at these magnitudes; the amount owed is stored once and the payment check reads that stored figure, so page and check cannot disagree.
- **Division by zero / empty cases**: `get_pve_income` (0 % corp tax), `_hour_series`, `_busy_share`, `_typical_hour`, `level_for` callers, `percent` in `get_runs`, empty journals and empty alliances were all followed - each has its guard.
- **Double counting in the tax base**: a matched member payout and its corporation slice count once (`_reconciled_income`); one journal side only for payments (`_one_side`).
- **Celery**: the bots and GM jobs are locked per month / globally and free the lock in `finally`; the tax subtasks are idempotent (`update_corp` rewrites the row). Progress state uses one cache key per job, so parallel workers do not overwrite each other.
- **Swallowed exceptions**: the two broad `except Exception` blocks (`_tax_rate_from_esi`, `_current_corporations`) log and fall back to "skip" / "keep listed"; every other handler re-raises.
- **N+1**: the overview, GM page, bots lists and statistics resolve names, mains and ages in one query per kind.
- **Templates**: every variable used in `index.html`, `gm-transactions.html`, `recalculate-result.html` and `progress.html` is supplied by its view; the other templates were spot-checked.
- **Migrations**: the four data migrations (0005, 0008, 0010, 0019) only touch this app's tables, guard their edge cases and have a noop reverse. Model/migration drift was **not** verified by command - `makemigrations --check` runs at `/commit`.
- **Dependencies**: `pyproject.toml` names what the code imports; `eve_sde` is optional and guarded. `default_app_config` in `__init__.py` is ignored by Django 5.2 - harmless.
- **`testauth/settings`**: the committed secret key and ESI credentials are dummies of the test project.
- **Known and accepted, not findings**: without reason codes one transfer of an amount settles every row owing exactly that amount (said in the setting's help text); blacklisted Corporations still get rows from the task; the tax-changes page reads a whole year of journal in the request (its footer shows the seconds); `auth_hooks` sets `self.count` on a shared hook instance, which is Alliance Auth's own documented pattern.

## Decisions (user, 2026-11-12)

- **Q1 - TAX-02**: unpaid rows are checked **three months back**, as the fix is written.
- **Q3 - TAX-01**: **README only**, no hint on the page, no new string. Several
  transfers with the same code (a correction payment on top of the first one)
  stay allowed and are still added up - TAX-01 does not touch that. It only
  refuses a single transfer whose reason names more than one code.
- **Q4 - progress bar**: the **exception text stays** for everyone who sees the
  bar; it is what makes a failure easy to find. Nothing to implement.
- **Q5 - `basic_access`**: **stays as it is**. Holders are at least CEO or
  alliance leadership and may see the characters without wallet audit.
  Nothing to implement.

- **Q2 - older unpaid months**: the overview and the badge **stay as they
  are**; a debt older than the previous month is followed up through
  eos-invoices. TAX-02 only makes sure a late payment is still recognised.
  Nothing more to implement.
- **Q6 - `duration` / `apart_for`**: **left as they are**. Nothing to implement.
- **Q7 - month flags**: **remove both** ("Include the previous month" and
  "Include the running month") and always work with the previous and the
  running month. Planned below as FU-01.

No question is open any more; Q2, Q6 and Q7 below are kept for the record.

## Follow-up change FU-01 - always the previous and the running month

Not a finding: a feature change the user decided with Q7. Own commit, after
TAX-02 (both touch what the task calculates).

**What changes for the reader**: the overview always lists the previous month
(payable from the 2nd) and the running month ("in progress"); the task always
calculates both. `dates[0]` in `views.index` is then always the previous
month, so the page title always names the previous month's rate.

**Steps**:

1. `eos_tax/util.py`, `get_dates`. Before:

   ```python
   def get_dates():

       config = get_config()
       dates = []

       if config.last_month:
           previous = datetime.now() - relativedelta(months=1)
           dates.append((previous.month, previous.year))

       if config.current_month:
           now = datetime.now()
           dates.append((now.month, now.year))

       return dates
   ```

   After:

   ```python
   def get_dates():
       """The months the task calculates and the overview shows: the previous
       one, payable from the 2nd, and the running one. Both always - the two
       switches that used to choose between them are gone."""
       now = datetime.now()
       previous = now - relativedelta(months=1)

       return [(previous.month, previous.year), (now.month, now.year)]
   ```

   `get_config` is still used further down in `util.py` - keep its import.

2. `eos_tax/models.py`, `TaxConfiguration`: delete the fields `last_month` and
   `current_month` (lines 82-89).
3. `eos_tax/forms.py`, `TaxConfigurationForm.Meta.fields`: delete the entries
   `"last_month"` and `"current_month"`.
4. `eos_tax/templates/eos_tax/settings.html:82-83`: delete the two
   `{% bootstrap_field ... %}` lines; check the text around them for a sentence
   that explains the switches and remove it too.
5. `eos_tax/app_settings.py`: delete `DEFAULT_LAST_MONTH` and
   `DEFAULT_CURRENT_MONTH` (nothing reads them). Leave migration 0005 alone:
   it reads `settings` itself and writes the fields on the historical model,
   which still has them at that point.
6. Migration: `makemigrations eos_tax` - expected `0035` with two
   `RemoveField` operations. Not yet applied anywhere; ask before migrating
   `aa_dev`.
7. `README.md`: remove `LAST_MONTH` / `CURRENT_MONTH` and any description of
   the two switches; say that both months are always calculated.
8. `CHANGELOG.md`, `[Unreleased]`.
9. Translations at the commit: the two help texts disappear from the source,
   so `makemessages` marks them obsolete in all six catalogues - no new string.

**Tests to change** (they set or post the removed fields):

- `tests/factories.py:179` `enable_current_month()` - remove it and its calls
  (`test_views.py:77, 135, 303, 347, 970, 1032`, `test_translations.py:223`),
  or keep the function returning the configuration where a caller uses the
  return value (`test_views.py:135`).
- Drop the assignments `config.last_month = ...` / `config.current_month = ...`
  in `test_views.py:136, 460, 801, 1098-1099`, `test_payments.py:1504-1505`,
  `test_bot_store.py:127-128`, `test_gm_bots_access.py:124`,
  `test_settings.py:892, 911`.
- Drop `"last_month": "on"` / `"current_month": "on"` from the settings POSTs
  (`test_settings.py:164-165`, `test_bot_store.py:212-213`) and the two
  assertions at `test_settings.py:186-187`.
- `test_settings.py:882-931` (`TestConfigurationTakesEffect`) and
  `test_views.py:1088-1117` (`TestTitleRate`) test the switches themselves:
  read them and rewrite or delete what no longer has a subject.
- New test, `tests/test_util.py`: `test_should_always_name_the_previous_and_the_running_month`
  - `get_dates()` equals the previous and the running month for today, and for
  a patched January (`eos_tax.util.datetime`) the first entry is December of
  the year before.

**Verify**: `eos-test eos_tax.tests.test_util`, then one call each for
`test_views`, `test_settings`, `test_payments`, `test_bot_store`,
`test_gm_bots_access`; the `Checks` command of `## Release` for the migration.

**Risk**: an instance that ran with only one of the switches on gets rows and
menu badge counts for the other month from the next task run on. On deploying:
migrate, then restart gunicorn and every Celery worker (the model lost two
columns).

## Questions as asked

**Q2 - Should unpaid rows of older months be visible?** Today a month disappears
from the overview and the menu badge once it is no longer the previous month,
paid or not - a debt nobody collected is simply gone from every page.
- a) Show unpaid rows of the same window as Q1 on the overview and count them in the badge (recommended; needs a small change to `get_website_data` and `get_open_payment_count`, to be planned once decided).
- b) Show them to `admin_view` only.
- c) Leave it as it is.

**Q7 - Remove the `current_month` setting?** (raised by the user with Q1; not a
finding, a feature change with a migration and removed strings - plan it
separately once decided)
- a) Remove it and always calculate the running month.
- b) Remove it and never calculate the running month (rows only from the 1st of the following month on).
- c) Keep it.

**Q6 - `duration` and `apart_for` on the runs and clock tabs** have the same
cause as TAX-09 (text built in the worker's language).
- a) Leave them (recommended) - the units "h" and "min" read the same in most of the six languages.
- b) Rebuild them at read time from the stored `hours` / `apart`; those are rounded to a tenth of an hour, so the minutes can differ by up to three from today's text.
- c) Store minutes in the job and format at read time; lists stored before keep their text until recomputed.
