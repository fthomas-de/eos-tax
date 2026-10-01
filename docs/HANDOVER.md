# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-10-01.

## Release

- Version **0.3.10** in `eos_tax/__init__.py`, released 2026-10-01 and
  pushed together with 0.3.9, which had been committed on 2026-09-28 but
  never pushed
- `[0.3.10]` in `CHANGELOG.md`: "Average day (hours)" column on "Hours per
  day", a heading row for groups of one on all four bots tabs, the overview
  sorted by Month then Corporation only, and the payment tests that failed on
  the first of every month (`mid_month()` in `factories.py`)
- `[0.3.9]` is empty on purpose: the only change was `LICENSE`'s copyright
  holder (a leftover from the plugin template), not worth a changelog line
- Migrations **0001-0020** applied to `aa_dev`; 0.3.10 brings none
- 471 tests, all green (456 without the translation tag, 15 with it)
- All six catalogues (`de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`) are
  complete: `msgfmt --check` clean, nothing fuzzy or empty, `.mo` newer than
  `.po`. `ratter` is paraphrased in es/fr/it/ko/ru and kept literal in de,
  consistently in every place it occurs now, including `settings.html`
- `CHANGELOG.md` is newest first; `[0.3.2]` and `[0.3.6]` were written from
  the commits that raised those versions

## Decisions of the 2026-10-01 session

- **The overview sorts by Month, then Corporation - nothing else.** The
  user's explicit wording ("nichts anderes"): Reason and Paid no longer take
  part in the default order, they stay sortable by click. The server side
  order in `db/payments.py` was left as it is.
- **Every group on the bots page has a heading, a group of one too**, on all
  four tabs. The user chose this over a separator line with a badge.
- **The average day divides by active days**, not by the days of the month.
- Version **0.3.10** rather than folding the new work into the unpushed
  0.3.9.

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

Removal and rollback records live outside the repo, next to the dev instance:

| | |
|---|---|
| `~/aa-dev/seeded-bot-family.json` | every id the seed created |
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

## Traps this session cost time on

- **`compilemessages` has to run from `eos_tax/`, the same as
  `makemessages`, not from `myauth/`.** Run from `myauth` it reported no
  error and did nothing - all six `.mo` stayed at their old content,
  silently. Only the `.mo`-newer-than-`.po` timestamp check caught it.
- **`makemessages -a` from `eos_tax/` did nothing on 2026-10-01** - exit
  code 0, no "processing locale" line, all six `.po` untouched. Naming the
  locales works: `makemessages -l de -l es -l fr_FR -l it_IT -l ko_KR -l ru`.
  It then put the translation of "Busiest day (hours)" onto the new "Average
  day (hours)" as a fuzzy guess in all six - the trap `CLAUDE.md` warns about.
- **Two sessions share `test_aa_dev`.** With another session running tests
  in the same instance, `--parallel 4` failed with "Can't create database
  'test_aa_dev'; database exists" and a missing `esi_token` table. Both
  sessions also edit the same working tree - the date fix of the other one
  turned up uncommitted in `git status` at `/commit`. A serial run with
  `EOS_TEST_DB=<own name>` was clean.
- **Release 0.3.9 sat unpushed** from 2026-09-28 until this push - `git log
  @{u}..HEAD` at the start of `/push` is what showed it.
