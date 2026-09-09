# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

### Added

### Changed

### Fixed

## [0.2.0] - 2026-09-09

### Added

- Settings page. The configuration moved out of `local.py` into the database and
  is edited in the app. Migration `0005` reads the existing `TAX_*` values once
  and carries them over, so an upgrade keeps behaving as before.
- Tax rate schedule. Entries say *from this month on, the rate is X*, open
  ended, so a change can be entered months ahead. The newest entry that is not
  in the future applies.
- Statistics page. Tax per Corporation over a year, either as a trend line or as
  the share of a single month. The legend doubles as a table and its checkboxes
  switch Corporations on and off. Beyond eight Corporations the line style
  carries part of the identity.
- Bots page. Characters whose taxed income looks automated: more than *X*
  different hours of a day, on more than *Y* days of the month, both thresholds
  configurable. Each character is listed with its main. When nothing crosses the
  thresholds the ten longest days of the month are shown instead. A footer
  reports what the evaluation cost, so a slow-down becomes visible before it
  turns into a timeout.
- Statistics: a minimum share in percent, default 2. Corporations below it fold
  into one series or slice. Measured against the live August figures that draws
  twelve of 35 Corporations and still covers 89 percent of the tax. A percentage
  survives changing ISK magnitudes, an absolute amount would not.
- Statistics: a footer with the figures behind the chart - Corporations drawn of
  the total, the share of tax covered, gross PvE income and tax, the last two
  abbreviated to billions with a B.
- Navigation bar with Overview, Statistics, Bots and Settings. The admin pages
  are not offered without `admin_view`.
- Overview shows the applied alliance tax rate as its own column, between the
  ingame corp tax and the amount owed. The rate that produced the amount was
  invisible, so two months at different rates looked like a miscalculation.
  Rows written before the rate was stored per row fall back to the schedule.
- The payment reason on the overview has a copy button. It has to reach the
  ingame transfer character for character, and Clipboard.js is already an
  Alliance Auth bundle. A button rather than the SRP page's icon: the
  `cursor-pointer` class it hangs on is not defined anywhere in Alliance Auth,
  while a button brings the pointer, focus and Enter for free.
- Overview table is sortable per column and searchable by Corporation.
- The alliance tax rate that was applied is stored per `MonthlyTax` row, so a
  later rate change does not rewrite what past months were owed.
- Translations for German, Spanish, French, Italian, Korean and Russian. EVE
  terms stay in English. Only the German catalogue has been reviewed by a native
  speaker.
- Test suite with 139 tests covering access, page content, markup, the
  configuration, bot detection and the translation catalogues, including a check
  that every compiled catalogue matches its source.

### Changed

- The configuration is read where it is used instead of at import time. An edit
  now takes effect without restarting gunicorn and every celery worker.
- Tax rates are entered as percentages instead of fractions. Storage is
  unchanged, the conversion happens in the form.
- Exactly one holding Corporation can be configured; it used to be a list.
  Migration `0008` keeps the entry with the lowest id and reports the rest.
- Statistics and Settings require `admin_view`.
- Overview template rebuilt for Bootstrap 5. It still carried Bootstrap 3 markup
  that no longer had any effect.
- Performance, first pass: the corporation list is fetched in one query instead
  of one per Corporation; journal queries use a half open date range instead of
  `date__year` plus `date__month`, which no index can serve; payment matching
  runs as one query with `exists()` and a date bound instead of two sequential
  full scans; `MonthlyTax` gained an index on the period and a uniqueness
  constraint per Corporation and month; the fallback tax rate is resolved once
  per month instead of once per row. Measured at 1000 characters and 866,000
  journal rows the bot evaluation went from 11.8 s to 4.1 s.
- Statistics formats ISK with dots, the way the overview always has.
  Intl.NumberFormat followed the viewer's locale and printed commas on an
  English browser, so the two pages disagreed about the same figure.
- README rewritten. It documented `local.py` settings that no longer have any
  effect, and its feature sections were empty.

### Fixed

- The `payed` flag was dropped when a monthly row was created for the first
  time, so a freshly recorded month always read as unpaid even when a payment
  had been found.
- `overall_ratted` could be unbound or carry the previous iteration's value in
  `update_corp`.
- Overview sorting never chained. Four `sorted()` calls each worked on the
  original list, so only the last key had any effect.
- Numeric sort values in the overview are no longer localised. A German locale
  rendered the tax rate as `10,0`, which the table then sorted as text.
- The Corporation search on the overview matched nothing. Two overlapping
  DataTables definitions made every column unsearchable.
- Multi line `{# #}` template comments were rendered as visible text. Django
  only treats single line comments that way.
- Tests no longer leak the configuration singleton between cases. django-solo
  caches it in the backend named by `SOLO_CACHE`; a `TestCase` rolls its
  transaction back but not the cache, so a configuration saved in one test
  survived into the next and pointed at a Corporation that no longer existed.
- The DataTables assertion pinned the unhashed file name and broke once the
  static manifest was in place. It checks the versioned path instead.
- The uniqueness constraint moved out of migration `0009` into `0010`, with a
  check in front of it. MariaDB cannot roll DDL back, so adding the index and
  the constraint together left the index behind when the constraint hit
  duplicate rows - the migration was not recorded and the retry then died on
  "Duplicate key name" until someone dropped the index by hand. One schema
  change per migration makes the retry work, and the check names every
  offending Corporation and month instead of letting the database name one.
- Migration `0005` crashed instead of reporting what it could not link. It read
  the field name off a many-to-many manager, which carries no `field`
  attribute, so any alliance or Corporation unknown to Alliance Auth aborted
  the migration - the warning path was the one path never exercised.
- `update_corp` raised `AttributeError` for a Corporation Alliance Auth does not
  know.
- `update_corp` ran once per holding Corporation with identical arguments.
- The percentage in the overview title is rounded instead of truncated. `int()`
  turned 29 percent into 28.

### Removed

- The `TAX_ALLIANCES`, `TAX_CORPORATIONS`, `CORPORATION_BLACKLIST`, `TAX_RATE`,
  `TAX_TYPES`, `USE_REASON`, `LAST_MONTH` and `CURRENT_MONTH` settings are no
  longer read from `local.py`. They are taken over once by migration `0005` and
  can then be deleted from the file.
