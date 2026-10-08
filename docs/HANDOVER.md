# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-10-08.

## Release

- Version **0.3.12** in `eos_tax/__init__.py`, released 2026-10-08
- `[0.3.12]` in `CHANGELOG.md`: what was paid is recorded - "Amount paid in
  ISK" column on the overview with +/- badges, payments listed in the
  recalculate log, payments with a reason code added up (exact amount
  first), paid rows looked up again for their amount
- `[0.3.11]`: test users without a password, suite ~20 s instead of 88 s
- Migrations **0001-0021** applied to `aa_dev`
- 506 tests, all green (491 without the translation tag, 15 with it)
- All six catalogues (`de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`) are
  complete: `msgfmt --check` clean, nothing fuzzy or empty, `.mo` newer than
  `.po`. `ratter` is paraphrased in es/fr/it/ko/ru and kept literal in de,
  consistently in every place it occurs now, including `settings.html`
- `CHANGELOG.md` is newest first; `[0.3.2]` and `[0.3.6]` were written from
  the commits that raised those versions

## Decisions of the 2026-10-08 session

- **Paying more is recorded, not only accepted.** `MonthlyTax.amount_paid`
  and `payment_count` (migration 0021, applied to `aa_dev`) hold what
  `find_payment` (was `corp_has_payed`) found. Shown in the recalculate log
  and in an own overview column "Amount paid in ISK" - the user's choice
  over a note in the Paid column.
- **With reason codes: the exact amount first, then the sum.** The user's
  wording: look for the matching amount, if none fits add up and check
  whether the amount was reached. Partial payments therefore settle a row
  now; before, one transfer had to cover it alone.
- **Without reason codes only the exact amount counts**, as before - the
  user kept it on purpose.
- **Paid rows are looked up again** on every run for the amount (the flag
  stays). That is the backfill for rows paid before 0021, the user's
  choice over leaving them empty; there is no data migration.
- **One journal side only.** A transfer can be in the holding's and the
  payer's journal; `_one_side` adds up the fuller side. The dev data has a
  single payment to the holding, so whether both sides share an
  `entry_id` could not be checked - the sign split does not depend on it.
- **The new column is hidden on phones** (`d-none d-md-table-cell`), like
  the two rate columns. Claude's call, told to the user, not objected to.

## Decisions of the 2026-10-01 sessions

- **Tests keep their database while working, `/commit` builds it fresh.**
  `~/bin/eos-test` passes `--keepdb` unless given `--fresh`; the `## Release`
  suite line carries `--fresh`. Building the database ran every migration of
  the instance - 70-100 s of a 174 s run. One kept `test_aa_dev` serves all
  apps of the instance (same schema). The same change went into
  eos-auth-monitor, eos-invoices and discord_announcer.
- **The suite runs serially.** `--parallel 4` saved 7 of 26 s with a kept
  database, against clones that miss new migrations and a hang on a failing
  subtest.
- **The overview sorts by Month, then Corporation - nothing else.** The
  user's explicit wording ("nichts anderes"): Reason and Paid no longer take
  part in the default order, they stay sortable by click. The server side
  order in `db/payments.py` was left as it is.
- **Every group on the bots page has a heading, a group of one too**, on all
  four tabs. The user chose this over a separator line with a badge.
- **The average day divides by active days**, not by the days of the month.

## Decisions of the 2026-09-25 session

- **The DEBUG line in `help.html` is gone.** The 2026-09-25 review had kept
  it on the user's call ("This should say Invidia Administrative - if not
  tell Nah Vi in Discord"); later the same day the user asked for it to be
  removed. The copy button added alongside it makes the eyeball check it
  existed for redundant - the name now comes straight from
  `get_tax_corp()`, never retyped.
- **Paid is never taken back.** Once a row is marked paid no write may
  clear it; `set_corp_tax` only ever adds the flag.
- Recalculate keeps checking a payment against the stored amount before it
  recalculates - not changed on purpose.
- The blacklist is left as it is: corporations on it still get rows from
  the task.
- A month with alliance rate 0 gets no row.
- The day threshold on "Hours per day" counts once reached (`>=`).
- A character who moved counts with the last Corporation of the month.
- `bot_clock_min_concentration` defaults to **12** (2026-09-25, the user's
  own call, migration 0020 regenerated with it before it was ever applied).

## The bots page

Four readings of the same month that deliberately disagree. A character at the
top of one can be absent from the next, and that disagreement is the point.

| Tab | What it measures |
|---|---|
| Hours per day | different hours of a day, on enough days |
| Unbroken runs | a chain of payouts at the game's twenty minute tick |
| Against the Corporation | share of income inside the Corporation's busy hours |
| Off the Corporation clock | distance between the two middles of the day |

Each has its own thresholds on the settings page, which is cut into chapters -
one per page of the navigation, one sub-chapter per tab. The thresholds are
**deliberately not shared** between readings, even where the numbers agree
today: tuning one must not move another.

Two things are worth knowing before changing any of it.

**The yardstick is purged.** The two Corporation comparisons run twice: once to
find the characters they call bots, once with those characters taken out of the
baseline. A script with volume is part of its own Corporation's day and drags
it towards itself, which makes every other member look ordinary. Two passes and
not a fixed point - removing the flat characters makes the Corporation look
more concentrated, which would flag more of them, and where that ends says more
about the iteration than about the month. A Corporation that would fall under
its own floor keeps the plain yardstick. Both readings can be switched back to
it on the settings page.

**The character page does not compute its own grouping.** That would mean a
second walk over the whole month for the whole alliance, which is the cost the
tabs were split up to avoid. It takes the grouping from the list the reader
clicked through from, carried in the session (`SESSION_FAMILY` in `views.py`).
Opened cold - a bookmark, the search box - it falls back to the plain list of
alts from Alliance Auth, without assessments.

## Open

1. Nothing is blocked.
2. The new "Average day (hours)" column and the heading rows for groups of
   one have not been looked at in a browser yet - only through the tests.
   Worth one render with the seeded data (see below) before tuning anything
   on top of them.
3. The same for the "Amount paid in ISK" column, its badges and the new
   lines of the recalculate log: tested, not looked at in a browser. The
   Ether Element September row (see below) shows the `-` badge.

## Seeded test data

Five characters under the main **Kaskade Prime**, all in Ether Element
(98633815), 636 journal rows in September 2026:

| Character | Shows up on |
|---|---|
| Kaskade Beta | Hours per day, Against the Corporation, Off the clock |
| Kaskade Alpha | Unbroken runs |
| Kaskade Delta | Against the Corporation, Off the clock |
| Kaskade Gamma | Against the Corporation, Off the clock |
| Kaskade Prime | nothing - it is the main |

Beta holds 546 of Ether Element's 1249 payouts and covers 21 of 24 hours. That
is the character the purged yardstick was found on: moving her into a real
Corporation cost every other member of it about fifteen percentage points.

The seed also counts as tax: it adds 636,000,000 ISK to Ether Element's
September 2026 journal, so that row owes 1,497,770,014 instead of the
1,200,970,014 the real entries make, and the real payment of exactly the
latter (2026-10-02, reason `98633815/9/2026`) leaves it unpaid with
-296,800,000 in "Amount paid in ISK". Left that way on purpose (user's call,
2026-10-08): the row is the test case for an underpayment.

Removal and rollback records live outside the repo, next to the dev instance:

| | |
|---|---|
| `~/aa-dev/seeded-bot-family.json` | every id the seed created - its `entries` are journal `entry_id`s, not primary keys |
| `~/aa-dev/seeded-beta-move-undo.json` | Beta's Corporation before the move |
| `~/aa-dev/seeded-cleanup-record.json` | the audit and division removed on 14.09. |

Address these rows by their explicit ids. Never by a filter - see the warning
in `CLAUDE.md`.

## Looking at a page without logging in

The dev server wants EVE SSO, which cannot be automated. Render the page with
the Django test client instead (`force_login` on a user holding
`eos_tax.admin_view`), write it to a scratch file and serve that over a small
HTTP server.

Three traps in that setup, each of which produced a wrong answer once:

- **Subresource Integrity** fails for a cross-origin script because Django
  serves static files without CORS headers, and the browser reports nothing.
  Strip the `integrity` and `crossorigin` attributes from the snapshot.
- **The browser cache** then serves the version from before the edit anyway.
  Append a `?v=<timestamp>` to the app's own script URLs.
- **The obvious test user is the wrong one.** `force_login` on the seeded
  superuser (`allianceserver`) 302s to `/dashboard/` with no error - it has
  no main character, and `main_character_required` (every eos_tax URL goes
  through it via the app's `UrlHook`) redirects there before the view ever
  runs. Use a seeded user that has one, e.g. `kaskade`. Also reverse the URL
  rather than guessing it: the app is mounted at `/eos_tax/`, not `/eos-tax/`.

## Traps recent sessions cost time on

- **`eos-test` takes one test label.** A second module after the first is
  passed through as an option and `manage.py test` refuses it - run one
  module per call.
- **Someone else may migrate and start Celery meanwhile.** On 2026-10-08
  migration 0021 was applied to `aa_dev` and a worker started from a VS Code
  terminal a minute after the migration was generated, not by the session.
  Check `showmigrations` before migrating, and leave a worker on someone's
  terminal alone.
- **`compilemessages` has to run from `eos_tax/`, the same as
  `makemessages`, not from `myauth/`.** Run from `myauth` it reported no
  error and did nothing - all six `.mo` stayed at their old content,
  silently. Only the `.mo`-newer-than-`.po` timestamp check caught it.
- **`makemessages -a` from `eos_tax/` did nothing on 2026-10-01** - exit
  code 0, no "processing locale" line, all six `.po` untouched. Naming the
  locales works: `makemessages -l de -l es -l fr_FR -l it_IT -l ko_KR -l ru`.
  It then put the translation of "Busiest day (hours)" onto the new "Average
  day (hours)" as a fuzzy guess in all six - the trap `CLAUDE.md` warns about.
- **Two sessions share `test_aa_dev`** - all the more now that it is kept.
  With another session running tests in the same instance, `--parallel 4`
  failed with "Can't create database 'test_aa_dev'; database exists" and a
  missing `esi_token` table. Both sessions also edit the same working tree.
  A second session runs with `EOS_TEST_DB=<own name>`.
- **Editing `~/bin/eos-test` through `\\wsl.localhost` dropped its execute
  bit** - `chmod +x` afterwards.
- **Old test databases are lying around** in MySQL: `test_aa_dev_5` to `_8`,
  `_a1`, `_fix`, `_lang`, `_pay`, `test_main_session_4` - clones and
  `EOS_TEST_DB` names of earlier sessions. Not touched; dropping them needs
  the user's yes.
- **A kept `test_aa_dev` is new**: a migration rewritten after it was
  applied there, or another branch's schema, needs `eos-test ... --fresh`.
