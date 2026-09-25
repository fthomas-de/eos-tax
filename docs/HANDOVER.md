# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-09-25.

## Release

- Version **0.3.7** in `eos_tax/__init__.py`, **not committed** - the review
  and the translation round of 2026-09-25 sit in the working tree, under
  `[0.3.7]` in `CHANGELOG.md`
- Migrations **0001-0020** applied to `aa_dev`, including **0020**
  (`bot_clock_min_concentration`, default 12, and the help text updates)
- 463 tests, all green. `python runtests.py eos_tax` on testauth gives the
  same result
- All six catalogues (`de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`) are
  complete: `msgfmt --check` clean, nothing fuzzy or empty, `.mo` newer than
  `.po`. `ratter` is paraphrased in es/fr/it/ko/ru and kept literal in de,
  consistently in every place it occurs now, including `settings.html`
- `CHANGELOG.md` is newest first; `[0.3.2]` and `[0.3.6]` were written from
  the commits that raised those versions

## Decisions of the 2026-09-25 review

- **Paid is never taken back.** Once a row is marked paid no write may
  clear it; `set_corp_tax` only ever adds the flag.
- Recalculate keeps checking a payment against the stored amount before it
  recalculates - not changed on purpose.
- The DEBUG line in `help.html` ("This should say Invidia Administrative")
  stays, on the user's call.
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

1. Before 2026-09-25: nothing was blocked. The four points that were open on 2026-09-14 are done:
   the two list thresholds were lowered to 0 pp and 3 h, the empty audit and
   division the seed left behind in corptools were removed, and the list links
   now keep the tab the reader is on.

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
