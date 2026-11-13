# Handover

Where the work stands and what is still open. `CLAUDE.md` holds the durable
rules for working on this app; this file holds the moment, and goes stale on
purpose - if a statement here contradicts the code, the code is right.

Last updated 2026-11-13 (0.4.24).

## Release

- Version **0.4.24** in `eos_tax/__init__.py`, released 2026-11-13, tag
  `v0.4.24`
- `[0.4.24]` in `CHANGELOG.md`: Simplified Chinese (`zh_Hans`), the
  seventh catalogue, so eos-tax and eos-invoices ship the same languages.
  No code change; `test_translations.py` knows the new locale. Decisions
  below
- `[0.4.23]`: a sixth bots tab "Possibly banned" -
  characters any of the four readings showed in a stored month whose last
  corptools login is at least `possibly_banned_min_days` (default 30,
  migration 0037) ago, grouped by main, with the months listed. Where it
  lives: `db/bot_ban.py` (`get_possibly_banned`), the `banned` branch of
  `views.bot_signal`, `partials/bot-banned.html`, the card at the end of
  the bots chapter of `settings.html`, tests in `test_bot_ban.py`.
  `bots.js` needed no change - it fetches and sorts any `data-eos-signal`
  pane. Decisions below
- `[0.4.22]`: a button beside every name on the five
  bots tabs opens the character's information window in the reader's EVE
  client (ESI `esi-ui.open_window.v1`, modelled on aa-srp). Where it
  lives: `providers.py` (own ESI client), `UiCharacter` (migration 0036),
  views `ui_character_add` / `ui_character_select` / `open_window`,
  `partials/ui-character.html` (header dropdown),
  `partials/open-window-button.html`, `js/open-window.js`, tests in
  `test_open_window.py`. Decisions below
- `[0.4.21]`: the fixes of the audit of 2026-11-11 and
  the end of the month switches. `docs/AUDIT.md` holds the findings
  (TAX-01 to TAX-09), the user's decisions and the plan they were built
  from; everything in it is implemented. Where each fix lives:
  - **TAX-01** `util.find_payment`: a transfer counts only when its reason
    names this row's code and no other (`REASON_CODE`). Several transfers
    with one code still add up - the user wants correction payments
  - **TAX-02** `tasks.overdue_jobs`: the periodic task also recalculates
    unpaid rows `OVERDUE_MONTHS` = 3 months back, passed to
    `queue_corporations(..., extra=)`
  - **TAX-03** `set_corp_tax` is `@transaction.atomic` and reads the row
    with `select_for_update()`
  - **TAX-04** `find_payment(..., amount_to_pay=)`, used only while the
    month has no row; `update_corp` hands in `round(gross_income *
    alliance_tax_rate)` - keep it equal to `set_corp_tax`'s formula
  - **TAX-05** `views.FIRST_YEAR` = 2003: `_selected_month` falls back to
    the running month for a month before it or in the future,
    `bots_recalculate` answers 400
  - **TAX-06** `settings_recalculate` answers 400 for a Corporation outside
    the taxed alliances
  - **TAX-07** `tax_changes._npc_bounties` keeps the table in the Django
    cache for an hour (`NPC_BOUNTIES_KEY`), an empty one not at all
  - **TAX-08** `TaxRate.clean()` puts the day on the first before the
    uniqueness check
  - **TAX-09** `bot_store._restored` writes `age` from `age_days` when the
    lists are read
  - **Month switches gone** (migration 0035): `TaxConfiguration.last_month`
    and `current_month`, their form fields and the settings heading
    "Months"; `get_dates()` always returns the previous and the running
    month. The three strings are obsolete (`#~`) in all six catalogues
- Earlier versions, in short (details in `CHANGELOG.md`): 0.4.20 `?search=`
  on GM Transactions; 0.4.19 the "Cleared" tick (`GmNote.cleared`, 0034);
  0.4.18 the five largest payments in the sum badge (0033); 0.4.17 green
  for one exact payment among several (0032); 0.4.16 copy buttons, red rows
  and the GM tab on the bots pages; 0.4.15 `gm_bots_access` (0031); 0.4.13
  notes on GM Transactions (`GmNote`, 0030); 0.4.10 Recalculate buttons
  and step runs on the bar; 0.4.6/0.4.7 the bots and GM jobs (`BotReport`
  0028, `GmReport` 0029). `manage_settings` (0.4.5, 0027) guards every
  settings write; `admin_view` alone sees the settings page read only
- Migrations **0001-0037** applied to `aa_dev`
- 847 tests, all green (832 without the translation tag, 15 with it); the
  suite ran `--fresh` at the commit
- `aa_dev` has **no GM transactions** and no stored `GmReport`: the page's
  GM rows can only be seen in tests or on production data. 0.4.9 to 0.4.16
  on GM Transactions are verified by tests only, not in the browser
- All seven catalogues (`de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`,
  `zh_Hans`) are complete: `msgfmt --check` clean, nothing fuzzy or empty,
  `.mo` newer than `.po`. `ratter` is paraphrased in es/fr/it/ko/ru/zh and
  kept literal in de. `zh_Hans` (0.4.24) is machine-translated, not read by
  a native speaker, not looked at in a browser
- `CHANGELOG.md` is newest first

## Decisions of the 2026-11-13 session (0.4.24)

Simplified Chinese - the user's choices unless marked:

- **eos-tax and eos-invoices ship the same languages**: eos-tax got
  `zh_Hans`, eos-invoices gets es, fr_FR, it_IT, ko_KR in a session of its
  own (that repo, not this one).
- **Translated the way the other six are**: by hand in the `.po` (no
  glossary tool here), EVE jargon English, `ratter` paraphrased (刷怪玩家).
- **Alliance Auth's clashes accepted**: the bare column titles Alliance,
  Character and Corporation show AA's 所在联盟 / 角色 / 公司 on a Chinese page,
  as German shows "Allianz". A `msgctxt` would fix it in all seven
  catalogues - offered, not chosen.
- Claude's calls: terms taken from eos-invoices' `tools/glossary.py`
  (概览, 已付, 设置 ...); payout = 发放, run = 连续段, yardstick = 参照基准,
  reading = 判读, journal = 流水, Bots = 机器人, audit = 审计; the jargon test
  rejects 赏金, 公司, 军团, 联盟, 原因, 钱包, 角色; the language test uses
  如何缴税？ because 概览 also comes from eos-invoices (caught by removing the
  `.mo`, both new checks failed once the word was changed).

## Decisions of the 2026-11-13 session (0.4.23)

Sixth bots tab "Possibly banned" - the user's choices unless marked:

- **Tab name "Possibly banned"**; characters **grouped by main**.
- **Everything a tab showed counts**, the fallback list included (chosen
  over "crossed a threshold only" and "high/medium only").
- **All months a character was listed in, newest first**, as badges
  linking to that month's bots page.
- **No known login (no audit, or `last_known_login` empty) = left out.**
- **Days in the settings, default 30** (`possibly_banned_min_days`,
  migration 0037, applied to `aa_dev`), card "Possibly banned" at the end
  of the bots chapter.
- Claude's calls: `db/bot_ban.py`, read live at every fetch, no job; only
  the four readings' `BotReport` rows, **every stored month whatever its
  fingerprint**; the tab ignores the month selector; the field name has no
  `bot_` prefix so it stays out of the fingerprint (tested); Corporation
  of today from `EveCharacter`, falling back to the stored name; age live
  via `grouped()`; login compared with `<=` now minus the days; red rows
  for GM-listed characters like the other tabs; no level column. A month
  recomputed after a settings change replaces its list, so a character
  can drop out of the history. 16 tests in `test_bot_ban.py`, seven
  sabotages caught. Not looked at in a browser; empty on `aa_dev` (nobody
  there has a login). The eight new strings are in all six catalogues
  (tab: "Möglicherweise gebannt", "Posiblemente baneado", "Peut-être
  banni", "Forse bannato", "밴 가능성", "Возможно, забанен").

## Decisions of the 2026-11-13 session (0.4.22)

In-game window button on the bots tabs, modelled on aa-srp - the user's
choices unless marked:

- **The chosen character is stored per user in the DB** (`UiCharacter`,
  migration 0036, applied to `aa_dev`), not in the browser or session.
- **On all five bots tabs**, not on GM Transactions or the character page.
- **The listed character only**, no button beside the main.
- **Feedback as a status line in the card header**, like Recalculate.
- Claude's calls: own `ESIClientProvider` in `providers.py` (AA's
  `open_api_provider` is limited to its own operations), compatibility
  date taken from Alliance Auth; the dropdown offers own characters with
  an `esi-ui.open_window.v1` token, saved on change by fetch; `+` goes
  through `token_required`; the button is always clickable - without a
  choice the server answers "Choose your in-game character above first."
  (the fetched tabs would otherwise need the choice in their context);
  any target id is accepted (an info window is public); icon
  `fa-display`. Saving a token makes Alliance Auth move the character's
  ownership to the token's user, so the "not one of your characters"
  branch of `ui_character_add` is tested with an unsaved token.
- 16 tests in `test_open_window.py`, six sabotages caught. Not looked at
  in a browser, never talked to the real ESI. The ten new strings are in
  all six catalogues ("Character" kept English, no "персонаж" in ru).

## Decisions of the 2026-11-12 session

The audit (`docs/AUDIT.md`, "Decisions") - the user's choices:

- **Unpaid rows are followed up three months back** by the task. The
  overview and the menu badge **stay at the previous and the running
  month**; an older debt is followed up through eos-invoices.
- **The two month switches go**, the app always works with the previous
  and the running month (`LAST_MONTH` / `CURRENT_MONTH` in `local.py` are
  no longer read).
- **Correction payments stay allowed**: several transfers with the same
  code add up. Only one transfer naming two codes is refused. No hint on
  the page, the README says it.
- **Left as they are**: the exception text on the progress bar (it is what
  makes a failure easy to find); what `basic_access` sees, the characters
  without wallet audit included (holders are CEOs or alliance leadership);
  `duration` / `apart_for` on the runs and clock tabs written in the
  worker's language.
- Claude's calls: a reason that names another `n/n/n` beside the code (a
  date written that way) is refused too; rows settled earlier by a
  two-code transfer stay paid - paid is never taken back; 2003 as the
  first month a journal can exist for.

## Decisions of the 2026-11-06 sessions

`?search=` on GM Transactions (0.4.20), for the link from
eos-auth-monitor - the user's choices:

- **The main's name only, quoted** - not the corporation too (it would
  hide alts in other corps), and not a hidden filter on the Main column
  (invisible, not clearable). The search also hits Character, Note,
  Description and the corporation columns, which is accepted.
- **The alliance switch stays on** when the parameter is present: a main
  whose whole account has left shows an empty table until the switch is
  turned off.

"Cleared" on GM Transactions (0.4.19) - the user's
choices unless marked:

- **A tick per row needs a note**; **emptying the note takes the tick
  away** (the note row is deleted, the flag with it).
- **A cleared row's alliance mark turns grey** (`text-body-secondary`),
  not empty - empty means "left".
- **Switch "Hide cleared rows", off by default.**
- **The bots lists stay red** for a cleared character; **the GM tab of
  the character page shows the tick** read only (green `fa-check`).
- Claude's calls: `GmNote.cleared` (migration 0034), not a table of its
  own; POST `gm_transactions_cleared` (`BOTS_GM_READ`, 403), answers
  `{"cleared": bool}`, refuses an unlisted row or a row without a note
  (taking a tick off a row without a note is a quiet no-op); the column
  third, after Note; changing the note keeps the tick; `updated_by` /
  `updated_at` move with a tick too; the wallet-below-zero row (entry 0)
  can be cleared like any other, and its tick stays when the wallet
  dips below zero again later. New strings "Cleared", "Add a note first",
  "Hide cleared rows", "Could not save." - in all six catalogues (gettext
  had guessed the old note strings for two of them). Tests in `test_gm_transactions.py`
  (`TestGmNotes`) and `test_bots_gm.py` (`TestGmTab`), all seven
  sabotages caught. Not looked at in a browser.

## Decisions of the 2026-11-04 sessions

Payment amounts in the sum badge's tooltip (0.4.18) - the user's choices
unless marked:

- **The five highest**, highest first; **stored on the row** (migration
  0033), not read from the journal at render - the overview stays
  journal-free.
- **Beyond five: the count plus "the 5 largest"** (chosen over one line
  per amount with "and n more").
- Claude's calls: amounts joined by " / " in one native `title`; each
  transfer cut to whole ISK like `amount_paid`; written with the amount
  paid, so a check finding nothing keeps them; rows checked before 0.4.18
  keep the count-only tooltip until recalculated - no data migration;
  French with a space before the colon, as the rest of its catalogue.

Green for an exact payment among several (0.4.17):

- **User**: when at least one of several payments to a reason code is
  exactly the amount owed, colour the row green.
- Claude's calls: both figures turn green, as for an exact total; the
  flag is stored on the row, not worked out at render (the overview
  reads no journal); rows checked before 0.4.17 stay as they were until
  their next recalculation - no data migration, it would have to re-read
  the journal; without reason codes nothing changes (only an exact
  payment counts there anyway).

## Decisions of the 2026-11-02 session

GM Transactions on the bots pages (0.4.16) - the user's choices unless
marked:

- **Copy buttons**: on GM Transactions for the Character name only; on
  the bots pages for both Character and Main names.
- **Last login = the character's own** corptools `last_known_login`, not
  the account's newest; the column **after Age**.
- **Red rows by the GM page's rule**: a GM transaction in the stored
  report **or** a wallet below zero now.
- **The GM tab shows the whole account** (main plus alts), wallet-below-
  zero rows included.
- Claude's calls: the login is read at render, not stored by the job; the
  red row's reason as a native `title`; the GM tab ignores the month on
  screen; its notes are read only (edited on GM Transactions); every
  bots list gets the red rows, the audit tab included; the copy button
  sits in the same cell as the name, after the link.

## Decisions of the 2026-10-29 sessions

`gm_bots_access` (0.4.15) - the user's choices unless marked:

- **Name `gm_bots_access`**; it shows the bots and GM Transactions pages
  **with every function**, including **both Recalculate buttons**
  (which otherwise need `manage_settings`), and **nothing else**.
- Claude's calls: GM notes count as part of "editing GM transactions";
  the progress bar is shown (the buttons point at it) but only with the
  bots and GM runs - the tax runs list every corporation; such a user
  may dismiss those runs, not a tax run; the menu entry stays the app's
  one entry and the overview redirects to the bots page; no badge.

Alliance switch (0.4.14) - the user's choices unless marked:

- **On by default**; hides every character whose account has no
  character left in the alliance.
- **A dash (unknown) stays shown** - only a known "left" is hidden.
- Claude's calls: always shown above the counterparty boxes, even when
  no row would be hidden; client-side only, state not kept in the URL or
  storage; label "Only characters still in the Alliance with a Main or
  alt"; it combines with the boxes (a row must pass both).

Notes, whole ISK, column swap (0.4.13) - the user's choices unless marked:

- **A note per row**, not per character: each GM transaction its own;
  a character with two bookings has two notes.
- **Anyone with `admin_view` may write notes**, not only
  `manage_settings`.
- **160 characters**, popup with a text field, Save and Cancel; the
  stored note as the button's tooltip; the button second in the row.
- **"Corporations in the Alliance" before "Alliance"**; **ISK as whole
  numbers**.
- Claude's calls: rounded, not truncated (the user was told and may want
  truncation); the note searchable by the search box; empty saves delete;
  line breaks kept, control/format characters dropped; native `title`
  tooltip, no Bootstrap tooltip (would need `html: false` care and an
  init); the filled button (`btn-secondary`) marks a row with a note; no
  history of a note's edits, only `updated_by` of the last.

"In the Alliance" for the whole account (0.4.12) - the user's choices
unless marked:

- **A red exclamation mark only**, no tick any more and no distinction
  between "the character itself" and "another character of the main"; no
  tooltip naming which characters are in (offered, not chosen).
- **As of the GM job's run**, like 0.4.11, not live at page load.
- Claude's calls: "the main's characters" = every character owned by the
  same Alliance Auth user (`CharacterOwnership`), a main set or not; a
  character nobody owns stands for itself; one known character out and
  the rest unknown = out (empty), not a dash; the header gets a tooltip
  explaining the mark (new string); the visually hidden cell text stays
  "In the Alliance".

"In the Alliance" (0.4.11) - the user's choices unless marked:

- **As of the calculation**, i.e. the GM job's run, not the page load.
- **Two sources, the newer wins**: Alliance Auth's `EveCharacter.alliance_id`
  dated by `last_updated_affiliations`, against corptools'
  `CorporationHistory`, dated by the `start_date` of its last record.
- Claude's calls: "the alliance" = the configured `tax_alliances`; the
  history side checks the last record's Corporation against the
  Corporations **in those alliances today** (`EveCorporationInfo`), not
  `_alliance_corporation_ids` - a Corporation that left keeps its tax rows
  but its members count as out. A tie goes to Alliance Auth (it looked at
  or after the record's start); `last_updated_affiliations` None = the
  history decides; last record by `start_date`, then `record_id`, as in
  `_corporation_at`. Left = an empty cell, unknown (report before 0.4.11,
  character neither source knows) = a dash. The mark carries a visually
  hidden "In the Alliance" for screen readers; column not searchable.
- The column order and the removal of "Transaction for" came from an
  earlier session that left them uncommitted; they went into
  the same commit. Its reasons are in the CHANGELOG only.

## Decisions of the 2026-10-27 sessions

Recalculate buttons and step runs (0.4.10) - the user's choices unless
marked:

- **The jobs show in the existing bar above every page**, not on their
  own page; **step by step**; **every run however started** (button, tax
  task, settings change, first visit to a month); the button needs
  **`manage_settings`**.
- **"GM X" by its exact name** (the user's choice over "every counterparty
  starting with GM "): red, and the only ticked box when it occurs; without
  it every box is ticked as before.
- Claude's calls: the bots button recalculates the month the page shows
  (not the month field's unsubmitted value) and all four lists; a job
  already locked is not queued again and the button says "Already being
  calculated."; the page does not reload by itself - the bar offers it;
  GM steps are the journal search and "balances and ages" (the search is
  one query, so the bar stands still during it).

Counterparty fix (0.4.9):

- **User**: the filter offers only the GM / non-player side, never a
  character.
- Claude's calls: "player" = a name Alliance Auth has an `EveCharacter`
  for, not the ESI party ids; a booking between two registered characters
  goes to "No counterparty". Open: a character Alliance Auth does not know,
  named second and not the wallet owner, still shows as a box; so does the
  tail of a player name with " and " in it when it stands second
  (`_parties` splits at the last " and ").

GM Transactions additions (0.4.8) - the user's choices unless marked:

- **The age is computed by the GM job**, like the bots lists - as old as
  the job's last run. Claude's calls: stored as days, not text, so the
  unit is in the reader's language; a character gone below zero after the
  run, or a report stored before 0.4.8, shows a dash until the next run.
- **Counterparty = the text after the last " and " of the description**
  ("GM X", "EVE Central Bank", ...), not corptools'
  `first_party`/`second_party` (the user's choice over the ESI parties).
  Claude's calls: the boxes are read off the rows on the page; sorted by
  name ignoring case; one box "No counterparty" for wallets below zero
  and descriptions of another shape, last; with only one counterparty no
  filter at all; all ticked at first; client-side only, not in the URL.
- **"Corporation at the time" is a column of its own** (the user's choice
  over marking it in the existing columns). Claude's calls: read at
  render from the whole corporation history, inside the alliance or not;
  the tax calculation's rule (`_corporation_at`: the membership that
  started last at or before the transaction, a tie to the higher
  `record_id`); only the name is red, the dash is not.
- **The audit link** goes to `corptools:reactmain`, as on the character
  page; the whole name is the link (Claude's call).

The GM Transactions page (0.4.7) - the user's choices unless marked:

- **Own page in the navigation** (`admin_view`), not a bots tab.
- **Criteria: wallet balance below zero now** (corptools
  `CharacterAudit.balance`), **or a description starting with "GM ["**
  (case-sensitive), e.g. "GM [16519715] issued transaction between
  <character> and GM X" or "... and EVE Central Bank". Empty
  `context_id`/`context_id_type` was **dropped** - in the dev corp journal
  it matched 1702 of 13119 rows: market tax, broker fees, donations,
  clone fees.
- **The whole journal**, no month selector.
- **Computed by a job** to keep the page fast.
- Claude's calls: every character corptools has a journal for, not only
  the alliance's; the job stores the GM rows (and since 0.4.8 the ages),
  balances, mains and Corporations are read at render; "Corporations in the Alliance" =
  corporation history against today's alliance corps plus every corp with
  a `MonthlyTax` row (a corp that left still counts); "Transaction for" =
  text after " between " up to the last " and "; one row per transaction,
  characters only below zero after them, deepest first; lock
  `GM_REPORT_LOCK` (15 min) like the bots job; the page reloads every
  20 s while pending; DataTables, server order kept.

The audit tab sorting (0.4.7):

- **User**: groups always by main name; the columns sort inside the
  groups.
- Claude's calls: own JS (`eosTaxSortGroups`), not DataTables - AA ships
  no RowGroup extension and DataTables would scatter the groups; headings
  from `partials/sort-header.html`; the Main heading reverses the group
  order; badge columns sort via `data-order`; `age_days` added in
  `grouped()` (stored lists from before sort ages as unknown until
  recomputed). On narrow screens the Main column, and with it the group
  toggle, is hidden.

The audit tab (0.4.6) - the user's choices unless marked:

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

The bots job (0.4.6) - the user's choices unless marked:

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
- **Progress bar** of every recalculation, admins only (since 0.4.15
  also `gm_bots_access`, with the bots and GM runs alone), cache only, a
  finished run shows "Reload".
- Every group on the bots page has a heading, a group of one too. The
  average day divides by active days. `bot_clock_min_concentration`
  defaults to 12. The blacklist still gets rows from the task. A month
  with alliance rate 0 gets no row.

## The bots page

Five tabs (the GM Transactions page is a page of its own, not one of
them). The first four are readings of the same month that deliberately
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

0000000. **On deploying 0.4.24**: nothing to migrate or restart - only the
   catalogues changed. Open one page with the browser set to Simplified
   Chinese (overview, bots, settings): the Chinese has never been rendered
   or read by a native speaker. A Chinese-speaking member's corrections go
   straight into `locale/zh_Hans/LC_MESSAGES/django.po`.
000000. **On deploying 0.4.23: migration 0037** before the settings page
   or the bots page loads (both read `possibly_banned_min_days`); no
   Celery change. Then open "Possibly banned" once on production data:
   does it list the expected quiet characters, and how long does the
   fetch take (it reads every stored `BotReport` row of the four
   readings on each visit - fine for a few years of months; if it grows
   slow, that is the place to cache). Not looked at in a browser yet.
00000. **On deploying the in-game window button: migration 0036**, and
   check that the EVE developer application of the instance has
   `esi-ui.open_window.v1` (corptools asks for it too, so it probably
   has) - otherwise the `+` SSO round trip fails. Then pick a character,
   log it in to EVE and press one button: never tried against real ESI.
0000. **On deploying 0.4.21: migration 0035**, then restart gunicorn and
   every Celery worker (the model lost two columns, the task queues more).
   An instance that ran with one month switch off gets rows and badge
   counts for that month from the next run on. Watch the first runs: the
   task now also queues every unpaid row of three earlier months, and a
   row settled by a late payment should turn paid. A reason with two codes
   no longer counts - if a Corporation paid that way, it has to pay per
   code. Not looked at in a browser: the settings page without the
   "Months" heading.
000. **On deploying 0.4.19: migration 0034** before GM Transactions
   loads (it reads `GmNote.cleared`); no Celery change. Not looked at in
   a browser (the dev data has no GM row) - in production tick one row,
   empty its note, and try the switch.
00. **On deploying 0.4.18: migration 0033** before the overview loads
   (it reads `largest_payments` on every row), then restart the Celery
   workers (`set_corp_tax` takes a new keyword). The amounts appear only
   on months recalculated afterwards. Not looked at in a browser, only
   through the tests; check one tooltip in production (long amounts in
   a native tooltip, the Korean and French wording).
0. **On deploying 0.4.17: migration 0032**, then restart the Celery
   workers (`set_corp_tax` takes a new keyword). Older months show the
   new green only after a recalculation; not looked at in a browser -
   `aa_dev` has no row with an exact payment among several.
1. **On deploying: restart every Celery worker.** 0.4.10: both bots and
   GM tasks now take `run_id`; a worker on older code fails them with a
   TypeError and their run stands at "Waiting" on the bar for an hour.
   **0.4.10 has never run against a real worker** - after deploying, press
   both buttons once and watch the bar step through. 0.4.6/0.4.7 also
   needed migrations 0028 and 0029 and the restart - a worker started
   before does not know
   `run_update_bot_reports` or `run_update_gm_report`, and the bots tabs
   and the GM page would wait forever. Until the first job ran, they show
   "being calculated". Check the beat cadence of `run_update_alliance` in
   production: both are only as fresh as its last run ("computed … EVE"
   says when). **0.4.8 needs the restart too**: a worker on 0.4.7 code
   stores GM reports without ages, and the Age column stays all dashes.
   **0.4.11 the same**: a worker on older code stores no `in_alliance`,
   and the first column stays all dashes. **0.4.12 too**: a worker on
   0.4.11 code stores the character alone, and alts of members that left
   show no mark. After the restart press Recalculate on GM Transactions
   once. **0.4.13 needs migration 0030** before the page loads - it reads
   `GmNote` for every row.
2. **GM Transactions has never seen real data** (0.4.14: with the
   alliance switch on, check that the rows hidden are really the
   accounts that left) - `aa_dev` has 6
   character journal rows, no GM booking and no negative balance. After
   deploying: does the page list the expected characters, do the
   counterparty boxes read the names right (which counterparties really
   occur?), does "Corporation at the time" match, are the "In the
   Alliance" marks right (spot-check a character who left recently while
   an alt stayed, and one whose whole account left - is
   `last_updated_affiliations` set in production, or does the history
   always win?), and how long does the job's `description LIKE 'GM [%'` scan over
   the live character journal take (no index serves it)?
3. Not looked at in a browser yet, only through the tests: everything
   of 0.4.16 (copy buttons on the bots pages, red rows, the GM tab and
   its pending retry, the Last login column - the dev server at
   `127.0.0.1:8000` was not running); the
   Recalculate buttons and the step runs on the real pages (0.4.10 - only
   a static snapshot with a stubbed fetch was rendered, where the steps,
   badges and button message looked right); the "GM X" filter state
   (0.4.10); the GM page
   with real rows - its counterparty filter was clicked through on a
   rendered snapshot with hand-made rows (DataTables 2.3.8, works); the
   red "Corporation at the time" column and the audit link were not
   rendered at all. The audit tab on the real page (its sorting was clicked
   through on a rendered snapshot with hand-made rows only),
   the pending note with the 20 s retry (fetched tabs) and the page reload
   (first tab), the "computed … EVE" lines. From earlier versions also not
   rendered yet: the read-only settings page with an `admin_view`-only
   user (0.4.5), the 0.4.4 template moves, the overview's four state links,
   the "Earned in total" tooltip and sum badge, the Paid tooltip, the
   overview columns "Characters without wallet audit", "Calculation time",
   "Amount paid in ISK" with its badges, and the "Payment differences"
   block on the settings page. One render with the seeded data before
   building on any of them.
4. **Known limitation of the stored bots lists**: names, mains and ages
   are taken when the job runs. A character moved to another main shows
   under the old one until the next run of that month; past months are
   only recomputed when a setting changes or someone asks after a
   fingerprint change. (The audit tab regroups live, so its mains are
   current.)
5. **Worth a look in production**: the footer of "Hours per day" splits
   its time into database and aggregation. If the ~30 s are mostly
   database, the query (grouping the whole month by character, day, hour
   and ref_type) may be worth an index or a rewrite - corptools' schema is
   not ours to change, so only the query.
6. On deploying 0.4.5: grant `eos_tax.manage_settings` to whoever changes
   the settings, or only superusers can. On deploying 0.4.15: migration
   0031, then grant `eos_tax.gm_bots_access` to the bot / GM hunters
   (a group or state in Alliance Auth). Not yet looked at in a browser
   with such a user - one render of the bots page and GM Transactions
   (navigation, buttons, bar) is still due.
7. After deploying 0.3.14/0.3.15, recalculate urex (your ex's) for every
   month it ran at 0% and check that "added" in the log holds only untaxed
   payouts - the matching key has never seen real member wallet data.
8. The affiliation filter (0.4.3) has never talked to the real ESI - check
   the log line "... has left this corporation since" after a
   recalculation; "ESI affiliation lookup failed" means everyone stayed
   listed.
9. Rows written before 0023/0024 show no characters and no calculation
   time until recalculated; rows paid before 0025 never get a "recorded
   as paid" time.

## State of the dev instance

- `eos_tax_uicharacter` (0036) is empty: nobody has picked an in-game
  character on the dev instance, and no `esi-ui.open_window.v1` token
  exists there that was taken for it.
- `possibly_banned_min_days` (0037) is at its default 30. "Possibly
  banned" is empty there: no listed character has a corptools login.
- Migrations 0001-0037 applied to `aa_dev`; both month switches were on
  before 0035 dropped them (`~/aa-dev/eos-tax-month-flags-before-0035.json`),
  so the dev instance behaves as before. Every `MonthlyTax` row has
  `exact_payment` False and `largest_payments` `[]` until recalculated. `eos_tax_gmnote` is empty.
  Nobody holds `gm_bots_access` there yet.
- `eos_tax_botreport` holds 8 rows from a trial run of the job (2026-09
  and 2026-10, all four tabs) - our own table, safe to overwrite or
  delete. They predate `age_days`, so the audit tab sorts their ages as
  unknown until recomputed. In the dev data nobody listed has a corptools
  audit, so the audit tab lists everyone as "no audit".
- `eos_tax_gmreport` is empty - the GM job never ran against `aa_dev`;
  the first visit to the page queues it. It would find nothing: no GM
  booking, no negative balance in the dev data.
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
in `manage.py shell` first, or the snapshot shows "being calculated". The
GM page the same with `store_gm_report()`.

For a whole page with hand-made rows (used for the GM counterparty
filter): `render(request, "eos_tax/gm-transactions.html", context)` in a
script fed to `manage.py shell`, with a `RequestFactory` request whose
`user` is `kaskade`, a `SessionStore()` session and `FallbackStorage`
messages; strip `integrity`/`crossorigin`, symlink `static` to
`/var/www/myauth/static` next to the file and serve the folder with
`python3 -m http.server`. Writes nothing to `aa_dev`. The dev static
files are not hashed, so the `?v=` trick needs the plain name.

For a fragment's JavaScript alone (the audit tab's sorting), quicker:
`render_to_string` the partial with hand-made rows, wrap it in a page with
the script inlined, and serve it with `python3 -m http.server` from WSL.
The browser pane opens a `file://` page only as a static snapshot - no
script runs there.

## Traps recent sessions cost time on

- **Saving an esi `Token` moves the character's ownership** to the token's
  user (Alliance Auth's signal). A test token for another user's character
  silently makes it yours - use an unsaved stand-in where ownership is
  what the test is about.
- **`UiCharacter.character_id` is the `EveCharacter` pk**, not the EVE id.
  Compare with `character__character_id`; the dropdown's "selected" was
  lost that way once.
- **AA's `open_api_provider` only knows its own operation list** - any
  other ESI call needs `eos_tax.providers.esi` with the operation added to
  its `operations`.

- **`makemessages` from `eos_tax/` goes through the instance's
  `manage.py` by path**: `cd eos_tax && ~/aa-dev/venv/bin/python
  ~/aa-dev/working/myauth/manage.py makemessages -l de -l es -l fr_FR
  -l it_IT -l ko_KR -l ru -l zh_Hans`, the same for `compilemessages`. A
  removed string turns into `#~` in all seven; the `#:` line shifts make the diff
  look large.
- **`overdue_jobs` reads `MonthlyTax` with `payed=False`**: a test that
  counts what `run_update_alliance` queues must not leave an unpaid row of
  an earlier month lying around, or it finds an extra job.
- **Script tests find the first match in the whole file.**
  `test_script_should_start_from_the_ticked_boxes` compared the first
  `addEventListener("change"` with the first `dataTable.draw();` and broke
  when `setUpCleared` (above the page start) got a listener - it now
  searches from `DOMContentLoaded` on. A new helper function above the
  page start can trip the other string-order tests the same way.
- **A quoted bash heredoc still broke a patch script** in the Bash tool
  (2026-11-06) - write patch scripts with the Write tool, always.

- **`payments._corporation_at` bisects with a float sentinel**
  (`(moment, inf)`): its periods must be `(start, corporation_id)` pairs.
  A name as second element raises a TypeError the moment two records
  start in the same second - look names up afterwards.
- **A DataTables `columns` option shorter or longer than the header
  breaks the table.** `test_script_should_describe_every_column` counts
  both on the GM page; a new column needs its entry in
  `gm-transactions.js`.

- **The Bash tool's `python3` is the Windows Store stub**, but `python`
  worked on 2026-10-29 and patched files through `\\wsl.localhost`.
  Anything that needs Django runs in WSL.
- **A test that a guard was right needs the guarded case to exist.** The
  menu badge test passed against its sabotage because nothing was due -
  give it a due row first (`mid_month`, `last_month`, `create_tax_row`).
- **`pkill -f <pattern>` inside `wsl.exe ... bash -lc '...'` kills its own
  shell** - the pattern is in that shell's command line, so everything
  after it never runs (exit 15). Kill by PID, or run it in a call of its
  own.
- **The bots and GM views need stored lists in tests.** `EosTaxTestCase`
  patches `run_update_bot_reports.delay` and `run_update_gm_report.delay`
  to run the job in place. A test about the
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
  put "Wallet audit" on "no audit", for 0.4.7 "Taxation" on "GM
  Transactions" and "Duration" on "Description", in all six catalogues;
  for 0.4.10 "Back to the list" on "Bots lists".
- **Every bots or GM page visit in a test registers a progress run** now
  (the view queues the job, and queueing registers the run). A test that
  counts `progress.get_runs()` must `cache.clear()` first, as
  `ProgressTestCase` does.
- **`create_user` per login fails on the second call** with a duplicate
  username - make the users once in `setUp` and `force_login` them.
- **`eos-test ... | tail` can cut off the result line**: stderr and
  stdout interleave, and in a short run (the translation tag) the
  `Ran`/`OK` lines came before "Found 15 test(s)" and fell out of
  `tail -5`. Grep for `^Ran|^OK|^FAILED` instead.
- **A stale `.git/CLAUDE_COMMIT_MSG` gets committed** (0.4.12, 0.4.15
  and 0.4.16 commits). The Write tool needs a Read before it may
  overwrite the file, and a failed Write in the same batch as the
  `git commit` commits the old message. `rm` the file after each
  commit, commit in a later call, check `git log -1` before pushing.
- **A test that a row is red on a bots tab needs the character on that
  tab.** The rhythm and clock tabs did not list the seeded ratter, so
  the first red-row tests passed against nothing; `test_bots_gm.py`
  lowers their thresholds in `setUp` and adds a second character.
- **A markup change reaches tests in other modules**: the `ps-4` class
  assertions sat in `test_bots.py` and `test_bot_signals.py`, which
  feature work did not run - grep the tests for the old markup.
- **`/push` cannot be started by Claude** (the skill is user-only); the
  user types it.
- **A fix with two guards needs a sabotage of both at once**, and **a
  sabotage that does not compile proves nothing** - replace with valid
  code.
- **`eos-test` takes one test label** - run one module per call.
- **Someone else may migrate and start Celery meanwhile.** Check
  `showmigrations` before migrating, and leave a worker on someone's
  terminal alone.
- **`compilemessages` and `makemessages` run from `eos_tax/`**, not from
  `myauth/`, and `makemessages` with the locales named
  (`-l de -l es -l fr_FR -l it_IT -l ko_KR -l ru -l zh_Hans`); `-a` did
  nothing.
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
- **corptools' `CorporationHistory` always has an `EveCharacter`** (it
  hangs off `CharacterAudit`), so a lookup that starts from
  `EveCharacter` misses no history - a fallback loop for "history
  without a character" is dead code.
- **The GM progress step `characters` is still labelled "Wallet balances
  and ages"** (`partials/progress.html`), although it now also works out
  the alliance membership of whole accounts. Left so on purpose to avoid
  a string change.
- **The Edit tool refuses a file seen only through `grep`/`sed` in Bash** -
  Read it (a few lines are enough) before the first Edit, or every edit
  of a batch fails.
