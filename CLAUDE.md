# Working on eos-tax

Alliance PvE tax tracking for Alliance Auth 5.2, reading the corporation
wallet journals that corptools collects. `README.md` says what the app does;
this file says how to work on it; `docs/HANDOVER.md` says where the work
currently stands.

## Where things are

| | |
|---|---|
| This app | `~/aa-dev/working/eos-tax/eos_tax` |
| Alliance Auth instance | `~/aa-dev/working/myauth` (has `manage.py`) |
| Alliance Auth source | `~/aa-dev/working/allianceauth` |
| Virtualenv | `~/aa-dev/venv` |
| Collected static | `/var/www/myauth/static` |
| Dev server | `http://127.0.0.1:8000` |

Everything runs from the Alliance Auth instance, not from the app directory:

```bash
cd ~/aa-dev/working/myauth
```

## Commands

```bash
~/aa-dev/venv/bin/python manage.py test eos_tax --parallel 4 --noinput
```

`myauth`'s own console log handler is set to `DEBUG` (useful for watching the
dev server live), which turns that command into mostly
`allianceauth.hooks`/`signals`/`authentication` noise - the bulk of what a
session reads back for a run that only needs `OK` or one traceback.
`~/bin/eos-test` wraps it and drops exactly the DEBUG/INFO lines the console
handler adds, nothing else - a real traceback, `WARNING` or `ERROR` still
comes through:

```bash
eos-test                          # eos_tax, whole suite, quiet
eos-test eos_tax.tests.test_bots  # one module
eos-test eos_tax --parallel 4     # extra args pass straight through
```

It lives in `~/bin`, not in this repo - personal tooling for whichever
environment is running it, not part of the app.

```bash
~/aa-dev/venv/bin/python manage.py makemigrations eos_tax
```

```bash
~/aa-dev/venv/bin/python manage.py makemigrations --check --dry-run
```

```bash
~/aa-dev/venv/bin/python manage.py collectstatic --noinput
```

`--keepdb` is faster but does not migrate the parallel clone databases. After
a new migration it fails with an unpicklable traceback that says nothing -
use `--noinput` once, then `--keepdb` again.

## Release

Read by the personal skills `/commit` and `/push`; the same shape in every
app. Commands run from `~/aa-dev/working/myauth`. Translation tests carry
`@tag("translations")`: between commits the catalogues describe the last
commit, so the suite leaves them out.

- App: `eos_tax`
- Version file: `eos_tax/__init__.py`
- Changelog section: `[Unreleased]`
- Tests while working: `eos-test eos_tax.tests.<module>`
- Suite without translation tests: `eos-test eos_tax --parallel 4 --exclude-tag translations`
- Checks: `~/aa-dev/venv/bin/python manage.py makemigrations eos_tax --check --dry-run`
- Translations: as in `## Translations` - makemessages, fill every `.po`,
  `msgfmt --check`, compilemessages, `.mo` newer than `.po`
- Translation tests: `eos-test eos_tax --tag translations`

## The database is irreplaceable

`aa_dev` holds ESI-pulled corptools data that cannot be fetched again. There
is no binary log and there are no dumps.

- **Never** delete with a range filter on `EveCorporationInfo`. The cascade
  takes the wallet journal with it.
- Address rows by explicit id lists, and write the previous values out first.
- corptools and other foreign apps: read their models, never change their
  schema or their rows beyond what a seed of our own created.

## Code

Comments say **why**, not what. A comment that restates the line is noise; a
comment that names the fault the line prevents is the reason somebody will not
reintroduce it. That is the house style throughout this app - match it.

English everywhere in the code, including comments and docstrings.

Templates use the Alliance Auth standard style unchanged: its Bootstrap 5
classes, its bundles (`bundles/chart-js.html`, `datatables-2-js-bs5.html`),
`{% load sri %}` with `{% sri_static %}` for our own scripts. No custom theme,
no overriding of AA's own look. Prefer an AA or corptools pattern over
inventing one.

CSS lives in `eos_tax/static/eos_tax/css/eos_tax.css`, loaded by `base.html`;
a page adds its own bundle CSS in `{% block eos_tax_css %}`, never by
overriding `extra_css`, which would drop the stylesheet. No `<style>` blocks.

JavaScript lives in `eos_tax/static/eos_tax/js/`, never inline in a template -
`sri_static` cannot hash inline code, and `collectstatic` has to see the file.
Run `collectstatic` after every change to it.

## Tests

Every change gets a test, and every new test gets checked against the broken
version: put the fault back, run the test, confirm it fails, restore the file
and compare its checksum. A test that passes against the broken code tests
nothing. Several tests in this suite only exist because that step caught them
passing for the wrong reason.

Fixtures live in `eos_tax/tests/factories.py`, not in another test module;
page helpers (`read_static`, `read_stylesheet`, `json_script`,
`table_body`) in `eos_tax/tests/base.py`. Assert a Corporation name against
`table_body(response)`, never the whole page: Alliance Auth's sidebar prints
the logged in user's own Corporation before the content.
`settings_numbers()` builds the numeric part of a settings POST from the model
itself, so a new threshold does not silently invalidate every settings test.

Private helpers with arithmetic in them (`_longest_run`, `_typical_hour`,
`_purged_for`) are tested directly with hand-built values. A few numbers decide
their behaviour, and a database round trip only obscures which.

## Payments

A row once marked paid is never unmarked - not by a recalculation, not by
the task, not by any other write. `set_corp_tax` only ever adds the flag;
keep it that way, `TestPaidIsNeverTakenBack` guards it.

## Translations

Six catalogues: `de`, `es`, `fr_FR`, `it_IT`, `ko_KR`, `ru`. They are only
touched **at a commit** - see below. Everything else stays English.

- EVE jargon stays English in every language: Corporation, Alliance, Character,
  Main, bounty, wallet, Reason, ratter, ESS. `test_translations` enforces it.
  In the English source they are lower case in running text ("the rest of
  their corporation") and capitalised in headings, tab names and column
  titles.
- A `#, fuzzy` entry is **not compiled by msgfmt**. gettext guesses a fuzzy
  translation from the nearest old entry and guesses wrong nearly every time,
  so an unreviewed fuzzy entry ships as English without a warning. Read every
  one; do not trust the suggestion.
- After `compilemessages`, check that the `.mo` files are actually newer
  than their `.po`. It is easy to chain the command behind something that
  exits non-zero - `grep -c` returns 1 when it counts none - and then it never
  runs, silently. `test_compiled_catalogue_should_match_its_source` catches
  it; let it.
- Filling in an empty `msgstr` with a script rather than the Edit tool has
  corrupted a `.po` file before - the `msgid` line vanished, leaving a bare
  quoted string that `msgfmt` refuses to compile. `msgfmt --check -o /dev/null
  <file>` right after any bulk edit catches it while it is still one file to
  revert instead of six; the Edit tool alone has not needed it yet.
- Plural forms: de/es/fr/it 2, ko 1, ru 3.
- Korean: never write a bare `%` that the msgid does not have - msgfmt rejects
  it as a broken format string.
- xgettext reads the source, it does not run it, and it does not descend into
  an f-string interpolation. Bind a translated unit to a local before building
  the string, or it never reaches a catalogue.
- `makemessages` without extra flags. `--no-location` strips every `#:`
  line-number comment from all six catalogues at once - a diff of ~2000 lines
  for a one-string change, and it did not shrink again on the next plain run
  because the flag is not sticky. If that happens, `git checkout` the `.po`
  files and rerun without it.

## Committing

Commits and pushes only go through the user's personal skills `/commit`
and `/push`, never unasked; both read `## Release` above. While working on
a feature, run only the affected test modules - the full suite runs at
`/commit`.

The `CHANGELOG.md` is written along with every change, unasked. An entry says
what was wrong and why the fix is the fix, in the same voice as the rest of the
file.

## Editing files

Write patch scripts with the Write tool and run them by path. Do not build them
with shell heredocs: an apostrophe in `Corporation's` or a backtick in a
CHANGELOG entry gets executed by bash before Python ever sees the text, and it
corrupted a file that way once.

Every patch script asserts its anchor occurs exactly once before it replaces
anything, and prints what it changed.

For a small, unambiguous change the Edit tool is one step instead of two - use
it. The script is for multi-site edits and for anything with tricky quoting.

## Keeping a session cheap

Every request re-sends the whole conversation, so a long session costs several
times what the same work costs in a fresh one. Measured in this project: 72k
tokens per request at the start of a session, 900k before compaction.

- One session per topic. Start a new one when the subject changes.
- Run the affected test module while iterating; the full suite runs at
  `/commit`.
- Bundle the sabotage checks into one run per feature rather than per line.
- Take a browser screenshot only when something visible changed.
