# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-09-14.

## Release

- Version **0.3.1** in `eos_tax/__init__.py`; `[0.3.0]` is committed,
  `[0.3.1]` is the running section
- Migrations **0011-0018** are written and applied
- Catalogues complete: six languages, nothing empty, nothing fuzzy
- 406 tests green, `makemigrations --check` clean, `collectstatic` run
- `CHANGELOG.md`: `[0.2.2]`-`[0.2.6]` were split out retroactively by diffing
  each version's own changelog out of git; `[0.3.0]`/`[0.3.1]` were split at
  the commit that actually raised the version in between

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

1. Nothing is blocked. The four points that were open on 2026-09-14 are done:
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
