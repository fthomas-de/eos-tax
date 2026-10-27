# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-10-27.

## Release

- Version **0.4.6** in `eos_tax/__init__.py`, released 2026-10-27
- `[0.4.6]` in `CHANGELOG.md`:
  - **The bots lists come from a Celery job** (`run_update_bot_reports`,
    `db/bot_store.py`), stored in `BotReport` (migration 0028) - one row
    per month and tab, with a fingerprint of the settings they depend on.
    Live, "Hours per day" took ~30 s and "Unbroken runs" ~10 s per visit.
  - **Fifth tab "Without current audit"** (`db/bot_audit.py`,
    `partials/bot-audit.html`): characters shown on the four lists whose
    corptools audit is missing or `active = False`, grouped by main
  - 11 new strings, in all six catalogues
- Earlier versions: see `CHANGELOG.md`. Still worth knowing from them:
  `manage_settings` (0.4.5, migration 0027) guards every settings write;
  `admin_view` alone sees the settings page read only
- Migrations **0001-0028** applied to `aa_dev`
- 645 tests, all green (630 without the translation tag, 15 with it)
- All six catalogues (`de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`) are
  complete: `msgfmt --check` clean, nothing fuzzy or empty, `.mo` newer than
  `.po`. `ratter` is paraphrased in es/fr/it/ko/ru and kept literal in de
- `CHANGELOG.md` is newest first

## Decisions of the 2026-10-27 session

The audit tab - the user's choices unless marked:

- **"Listed" means what a tab shows**: its first ten mains, or the
  fallback list when nobody crossed the threshold. Not every row a reading
  scored.
- **Only the listed characters are checked**, not the rest of the account
  (the user's choice over "every character of the main").
- **Current = corptools' own `active` flag**; no `CharacterAudit` row
  counts as "no audit", `active = False` as "not current". Read live at
  render, not stored with the lists (Claude's call), so a renewed token
  shows at once.
- **Characters without an Alliance Auth account are listed** as a group of
  their own ("no main known"), the way the tabs list them.
- Claude's calls: every main is listed (no ten cap - it is already a cut of
  four cut lists); a character carries the strongest assessment of the
  tabs that listed it; each tab name is a link that reopens that tab for
  the month; the character page does not get the tab
  (`bot-tabs.html` takes `audit_tab=True` from `bots.html` only).

The job - the user's choices unless marked:

- **Stored in an own DB table**, not the cache.
- **A month never computed queues the job and the tab says so**
  (`partials/bot-pending.html`, `data-eos-pending`); `bots.js` asks again
  every 20 s while the tab is open, the first tab reloads the page
  (interval: Claude's call). Not computed live.
- **Runs with the tax job** (`run_update_alliance` queues
  `queue_bot_reports(get_dates())`), no own beat entry.
- **A settings save recomputes the previous and the running month at
  once** when the fingerprint changed; older months notice on their next
  visit.
- Claude's calls: the fingerprint covers every `bot_*` field, the taxed
  types, the alliances and the blacklist; a list under another
  fingerprint is treated as missing, not shown with a warning. One job per
  month at a time via a cache lock (`BOT_REPORT_LOCK`, 15 min, deleted in
  `finally`). Only `listed`, `groups` and `stats` are stored, not every
  scored row. Run times (`started_at`, `ended_at`) are turned back into
  datetimes on read (`DATETIME_KEYS`). Every list shows "computed … EVE".

## Earlier decisions still in force

- **`admin_view` sees the settings page read only** (2026-10-26); the
  writes need `manage_settings` on top. The fetched endpoints
  (`settings_recalculate`, `progress_dismiss`) answer a missing
  `manage_settings` with 403, not the login redirect.
- **The bot readings may share logic where it makes sense**; the
  thresholds per reading stay separate (see "The bots page").
- **Former members are not listed as "without wallet audit"**: ESI
  `/characters/affiliation/` at recalculation, only for characters above
  the threshold, chunks of 1000. ESI down = stays listed.
  `EosTaxTestCase.setUpClass` patches `get_affiliations` to answer nobody.
- **Member wallet entries count only while in the Corporation**, by
  corptools' `CorporationHistory`; no history = counts nothing; a payout
  the Corporation taxed counts regardless.
- **0% ingame tax is taxed from the member wallets**, reconciled with the
  corporation wallet (key: character, second, system, reason, ref_type;
  fallback within `LOOSE_MATCH_WINDOW`). Never verified against real
  member data.
- **A missing ingame rate is asked from ESI** (`_tax_rate_from_esi`) - AA
  5.2-5.5 stores 0% as `None`. Not written back.
- **Payments**: with reason codes the exact amount first, then the sum;
  without reason codes only the exact amount. Paid is never taken back.
  Paid rows are looked up again for the amount. One journal side only.
- **Overview**: filter `?show=open|paid|progress|all`, Outstanding the
  default; sorts by Month, then Corporation, nothing else; payment
  difference badges only for admins and from `paid_difference_min_millions`
  (default 10) on.
- **Progress bar** of every recalculation, admins only, cache only, a
  finished run shows "Reload".
- Every group on the bots page has a heading, a group of one too. The
  average day divides by active days. `bot_clock_min_concentration`
  defaults to 12. The blacklist still gets rows from the task. A month
  with alliance rate 0 gets no row.

## The bots page

Five tabs. The first four are readings of the same month that deliberately
disagree - a character at the top of one can be absent from the next, and
that disagreement is the point. The fifth sums them up.

| Tab | What it shows |
|---|---|
| Hours per day | different hours of a day, on enough days |
| Unbroken runs | a chain of payouts at the game's twenty minute tick |
| Against the Corporation | share of income inside the Corporation's busy hours |
| Off the Corporation clock | distance between the two middles of the day |
| Without current audit | characters on the four lists without a current corptools audit |

**The page reads, the job computes.** `bots` and `bot_signal` in
`views.py` go through `_stored_reports`: stored lists for the month and
the current fingerprint, else queue the job and render the pending note.
After queueing it looks once more - with an eager Celery (the tests) the
lists are there by then. The readings themselves (`get_bot_report`,
`get_unbroken_runs`, `get_daily_profile`, `get_clock_offset`) are
unchanged and listed in `bot_store.READINGS`; the character page and its
detail tabs still compute live (one character is cheap).

Each reading has its own thresholds on the settings page, cut into
chapters - one per page of the navigation, one sub-chapter per tab. The
thresholds are **deliberately not shared** between readings.

**The yardstick is purged.** The two Corporation comparisons run twice: once
to find the characters they call bots, once with those characters taken out
of the baseline. Two passes and not a fixed point. A Corporation that would
fall under its own floor keeps the plain yardstick. Both readings can be
switched back to it on the settings page.

**The character page does not compute its own grouping.** It takes the
grouping from the list the reader clicked through from, carried in the
session (`SESSION_FAMILY` in `views.py`). Opened cold it falls back to the
plain list of alts from Alliance Auth, without assessments.

## Open

1. **On deploying 0.4.6: apply migration 0028 and restart every Celery
   worker** - a worker started before it does not know
   `run_update_bot_reports`, and the tabs would wait forever. Until the
   first job ran, every tab shows "being calculated". Check the beat
   cadence of `run_update_alliance` in production: the running month's
   lists are only as fresh as its last run ("computed … EVE" says when).
2. Not looked at in a browser yet, only through the tests: the audit tab,
   the pending note with the 20 s retry (fetched tabs) and the page reload
   (first tab), the "computed … EVE" lines. From earlier versions also not
   rendered yet: the read-only settings page with an `admin_view`-only
   user (0.4.5), the 0.4.4 template moves, the overview's four state links,
   the "Earned in total" tooltip and sum badge, the Paid tooltip, the
   overview columns "Characters without wallet audit", "Calculation time",
   "Amount paid in ISK" with its badges, and the "Payment differences"
   block on the settings page. One render with the seeded data before
   building on any of them.
3. **Known limitation of the stored lists**: names, mains and ages are
   taken when the job runs. A character moved to another main shows
   under the old one until the next run of that month; past months are
   only recomputed when a setting changes or someone asks after a
   fingerprint change.
4. **Worth a look in production**: the footer of "Hours per day" splits
   its time into database and aggregation. If the ~30 s are mostly
   database, the query (grouping the whole month by character, day, hour
   and ref_type) may be worth an index or a rewrite - corptools' schema is
   not ours to change, so only the query.
5. On deploying 0.4.5: grant `eos_tax.manage_settings` to whoever changes
   the settings, or only superusers can.
6. After deploying 0.3.14/0.3.15, recalculate urex (your ex's) for every
   month it ran at 0% and check that "added" in the log holds only untaxed
   payouts - the matching key has never seen real member wallet data.
7. The affiliation filter (0.4.3) has never talked to the real ESI - check
   the log line "... has left this corporation since" after a
   recalculation; "ESI affiliation lookup failed" means everyone stayed
   listed.
8. Rows written before 0023/0024 show no characters and no calculation
   time until recalculated; rows paid before 0025 never get a "recorded
   as paid" time.

## State of the dev instance

- Migrations 0001-0028 applied to `aa_dev`.
- `eos_tax_botreport` holds 8 rows from a trial run of the job (2026-09
  and 2026-10, all four tabs) - our own table, safe to overwrite or
  delete. In the dev data nobody listed has a corptools audit, so the
  audit tab lists everyone as "no audit".
- No Celery worker was running at the end of the session.

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

Beta holds 546 of Ether Element's 1249 payouts and covers 21 of 24 hours -
the character the purged yardstick was found on.

The seed also counts as tax: Ether Element's September 2026 row owes
1,497,770,014 instead of 1,200,970,014, and the real payment of exactly the
latter leaves it unpaid with -296,800,000 in "Amount paid in ISK". Left
that way on purpose (user's call, 2026-10-08): the row is the test case for
an underpayment.

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
  superuser (`allianceserver`) 302s to `/dashboard/` - it has no main
  character. Use a seeded user that has one, e.g. `kaskade`. The app is
  mounted at `/eos_tax/`, not `/eos-tax/`.

The bots tabs now need stored lists: run `store_bot_reports(year, month)`
in `manage.py shell` first, or the snapshot shows "being calculated".

## Traps recent sessions cost time on

- **The bots views need stored lists in tests.** `EosTaxTestCase` patches
  `run_update_bot_reports.delay` to run the job in place. A test about the
  waiting state patches `delay` away again and must `cache.clear()` in its
  cleanup - the locmem cache is shared across tests, and a lock left
  behind makes every later bots page test show "being calculated". To feed
  a hand-made reading into the job, `mock.patch.dict` on
  `eos_tax.db.bot_store.READINGS`; patching `eos_tax.views.get_bot_report`
  no longer reaches anything.
- **A ModelForm writes the posted values into its instance at
  `is_valid()`**, before `save()`. The settings fingerprint is therefore
  taken before the form is built; taken after validation it never differs
  and a changed threshold would not recompute anything.
- **Sabotages run together can hide each other.** The lock sabotage
  (`True or cache.add`) made the `finally` sabotage pass. Run a sabotage
  whose test depends on another guard in a run of its own.
- **A command in Git Bash that reads stdin hangs until the timeout** - a
  stray `cat > file` without input stopped one run for ten minutes. Feed
  `< /dev/null` to test runs started through scripts.
- **Static files are hashed in tests.** `sri_static` goes through the
  manifest storage: assert `"eos_tax/js/progress."`, never `progress.js`,
  and run `collectstatic` before a test that renders a new script.
- **A `msgctxt` entry needs the context in the catalogue test**: `read_po`
  keys them `context\x04msgid`.
- **Celery task arguments are a contract with the running worker.** A new
  task or keyword fails in a worker started before the change - restart it.
- **The overview shows only outstanding rows by default.** A view test
  about a row's markup requests `{"show": "all"}`.
- **A Python patch script inside a bash heredoc breaks on its quotes** -
  write the script with the Write tool, as `CLAUDE.md` says. The same
  goes for inline `python -c` through `wsl.exe ... bash -lc`.
- **A `%` in a translatable text breaks every catalogue** ("0% ingame" is
  read as `% i`). Write "without ingame tax" or "zero percent".
- **gettext's fuzzy guesses are wrong almost every time**: for 0.4.6 it
  put "Wallet audit" on "no audit" and "Character %(value)s" on
  "computed %(value)s EVE" in all six catalogues.
- **A stale `.git/CLAUDE_COMMIT_MSG` gets committed.** Read the file
  first, and check `git log -1` before anything is pushed.
- **A fix with two guards needs a sabotage of both at once**, and **a
  sabotage that does not compile proves nothing** - replace with valid
  code.
- **`eos-test` takes one test label** - run one module per call.
- **Someone else may migrate and start Celery meanwhile.** Check
  `showmigrations` before migrating, and leave a worker on someone's
  terminal alone.
- **`compilemessages` and `makemessages` run from `eos_tax/`**, not from
  `myauth/`, and `makemessages` with the locales named
  (`-l de -l es -l fr_FR -l it_IT -l ko_KR -l ru`); `-a` did nothing.
  Check `.mo` newer than `.po` afterwards.
- **Two sessions share `test_aa_dev`** - a second session runs with
  `EOS_TEST_DB=<own name>`.
- **Editing `~/bin/eos-test` through `\\wsl.localhost` drops its execute
  bit** - `chmod +x` afterwards.
- **Old test databases are lying around** in MySQL (`test_aa_dev_5` to
  `_8`, `_a1`, `_fix`, `_lang`, `_pay`, `test_main_session_4`). Not
  touched; dropping them needs the user's yes.
- **A kept `test_aa_dev`**: a migration rewritten after it was applied
  there, or another branch's schema, needs `eos-test ... --fresh`.
