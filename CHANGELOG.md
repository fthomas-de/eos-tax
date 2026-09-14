# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [0.3.0] - 2026-09-14

### Added

- `docs/HANDOVER.md` says where the work currently stands - release state,
  the two things about the bots page that are not obvious from the code, the
  seeded test data and how to remove it, and how to look at a page without
  logging in through EVE SSO. It says outright that it goes stale and that the
  code wins any disagreement.
- `CLAUDE.md` collects what working on this app has taught: where the
  instance and the virtualenv live, the commands, that `--keepdb` does not
  migrate the parallel clones, that the dev database cannot be refetched, the
  comment style, the rule that every new test is checked against the broken
  version, the six catalogues and the fuzzy-entry trap, and that the user
  commits. It was scattered across a working session before, which meant it
  was lost the moment that session ended.
- The two Corporation comparisons leave the characters they already call bots
  out of the yardstick. A script with volume is part of its own Corporation's
  day, and that Corporation is what everybody there is measured against - so
  the loudest one in a Corporation makes every other member look ordinary,
  itself included. Moving one seeded character into a real Corporation cost
  every other member of it about fifteen percentage points, which is how the
  fault was found. The reading runs twice now: once to see who is flat, once
  against what is left without them. In the journal that lifted the flagged
  characters from 25-59 to 50-83 points apart.
- Two passes and not a fixed point, on purpose: taking the flat characters out
  makes the Corporation look more concentrated, which flags more characters,
  which flattens it further. Where that ends is a property of the iteration
  and not of the month. A Corporation that would fall under its own floor once
  the flagged are removed keeps the plain yardstick - losing its members from
  the reading altogether would hide findings, which is the opposite of the
  point. Both readings can be switched back to the plain yardstick on the
  settings page, and the tab says how many characters were left out of it.
- The character page carries a dropdown beside the name with the main's other
  characters, each with the assessment it was given, so a family can be walked
  through without going back to the list every time. It costs nothing: the
  page does not work the grouping out for itself - that would mean a second
  walk over the whole month for the whole alliance, which is exactly the cost
  the tabs were split up to avoid - it takes the grouping the list the reader
  clicked through from was already showing. Opened cold, from the search box
  or a bookmark, there is no grouping to take and no dropdown, and a grouping
  from another month is ignored rather than shown as if it were current. The
  dropdown names which of the four readings the assessments came from, because
  the readings disagree on purpose and a badge without its reading would be a
  verdict from nowhere.
- The two Corporation comparisons list from a threshold now instead of
  ranking everybody. They deliberately had no cut-off - there is no number
  that separates a night shift worker from a script - but the result was that
  five of the ten shown groups were entirely green: the ranking carried the
  information, the colour said "nothing here", and both filled the same table.
  The runs tab already had the answer, so the two follow it: a threshold, and
  the largest values of the month when nobody reaches it, because an empty
  table says the threshold was not met without saying by how much. The
  defaults are argued rather than picked - ten percentage points sits in the
  middle of the gap the journal actually shows between the concentrated
  characters and the flat ones, and four hours is a third of the twelve hour
  scale, which is where the colouring stops calling a distance unremarkable.
- Both readings hand over what they measured as well as what they listed, so
  "not measurable" and "measured and ordinary" stay different answers. The
  footer says which of the two the table is showing.
- The rule the whole first tab rests on is a setting as well: how many entries
  of the same taxed type an hour needs before it counts as active. It decides
  what an active hour is before either of the other two thresholds counts
  anything, and it was the one number on that page nobody could change or even
  see - it appeared only in the sentence above the matrix on a Character page.
- All four bot readings have their thresholds on the settings page, and the
  page is cut into the chapters the app is cut into: one per page of the
  navigation, one sub-chapter per tab, so a knob is looked up where the thing
  it changes is looked at. Eight new settings, and the two run thresholds
  reach the page at all for the first time - they existed on the model and
  were only reachable through the Django admin.
- The thresholds are kept apart per reading even where two of the numbers
  agree today. "Enough payouts to describe a day" and "enough payouts to place
  the middle of a day" are different questions that happen to have the same
  answer at the moment, and one shared field would force whoever tunes one to
  accept the other. The four readings are meant to disagree; shared thresholds
  would tie them back together.
- Each tab prints the settings it was read with. Two already did. A surprising
  list on the other two could not be argued with, because the reader had no
  way to tell a real finding from a threshold somebody had moved.
- The settings page is rendered field by field rather than dumped in one tag,
  which is what allows the grouping - and makes a forgotten field invisible
  rather than broken, since the form still requires it and every save fails
  validation instead. A test walks the form's own field list against the
  rendered page, so the next field cannot be quietly left off.
- Tests for the write path. `update_corp` turns a month of journal entries
  into the row the overview shows, and `corp_has_payed` decides whether that
  row counts as settled - between them the only place the app produces a
  number, and neither had a single test. Twenty cases now cover them: the
  month boundaries as a half open range, the December rollover, which
  `ref_type`s count, which Corporation's entries count, a second run updating
  rather than duplicating, both signs of a payment, the exact-amount rule
  without a Reason code against the at-least rule with one, and the rate
  stored on the row winning over today's configured rate - which is the
  promise that field exists for. Each was checked against a broken copy of the
  code it covers, so none of them can pass for the wrong reason.
- The subtraction that leaves a Character out of their own Corporation's
  baseline is written once instead of three times. All three agreed, which is
  why it was worth collapsing now rather than later: the next change would
  have touched one of them, and nothing would have failed until a chart and
  its own summary line quietly disagreed.
- The Corporation's busy hours are shaded behind the bars rather than painted
  onto them. Colour was carrying two meanings at once - which series a bar
  belongs to, and whether its hour is inside the window - and Chart.js builds
  a legend swatch from the first entry of a colour array, so a Character whose
  first hour fell outside the window got a legend in one colour and most of
  its bars in another. The band also shows what the old version could not: an
  hour where the Character works and the Corporation does not is a bar without
  a band, and the reverse is a band without a bar.
- Each detection has a detail reading of its own, and the Character page shows
  all three beside the matrix it already had - one tab each, fetched when
  opened. The runs reading draws a point per payout with the longest run
  picked out, so an uninterrupted stretch is a vertical line rather than a
  number. The Corporation comparison draws the Character's hours against the
  rest of their Corporation's in shares, since in counts one Character against
  a Corporation is a flat line along the bottom. The clock comparison is drawn
  round a clock face: on a straight axis 23:00 and 01:00 sit at opposite ends
  while being an hour apart.
  All three come from the same functions the lists use, including the baseline
  that leaves the Character out of their own Corporation - a detail page
  disagreeing with the list it was opened from would be worse than none.
- All four bots tabs list one row per main rather than one per Character, and
  say how many of that main's Characters are on the list - one person running
  five accounts is a different finding from five people. A Character Alliance
  Auth does not know forms a group of its own instead of joining an unknown
  bucket, because burying an unregistered Character is the opposite of useful.
  A group of one is printed without a heading; the heading would be noise.
  The main also gets its own column, which is what answers the question for
  the groups that have no heading.
- Characters inside a group are indented under its heading, so a group of
  several is told apart from a row standing on its own at a glance. A group of
  one has no heading and its row stays at the left edge with everything else.
- Only the ten most notable groups are shown, and the footer says how many
  were left out. The lists are ordered by how far out of the ordinary a row
  is, and past the first handful the reader is looking at ordinary people.
- The hour thresholds tab gained the same colour band as the other three,
  measured against the configured days-per-month rather than an absolute.
- `level_for` and `grouped` moved to `db/shared.py`, which is the one module
  the other db modules may import: two of the four areas need them now.
- Times on the new tabs are written the way a clock and a stopwatch write
  them. A time of day was printed as `14.6` and a length as `4.7`; they are
  now `14:39` and `4 h 40 min`, units included. A run shows the span it
  covered as well as how long it lasted, with the date printed once when it
  stayed inside a day and twice when it crossed midnight - which is itself
  worth seeing.
- Two columns in the same table were both headed `Corporation`, once for the
  name and once for the figure being compared against. They now say which is
  which, and every counted figure in the footers uses a plural rule instead
  of reading `1 interruptions allowed`.
- Each row carries how far out of the ordinary it is - green, amber or red,
  always with the word beside the colour. The bands are relative to something
  rather than absolute: a run to the threshold in the settings, a flat day to
  how flat a day can possibly get, a clock offset to the twelve hours that are
  the furthest two times of day can be apart. Reaching the threshold is what
  makes a run strong, so the fallback list - which is made of runs that did
  not reach it - no longer contradicts the sentence printed above it.
- Three more readings of the month on the Bots page, as tabs beside the hour
  thresholds. They disagree with each other by design: a Character at the top
  of one can be absent from the next, and that is the information. Each is
  fetched when its tab is opened rather than computed on every visit.
  *Unbroken runs* counts consecutive payouts. The thresholds aggregate to hour
  buckets and throw the minute away, which is where the evidence is - the game
  pays about every twenty minutes, so an uninterrupted stretch is a chain and
  nothing else is. It is also the only reading that ignores *when* somebody
  plays, which matters for an alliance holding Chinese, American, European and
  Russian groups at once.
  *Against the Corporation* and *Off the Corporation clock* measure a
  Character against their own Corporation rather than against an absolute,
  for the same reason: the alliance's own day is flat across those timezones,
  so a script would look ordinary against it, while a Corporation usually sits
  in one timezone - one in the journal puts 78 percent of its payouts into
  eight hours.
  Both are rankings and carry no threshold, because no number separates a
  night shift from a script; each row shows the Corporation's own figure
  beside the Character's.
- Migration 0013 adds the two settings the run tab needs: how long a run must
  be, and how many interruptions it may contain. The second one exists because
  a daily downtime would otherwise cut every long night into two short ones.
  It counts interruptions rather than naming a time - the journal cannot say
  when the downtime is, since its quietest window is one European Corporation
  asleep. A break past an hour ends a run whatever the allowance says, or one
  allowance would weld a morning and an evening into a twelve hour run.
- Migration 0012 records the longer Match by Reason help text. State only -
  `sqlmigrate` reports it as a no-op, since help_text is not stored in the
  database - so it locks nothing and rewrites no table however large the
  journal behind it is.
- A test that fails when a model change has no migration. The one that got
  through was that help text: it produces no SQL, so nothing broke and
  nothing complained until `migrate` reported "No migrations to apply" and
  warned about unrecorded changes in the same breath.
- Test suite grown to 369 tests.
- The time units in a duration were never extractable. `format_duration`
  called gettext from inside the f-string it was building, which Python runs
  happily - but xgettext reads the source instead of running it and does not
  descend into an interpolation, so `h` and `min` never reached a catalogue
  and would have stayed English in all six languages for good.

### Changed

- The app's JavaScript lives in `eos_tax/static/eos_tax/js/` and is loaded
  with `{% sri_static %}`, the way Alliance Auth loads `timerboard.js` and
  the rest of its own. `statistics.html` was 667 lines, 486 of them a single
  hand written script - more than every other template of the app put
  together, and the app had no `static/` directory at all. It is now 224
  lines, and the four scripts are four files. What that buys beyond length:
  in a template a Django error and a JavaScript error look the same.
- One way for a page to give its script the strings it needs. The view builds
  the dictionary, the page emits a single `json_script`, the file reads it -
  no inline copy to keep in step, and no global. Lazy translations survive
  the trip, so the strings arrive in the reader's language rather than the
  worker's. A test covers both ends of that seam, because renaming either one
  breaks the page in the browser while the response still renders.
- The colour work moved to `eos_tax/db/palette.py`: `_oklab`, `_distance`,
  `_cube_colours` and the rest of the palette maths, 151 lines that had
  nothing to do with tax sums, sitting in the module that computes them.
  `palette.py` deliberately imports no models, so it can be reasoned about on
  its own. `_colour_slots` stays with the statistics: it queries `MonthlyTax`
  and decides which Corporation gets which slot, which is allocation rather
  than colour. `db/statistics.py` is down from 245 lines to 106.
- The bots tests follow the three parts of `db/bots.py` that never call each
  other: detection stays in `test_bots.py`, the character's month moves to
  `test_bot_detail.py`, the name search to `test_bot_search.py`. 878 lines
  become 473, 228 and 125, with the shared fixtures in `factories.py`. The
  set of test names was compared before and after rather than the count.
- `TestPayable` and `TestOpenPaymentCount` moved from `test_views.py` to
  `test_payments.py`. Neither renders a page - one is a calendar rule, the
  other a query - and they only sat there because that file was where the
  payments code used to be tested.
- `db/tax_changes.py` was left alone deliberately. At 406 lines it is the
  largest module, but its twelve functions form one connected call graph:
  there is no seam to cut along, and a split would be a filename rather than
  a boundary. The same measurement is what justified splitting `db_connector`
  earlier, where the four areas called into each other exactly zero times.
- The Match by Reason setting says what it protects against. Without it a
  payment is recognised by its amount and nothing else - not by who sent it,
  not by which month it was for - so two Corporations owing the same sum, or
  one Corporation owing it twice, cannot be told apart and a single transfer
  settles both. That is inherent to matching on an amount; the Reason code
  carries `corporation/month/year`, which is what makes a payment
  identifiable. The help text and the README now say so rather than leaving
  it as a preference.
- Grammar and idiom across the five non-German catalogues. Russian carried
  several outright errors of case and government - `превысить` taking "this
  many days" instead of a number, `изменилась с ... на ...` where the verb
  wants `до`, `в N днях` which means "N days from now" rather than "on N
  days", and a genitive singular after a placeholder. Italian pluralised
  loanwords the same file kept invariable elsewhere and missed three
  elisions. Korean mixed two counting units and rendered "covered" as
  "reflected". Four languages called the busiest day the longest day in one
  place and the busiest in another. Spanish keeps `tasa` for the configured
  rate and `tipo` for the rate recovered from the data: that reads as an
  inconsistency and is not one, and Italian draws the same line with
  `aliquota` and `tasso`.
- Class level fixtures where nothing in the class changes them. Building two
  alliances, two Corporations, their audits, wallet divisions and names ran
  before each of some sixty tests; it now runs once per class. Classes where a
  test writes the configuration keep their per test setup, because objects
  shared across a class are a failure that does not announce itself. The
  suite runs 289 tests in the time 268 used to take, and was checked three
  times in shuffled order to make sure nothing leaks between tests.
- Seven tests were tightened to assertions that can fail. Each was the same
  mistake: `assertContains` takes a substring, and the substring was on the
  page for another reason - `data-order="1"` is the start of `data-order=
  "10.0"` in the next column, `Main` is in Alliance Auth's own menu on every
  page, `value="2"` is the start of the year `2026`, `eostax-zero` is also
  the quick filter button, and both chart names appear in a script block that
  renders whether or not there is a chart. One test claimed to cover the
  migration backfill while creating no row at all; it is renamed to what it
  actually checks, with a note pointing at where the real behaviour is
  covered.
- The fixtures live in `eos_tax/tests/factories.py`. Five test modules used to
  import `create_user` from `test_views`, which made one test module a library
  for the others; `create_tax_row` existed twice with different signatures,
  and building an alliance with a corporation in it was written out six times
  with the same ids declared four times over.
- Four tests that could not fail on their own were removed, and their covering
  tests say so in a docstring. Two more candidates survived the check: one
  asserts a count where the covering test only indexes the first element, and
  one turned out to be weak rather than duplicated and was tightened instead.
- The README gains a note on the manifest trap: Alliance Auth serves static
  files through a manifest, so a template naming a file `collectstatic` has
  not seen yet raises `ValueError` and the page 500s, with a message that
  does not mention the cause.
- The README documents Corp Tax Changes, which shipped without being listed,
  and no longer claims `Character` stays English - none of the seven
  catalogues does that; they translate it in prose and keep the column label
  English. It also gains a Development section: the suite needs a real
  Alliance Auth install, `--keepdb` is the difference between minutes and
  under a minute, and `--parallel 4` roughly halves the rest. More workers are
  not better - on twelve cores eight were slower than four, because the
  database is the bottleneck rather than the CPU.
- The heaviest fixtures write what they are proving rather than several times
  that. A plateau needs three payouts a day, not four; twenty entries in one
  hour show nothing three do not; and a cap is shown by one row past it, not
  five. The cap tests now name the limit instead of repeating the number.
- `db_connector` is now the package `eos_tax/db/`, one module per page:
  `payments`, `statistics`, `bots`, `tax_changes`, plus `shared` for the three
  helpers more than one of them needs. The four areas never called into each
  other, so the file had only grown by addition - every new page appended to
  the same file and every change touched something the other pages import.
  Nothing is re-exported from the package: an importer names the module it
  means, which is what keeps that from coming back. No behaviour changed; the
  definitions were compared against the previous file one by one.

### Removed

- `corp_tax_exists` and `get_alliance_name` are gone. Neither had a caller
  anywhere, not even a test, and `corp_tax_exists` returned the `MonthlyTax`
  class rather than the row its annotation promised. `get_bot_candidates` is
  gone too: its only four callers were tests, so they were exercising a
  wrapper no page takes, and they now go through `get_bot_report` the way the
  view does.

### Fixed

- Opening a Character from any of the four lists dropped the reader onto the
  matrix, whichever list they came from - the same fault the dropdown had, from
  the other direction. The list links keep the open tab now. Two of those links
  are out of reach of the tab event that rewrites them: a list fetched into a
  pane arrives after the event, and the tab that is already open when the page
  loads never fires one at all. Both are handled where they happen.
- The two Corporation comparisons were listing from thresholds that hid most of
  what they measured. Both were set before the yardstick stopped counting
  flagged characters, and that change moved every figure: the gap in the
  journal's own distribution now runs from 11 to 45 points rather than from
  -15 to 25. Ten points and four hours were cutting into the useful range
  rather than under it, so they are zero points and three hours - everything
  at all flatter than the rest of its Corporation, and everything the colouring
  does not already call unremarkable. Fourteen and nine rows where there were
  nine and seven.
- Opening a character page cold - from a bookmark or the search box - left no
  dropdown at all, because the grouping it is built from only exists when the
  reader came from a list. Alliance Auth knows who is on an account without
  touching the journal, so the jump list is always there now; only the
  assessments beside the names are missing, and the heading says so instead of
  naming a reading.
- Jumping to another character through that dropdown dropped the reader back
  onto the matrix. The dropdown exists to compare one reading across a main's
  characters, so that was two clicks per character with the second easy to
  forget. The open tab travels in the url now - which also makes the address
  worth copying and bookmarking - and the way back to the list keeps it too.
  The links are rewritten as the tab changes rather than when one is clicked,
  because a middle click never fires a click handler and a link whose
  behaviour depends on one is a link that lies.
- The Corporation comparison and the clock reading drew a Character against a
  copy of themselves when there was no Corporation left to compare against. A
  Corporation that is one person leaves nothing behind once that person's own
  payouts are taken out, and the fallback handed the Character's own day back
  as the Corporation's - two lines exactly on top of each other, which reads
  as perfect agreement with the Corporation. On the radar chart the two rings
  were literally one ring. The footer did say there was no yardstick, in small
  print, under a picture claiming the opposite. Both readings now send nothing
  for the Corporation, the chart leaves the series out, and the reason is
  stated above the chart rather than below it.
- The first tab's explanation sat above the tab strip on both bot pages, where
  it read as the heading of all four tabs while describing only itself - so
  somebody looking at unbroken runs was being told about hours per day, and
  the three other tabs looked as though nobody had bothered to explain them.
  It sits inside its own tab now, where the other three already had theirs.
- The clock reading took its Corporation middle out of the busy window helper,
  which computes that middle over every hour and ignores its own window
  entirely. It worked, but it made the clock depend on a setting it never
  reads. It asks for the middle directly now, and the two readings share no
  thresholds at all.
- A tick tolerance above the break ceiling is refused. The run walk asks "is
  this still the same tick?" before it asks "is this break short enough to
  forgive?", so a tolerance past the ceiling swallows every gap below itself
  and the ceiling never applies - including to the gaps it exists to end a run
  on.
- The settings tests build their numeric payload from the model instead of
  listing it. Typed out, it broke the moment a threshold was added: every
  settings POST in the suite became an invalid form at once, and an invalid
  form only reports a redirect that did not happen. Six failures, none of them
  about the one missing field.
- A detail page keeps its own section lit in the navigation. `navactive`
  matches the resolved view name, so opening a character or a Corporation
  muted the whole navbar - on the pages where knowing where you are matters
  most, because the way back out of a detail page is a link rather than the
  browser's back button.
- Nobody is measured against a yardstick they helped build. The two tabs that
  compare a Character against their Corporation's day were including that
  Character's own payouts in the Corporation's figure, so somebody
  contributing a third of a Corporation's volume pulled the baseline a third
  of the way towards themselves and hid a third of their own deviation. The
  only ratter in a Corporation was compared against nothing but themselves and
  came out ordinary by construction - which is exactly what a seeded 546
  payout character did until this was fixed. The window is now built from the
  Corporation minus the Character being measured, and a Corporation with
  nothing left over offers no yardstick at all rather than a shadow of one.
- The tooltip on the Corp Tax Changes detail chart said `payouts` and
  `systems` in English while the two columns above it were translated. Both
  strings had been in the catalogues all along as the column headings; the
  chart just never used them.
- `update_corp` no longer dies on a Corporation whose ingame tax rate
  Alliance Auth never learned. `tax_rate` is nullable there - a holding
  imported by hand is the usual case - and formatting it raised `TypeError`.
  The task runs one subtask per Corporation, so that took the subtask down
  while the page went on showing the month as uncalculated. Such a
  Corporation is skipped with a warning instead.
- The overview and the bots list drop their context columns below Bootstrap's
  md. The overview is the only page without `admin_view`, so it is the one
  every member opens on a telephone, and it was the only table in the app with
  no column that gives way - seven of them, two of which are long. Ingame Corp
  Tax and Alliance Tax step aside; which Corporation, how much, for which
  month, the reason to copy and whether it is paid stay. A Corporation at zero
  percent keeps its warning either way, because that marking sits on the
  Corporation cell as well as on the rate. The bots list drops Main and Active
  days, keeping the three figures the call is made on.
- The bot matrix can scroll again. `table-layout: fixed` holds a table inside
  its container whatever it contains, so the `.table-responsive` around it
  never had anything to scroll and eight columns divided up whatever width the
  phone had - about nineteen pixels of text per weekday with the sidebar in.
  The table now has a minimum width for the two to disagree about.
- The rate schedule on the settings page scrolls on its own instead of pushing
  the page sideways. It was the only table in the app without a scroll
  container, and its cells hold form controls, which have a width they will
  not go below.
- The statistics legend no longer gets a scrollbar of its own on a tablet. The
  cap that keeps it level with the chart was written against md while the
  columns break at xl, so between 768 and 1199 pixels the legend already sat
  under the chart at full width and was still capped - the second scrollbar
  the rule set out to avoid.
- The bots runtime line says `slower than usual` in words. It used to turn
  amber and nothing else, which tells a first time reader nothing - they have
  never seen the ordinary colour - and on the light themes that amber reads
  worse than the colour it was standing out from. The colour now only
  underlines the words.
- The quick filters on Corp Tax Changes announce which one is active.
  Bootstrap marks the pressed button with a class, which says nothing to a
  screen reader: all three read alike while the table changed underneath.
- EVE jargon was translated in the prose entries of every catalogue. `bounty`
  had become Kopfgelder, recompensas, primes, taglie, 현상금 and наград - one
  entry each, in all six languages, while the same files wrote `bounty`
  correctly everywhere else. Spanish, Korean and Russian also translated
  `Corporation` and `wallet`, Spanish translated `kills`, and the tooltip on
  the copy button named the field differently from the `Reason` column it sits
  next to, in all six. The rule is now checked against every entry of every
  catalogue rather than two labels on the settings page; each language was
  verified to fail that check when its term is put back. `Character` is
  deliberately left translated in prose - all six do it, and the column label
  stays English.
- Three catalogues dropped `as well as the rate` from the note under the daily
  curve. That clause is the reason the level says little: it carries the rate
  and the system's bounty modifier at once. French, Italian and Russian
  promised the reader an explanation and then gave half of it, with the
  conjunction left dangling. The Korean note on the stored alliance rate said
  last month where the English says past months, which inverts what the stored
  rate is for.
- Corp Tax Changes counted an NPC the static data export does not know as
  worth nothing, which shrank the bounty instead of dropping the payout. A
  Corporation whose kill list held one unpriced rat read as having switched to
  a hundred percent, complete with the marker the quick filter looks for. Such
  a payout is now left out. Nothing in the current journal hits this - every
  NPC of the past year was priced - but a rat from an expansion the export has
  not caught up with is enough.
- A share larger than the whole bounty is no longer read as a rate. It cannot
  be one: the Corporation never receives more than the bounty. It means two
  ratters whose tick, system and kill list happened to match were summed as
  though they were one fleet. Measured over a year of payouts this does not
  currently occur - the fleet groups sit on the same nine percent the single
  payouts do - but the summed value is the one number that can be wrong
  without anything showing it.
- `?year=9999` and `?year=0` returned HTTP 500 on both Corp Tax Changes pages.
  The year was checked for being a number but not for being a year, and the
  range query builds January of the following one, which `datetime` refuses.
  Out of range values fall back to the running year, as a non-numeric one
  already did.
- A blacklisted Corporation no longer appears in Corp Tax Changes or in Bots.
  The overview and the statistics already left it out; these two started from
  the alliance instead and never applied the list, against what the setting
  promises - never taxed and never listed.
- The overview table now groups by what a reader does with it rather than by
  date: the payable month's unpaid rows first, then its paid rows, then the
  not yet payable follow-up month, corporation name breaking every tie inside
  a group. It used to put every paid row - of either month - ahead of every
  unpaid row of the month actually due, burying the one thing a reader opens
  the page to find under rows nobody has to act on yet.
- Two colours that read as barely-there on the Darkly theme are gone. The
  Unbroken Runs chart plotted every payout outside the longest run in
  `--bs-secondary`, which Darkly sets to the same `#444` as the chart's own
  card background - the "other payouts" were there, just not visible. Off the
  Corporation Clock had the same fault the other way round: the Character's
  line used `--bs-primary`, a navy dark enough to all but disappear against
  the chart's grid. Both now draw in `--bs-success`, which reads on both a
  light and a dark canvas.
- The character switcher on a Character page was a `btn-outline-secondary`
  button sitting on its own card header - and Darkly gives both the same
  `#444`, so the button was there but not visible until hovered. It now
  borrows the page's own link colour, which every installed theme already
  picks to read against its card headers, rather than a fixed palette colour
  that happened to collide with one of them.
## [0.3.1] - 2026-09-14

### Fixed

- The character switcher's cold fallback - opened from a bookmark or the
  search box, without a list behind it - listed every character Alliance Auth
  knows on the account, whether or not it ever ratted. `alts_of` now takes
  the selected month and keeps only characters with a taxed transaction in
  it, the same definition every other reading of the month uses. A main with
  five alts and one ratter used to offer four names worth nothing to click.
- All four fallback lists - the ten longest days, and the three signals'
  "nothing crossed the threshold" lists - capped themselves to ten rows
  before grouping by main, not ten mains. Two alts of one account near the
  top of the ranking cost two of those ten slots for a single main, and
  pushed an eleventh row - a main of its own - out before grouping ever saw
  it; the page then showed nine mains where ten were possible. The new
  `group_limited_rows` groups first and cuts the groups instead, the way the
  primary, over-threshold lists already did.

## [0.3.3] - 2026-09-14

### Added

- The Character page links to zKillboard and to corptools' own Character
  Audit for the character on screen - kills and losses, and the account and
  wallet data this whole page is built from, neither of which eos_tax shows
  itself.

### Changed

- The four bot readings on the settings page now sit in their own card each,
  rather than under a plain heading. Their field names alone do not say which
  reading they belong to - `bot_run_min_ticks` a few lines above
  `bot_rhythm_min_payouts` above `bot_clock_min_payouts` - and the thresholds
  are deliberately not shared between readings, so a value meant for one
  ending up under another by mistake is exactly the fault a heading alone
  does not stop a reader from making.

## [0.3.4] - 2026-09-14

### Added

- Every character list, and the Character page itself, now shows how old the
  character is - Alliance Auth's own `birthday`, one unit rather than a
  calendar (`format_age`). A character ratting round the clock a week after
  creation is worth noticing on sight, not after a lookup. Empty rather than
  a placeholder when Alliance Auth never had a birthday for a character at
  all, the same as an unregistered Main.

## [0.2.6] - 2026-09-10

### Added

- Levels read in half points: an ingame rate is set in whole or half percent
  and the measurement lands a hair beside it, so 0.02 shows as 0 and 99.8 as
  100 - which is what makes those two findable, since nobody types 0.02 into a
  search box. Two levels 0.45 points apart can round onto the same half, and
  "9.5 to 9.5" would read as nothing having happened; where that would occur
  the Corporation keeps its exact values.
- The search covers the change column as well as the Corporation name, and two
  buttons filter to the rates worth chasing: a tax switched off and one turned
  all the way up. Typing 0 cannot do that - it also finds 10, 20 and 30 - so
  each row carries a hidden marker in `data-search`, the search counterpart to
  the `data-order` the table already uses for sorting, and the buttons drive
  the same search box rather than a mechanism of their own. Either end of a
  move counts: a Corporation that switched its tax off and one that switched
  it back on both show.
- Test suite grown to 250 tests.

## [0.2.5] - 2026-09-10

### Added

- A move has to reach a minimum to be listed - 0.45 percentage points by
  default, set on the settings page next to the bot thresholds. Below it the
  difference does not change what a Corporation pays by enough to care about.
  The same number decides what counts as one level, so a rate switched once
  jumps clear of it while a rate crept up in several smaller steps would be
  absorbed; toggling is a jump, so that is a trade worth making. A level also
  has to hold for two days, with a three day rolling median before it, which
  is what keeps a single odd day out of the list.
- Settings carries the smallest move that counts as a corp tax change, in
  percentage points, default 0.45. Migration `0011`.

## [0.2.4] - 2026-09-09

### Added

- Every change is its own row, so the table reads as a list of events: a
  Corporation that switched three times appears three times, and sorting by
  name groups its changes together. The detector always found them all - the
  list used to keep one row per Corporation and show only the largest.
- The list is sortable per column and searchable by Corporation, the way the
  overview is. Three columns sort by something other than what they show - the
  move by its size rather than the arrow between two percentages, the date
  chronologically rather than as a written month, the payout count without its
  separators - and the table opens in the order the server sent it, biggest
  move first, instead of DataTables' default of sorting by the first column.
- Test suite grown to 236 tests.

## [0.2.3] - 2026-09-09

### Added

- Test suite grown to 224 tests.

### Changed

- Settings offers only Corporations of the taxed alliances for exclusion.
  Excluding any other one changes nothing, and the full list of everything
  Alliance Auth knows runs long. A Corporation that is already excluded stays
  in the list even after its alliance leaves - dropping it would remove it from
  the form, and the next save would quietly let it back in. The choices follow
  the alliances ticked in the form rather than only the stored ones, so they do
  not lag a save behind.

### Fixed

- The settings form raised `AttributeError` when bound to a plain dict. It
  reached straight for `getlist`, which a request's QueryDict has and a dict
  does not, though both are valid ways to bind a form.

## [0.2.2] - 2026-09-09

### Added

- Corp Tax Changes, a fourth admin page. It lists Corporations whose ingame tax
  rate moved during the year and draws the daily curve behind each of them.
  The corporation wallet only carries the Corporation's own cut - `tax` equals
  `amount` on every bounty row - so the rate is not in it. It is recovered from
  `reason`, which names the NPCs killed, against what the static data export
  says each of them pays: the slice that arrived over the full bounty is the
  rate that was in force at that moment.
  The ratio also carries the system's bounty modifier, so the level on its own
  says little. A step in it does: a Corporation switching its rate moves every
  system on the same day, while the modifier drifts per system, and the number
  of systems behind a step is listed for exactly that reason. Fleet payouts are
  summed back together before measuring - split apart they would report a
  fraction of the rate - and a three day rolling median keeps one noisy day
  from reading as a switch. Without eve_sde the page says so instead of
  breaking.
- Moves are counted in percentage points, so nine percent to ten is one point
  rather than the eleven percent it makes of the old value. That is a
  deliberate trade: only a relative comparison cancels the bounty modifier
  out, so in points the same switch weighs less where the modifier is low.
  Points are what a person means when they say a Corporation went from nine to
  ten. Both levels are shown as percentages - 10.00 % to 2.00 % rather than
  0.1000 to 0.0200 - with the move in points beside them, which is what the
  list sorts by. The columns are named after what the number is: the share of
  the bounty, not the rate. It carries the system's bounty modifier too, and on
  the live data it measures 9.00 % where Alliance Auth records 15 %.
- Overview marks a Corporation whose ingame corp tax is zero. Nothing reaches
  the corporation wallet at that rate, so the row owes nothing and says nothing
  about what the Corporation earned.
- Test suite grown to 216 tests.

### Changed

- The pie is ordered by size, largest slice first, with Other last whatever its
  size. The legend is fed from the same list, so the two agree. The line chart
  keeps its order - there a series is found by its colour, and reshuffling on
  every month change would cost the reader the position they had learned.

## [0.2.1] - 2026-09-09

### Added

- A character on the bots page opens a detail view for the month: a matrix with
  the weekdays as columns and the calendar weeks as rows, holding the active
  hours of each day. The cells are one hue at a share of the busiest day, taken
  from the theme's own primary rather than fixed colours, so it reads on all of
  Alliance Auth's themes. Hovering a day names the hours behind the number.
- A character can be opened straight from the bots page by name. The list only
  ever shows the candidates and the ten longest days, so a character that
  crosses neither was unreachable - and that is exactly who gets looked up when
  someone reports a suspicion. An exact name jumps, a partial one offers what
  it found.
- Each row on the bots page names the Corporation whose tax the character
  contributed to, read from the journal rather than from Alliance Auth - hardly
  any ratter is registered there, so that column would sit as empty as the Main
  one. A character that moved mid month is listed under the Corporation it
  earned most for.
- The menu entry carries a count of the payments that are due - rows that are
  unpaid and already have a reason code to quote. Alliance Auth's own
  `MenuItemHook.count` renders it, the way hrapplications, srp and corptools
  do. Nothing outstanding, no badge.
- Test suite grown to 191 tests.

### Changed

- An hour counts as active once the same taxed journal type appears in it at
  least twice. A single entry used to be enough, which let one stray bounty
  tick stand for an hour of ratting. The rule now lives in one place and the
  bot list, the busiest day column and the detail matrix all use it, so the
  term means one thing. On the live journal for September this leaves 100 of
  335 active hours standing and drops the longest day from 7 hours to 2. The
  thresholds keep their defaults: a bot earns more than two bounties an hour
  and still reaches them, while a player's stray ticks no longer count at
  all.
- Chart colours are midpoints of equal subcubes of the RGB cube, after
  https://stackoverflow.com/a/79300351. Rotating the hue alone never varies
  saturation and lightness, so past the palette's eight slots corporations kept
  drawing the same colour; two different subcubes cannot. Both charts use it,
  so a corporation keeps its colour when the display changes.
  Two departures from the source, both measured with a validator: the cube's
  own grey diagonal and its darkest and lightest corners are skipped, and the
  order is farthest-first instead of by hue. Sorted by hue the worst
  neighbouring pair sits at dE 4.8, which is hard to tell apart even with full
  colour vision; taking the farthest colour each time lifts that to 21.9.
- Statistics reads on a phone. The chart took a desktop height while losing
  two thirds of its width, so below Bootstrap's md it takes viewport height
  instead; the months stay level and every other one is dropped rather than
  rotated; the y axis keeps five ticks instead of eight. The legend drops its
  income column - three columns of grouped digits in 350 pixels wrap into
  something nobody can scan - and no longer caps its height, since it sits
  under the chart there rather than beside it. The key figures move from one
  flex row into two columns.
- Whether a month can be paid is one function now. The overview compared month
  numbers inline and special-cased December, and the menu badge would have had
  to repeat it - two places disagreeing about what is due is worse than no
  badge.

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
