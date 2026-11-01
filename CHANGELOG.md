# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Upgrading from 0.3.0

#### Changed results

- `fetch_plan()`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` bracket a query with a top-level OR, AND NOT or proximity
  operator before adding the year limit, which a top-level AND NOT took into its
  negation. Re-run such queries, whose `fetch_plan()` checkpoints are fetched again
  once.
- `compare_topics()` sends each comparison as `(reference) AND (term)`, where, without
  `field`, it joined them without brackets, so a reference with a top-level AND NOT
  took the term into its negation and shares could pass 100%. Re-run such comparisons
  made without `field`. Given `field`, only the `query` column differs.
- `fetch_plan()`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` send `refresh=True` unless you pass `refresh`, where
  pybliometrics' cache could answer a re-run with an earlier result. `refresh=False`, or
  a number of days, uses that cache again and warns when it answers.
- `fetch_plan()` records each checkpoint's query, view, page size and paging in a
  manifest beside it and serves it only to a matching cell, where an empty checkpoint
  served any plan and a `COMPLETE` one a `STANDARD` plan. Empty 0.3.0 checkpoints are
  fetched again.
- `scopus_query()` brackets each term of several words, other than a quoted or braced
  phrase or a bracketed or field-tagged group, when it joins terms without `field`, so
  `scopus_query("machine learning", "deep learning", op="OR")` gives
  `(machine learning) OR (deep learning)`, where Scopus read the unbracketed join as
  `machine AND (learning OR deep) AND learning`.
- `scopus_abstract()` checkpoints only successful retrievals, so a failed identifier is
  retried on resume, where its NA row was read back as data. NA rows that 0.3.0
  checkpointed are still read back, so delete their checkpoint files to retry them.
- Checkpoints are written atomically. An unreadable one, which stopped every resume, or
  one lacking a record column, which was served, is fetched again with a warning. A
  0.3.0 CSV checkpoint cut short by an interrupted run can still be served, so re-run
  that plan with `resume=False`.
- A CSV checkpoint resumes with `scopus_id` as text and `year` and `citations` as whole
  numbers, where they were read back as numbers, as floats once a value was missing, so
  a resumed record could carry a different identifier.
- A missing EID or citation count in search or abstract results gives NA, where an
  absent EID became the string `"nan"` in `scopus_id` and a missing citation count
  raised an error or, in `scopus_abstract()`, lost the row.
- `scopus_abstract()` trims identifiers, drops the `SCOPUS_ID:` prefix under
  `by="scopus_id"` and sends integer Scopus IDs as text, where it sent them as given.
  `corpus()` drops blank identifiers with a warning, as it drops missing ones.
- `scopus_abstract()` keeps a document's row when pybliometrics cannot parse a keyword
  entry without text (pybliometrics issue 436), leaving its keywords NA with a warning,
  where it lost the whole row. pybliometrics 4.5 drops such an author keyword itself.
- Once the quota is spent, `scopus_abstract()` and `corpus()` give an NA row to an
  identifier that pybliometrics' own cache holds, where 0.3.0 returned its cached
  record.
- `corpus(view="REF")` no longer asks `scopus_abstract()` for author keywords, which
  REF does not carry, so a run resumed from the checkpoints 0.3.0 wrote for that view
  fetches those abstracts again, spending Abstract Retrieval quota.
- `year_counts()` gives zero for each searched year without records or, for a set
  without a plan or year limit, each year between its first and last, where it left them
  out and `plot_trend()` drew a line across them. `fill=False` gives the 0.3.0 output.
- `top()` strips sources and authors of spaces, tabs and line breaks alone and drops
  blank sources, where it stripped authors of any white space and sources of none.
- `top()` orders tied values in byte order, keeping those that sort first at the
  cut-off, where it kept an arbitrary subset of them.
- `fetch_plan()` and `to_records()` join a `COMPLETE` harvest's authors with `"; "`,
  where they kept pybliometrics' `";"`, which the R twin read as one author, and drop
  the trailing comma of a name without a given name.
- `scopus_abstract()` counts each document it requests once in `n_requests`, where a
  step failing after the response arrived counted it twice, and leaves out the rows
  pybliometrics answered from its own cache.
- `scopus_trend()` sends a whole-number float year, such as 2015.0, as
  `PUBYEAR IS 2015`, where it sent `PUBYEAR IS 2015.0`.
- `example_records()` gives the U+2010 hyphen in five author names as the ASCII hyphen,
  where it kept U+2010, so those names now match the R twin's corpus.
- The app trims the query before every request, so it sends the query the script panel
  shows, where 'Fetch records' sent it as typed.

#### Changed interface

- `SearchPlan`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` refuse with `ValueError`, before any request, unbalanced
  brackets, quotation marks or braces and the `LIMIT-TO()` and `EXCLUDE()` refinements
  that the Search API ignores, with which a search ran unfiltered.
- `wrap_field()` and `SearchPlan` given `field` refuse with `ValueError` a query, and
  `scopus_query()` given `field` a term, that already opens with a field tag, where they
  nested the tags, which the API rejects. `scopus_count()` and `compare_topics()`
  refuse such a query before the request.
- `years`, wherever a function takes it, must hold whole numbers from 1700 to 2200, so a
  fraction, a year outside that range or a numeric string such as `"2015"` raises
  `ValueError`, where only `compare_topics()` refused the first two and every function
  took the third.
- scopusflow requires pybliometrics 4.4 or later, and its `app` extra NiceGUI 2.14 or
  later.
- `corpus()` returns a `scopus_id` column in second place, so code that selects its
  columns by position needs updating.
- `scopus_trend()` takes `field` third, before `view`, so a view passed by position, as
  in `scopus_trend(q, years, "COMPLETE")`, is taken as a field tag. Pass `view=` by
  name.
- `fetch_plan(subscriber=False)` pages by offset, as pybliometrics documents, where
  scopusflow overrode it with cursor paging, so a cell over 5000 records raises
  `ScopusQueryError` and 0.3.0 checkpoints are fetched again. Drop `subscriber=False` to
  page by cursor as 0.3.0 did.
- `SearchPlan` stores `years` sorted and without repeats, as a tuple, and `field`
  stripped and upper-cased. It raises `ValueError`, when the plan is built, for a
  `field` that is not a string of letters and hyphens.
- `scopus_abstract()` raises `TypeError` for `ids` that are not one identifier, a list,
  a tuple, a pandas Series or Index or a NumPy array, such as a set, which it accepted.
- `scopus_abstract()` raises, before any request, `ValueError` for a missing or blank
  identifier and `TypeError` for one that is neither text nor an integer, such as a
  float, even a whole one. `corpus()` raises the same `TypeError` for such a value in
  its `by` column.
- `scopus_abstract(include=("keywords",))` raises `ValueError` unless `view="FULL"`,
  where other views gave an empty column.
- `fetch_plan()`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` raise `ScopusFlowConfigError`, a `RuntimeError`, before any
  request, when `pybliometrics.init()` has not been called in the session, where
  pybliometrics raised `FileNotFoundError` ('No configuration file found').
- `scopus_abstract()` and `corpus()` raise `ScopusFlowConfigError`, before any request,
  when `pybliometrics.init()` has not been called in the session, where they gave every
  identifier an NA row with a warning.
- `plot_trend()` raises `ValueError` for an empty trend, where it drew empty axes or
  failed inside numpy, depending on the versions installed.
- `top()` raises `ValueError` for an `n` that is not a positive whole number, where
  `n=-1` returned all but the last value.
- `fetch_plan()`, `scopus_abstract()` and `corpus()` refuse with `ValueError`, before
  any request, a `cache_dir` in which no file can be created, where 0.3.0 read its
  checkpoints and lost any records it fetched to an error. Copy a read-only cache to a
  writable directory.
- `scopusflow-gui` rejects an unknown flag, where it ignored one, and gains `--version`,
  `--host`, `--port` and `--no-browser`. Reinstall an editable install, since its entry
  point has moved.

#### Changed output

- `to_bibtex()` and `to_ris()` write a name ending in initials as 'Surname, I.', where
  BibTeX read the initials as the family name and Zotero kept each RIS author as one
  field. Citation keys are unchanged.
- `to_bibtex()` spaces run-together initials, which BibTeX read as one given name, and
  protects words such as DNA in titles from lower-casing.
- `to_ris()` gives the source title as `T2` in place of `JO` and adds `DB  - Scopus` and
  the EID as `AN`.
- `to_ris()` and `to_bibtex()` export an `authkeywords` or `abstract` column, as a
  `COMPLETE` harvest (the abstract with `fields="extended"`) or `scopus_abstract()`
  gives, where they wrote neither.
- `top(by="author")` warns once per process that a set recorded as retrieved under
  `STANDARD` names first authors only. Sets retrieved by 0.3.0 record no view and do not
  warn.
- When the years plotted reach the year of retrieval, `plot_trend()` adds a note below
  the axis saying that it and any later year were incomplete when retrieved. It reads
  the year from `attrs["retrieved_at"]`, which `scopus_trend()` records and
  `year_counts()` keeps.
- `scopus_abstract()` and `corpus()` stop requesting at a spent quota and give the
  remaining identifiers their NA rows with one `ScopusFlowQuotaWarning`, where they
  requested each and warned for each.
- `fetch_plan()` warns when a cell returns fewer records than the API reported for it.
- `SearchPlan`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` warn with `scopusflow.query.QuerySyntaxWarning` for
  `INDEXTERMS()`, which pybliometrics documents as not working through the Search API.
- `plot_top()` raises a `ValueError` saying that the tally is empty, where its
  `ValueError` concerned an empty sequence.
- The app's generated script downloads as `scopusflow-script.py`, where a script saved
  as `scopusflow.py` imported itself in place of the package when run from its folder.
- The script the app generates keeps each plan's checkpoints in a directory of its own,
  where plans shared `harvest` and overwrote each other's checkpoints. A script
  generated now does not resume from the checkpoints of one generated by 0.3.0.
- The script the app generates records the scopusflow version, notes when demo mode was
  on, calls `pybliometrics.init()`, writes the search record to
  `scopus-search-record.md` and includes a comparison run with 'Partition by year' off,
  which it left out.

### Added

- `scopus_search_report()` writes up a harvest, or a plan not yet run, as a PRISMA-S
  search record (Rethlefsen et al., 2021) with the PRISMA 2020 identification counts,
  returned as a `SearchReport`. Its `format(style="paragraph")` gives a methods
  paragraph, and `scopus_search_report(file=)` writes the record as Markdown.
  `PRISMA_S_ITEMS` names the 16 items.
- The app's 'Search record (.md)' button downloads that record. In demo mode, the record
  says that it describes no search that was run.
- `scopus_combine()` binds record sets and renumbers `entry_number`. `dedupe=True`, also
  spelled `"id_or_shared_doi"`, keeps one copy of each record, matched by Scopus
  identifier or, for a record without one, by DOI, and counts the duplicates removed.
  `dedupe="id_or_doi"` and `"id_then_doi"` apply other rules.
- `fetch_plan()` gains `cursor`. `cursor=False` pages by offset, for keys without a
  Scopus subscription, and raises `ScopusQueryError` naming any cell that matches more
  than 5000 records. The default keeps cursor paging, and a checkpoint serves only a
  request in its own paging mode.
- `fetch_plan()` and `to_records()` gain `fields="extended"`, adding the document type,
  source type, volume, issue, pages, ISSN, PubMed identifier, open-access status and,
  under `COMPLETE`, the abstract, at no extra quota. `EXTENDED_COLUMNS` names the
  columns both views add.
- With `fields="extended"`, `to_ris()` and `to_bibtex()` type conference papers,
  conference reviews, chapters and books by their Scopus document type and add the
  volume, issue, pages, ISSN and, in RIS, the document type as `M3`.
- `scopus_abstract(include=("index_terms",))` returns the index keywords Scopus assigns,
  in an `idxterms` column, under `view="FULL"`. `corpus()` gains `keywords`, to use them
  alone (`"index"`) or with the author keywords (`"both"`). The default, `"author"`, is
  unchanged.
- `write_corpus()` writes, and `to_theoryforge_corpus()` returns, a `corpus()` result in
  theoryforge's corpus schema, with a `provenance` block, keying cited works on the
  Scopus identifier so that a work is one node however its DOI is written.
- `diff_records()` compares two harvests record by record, matching records as
  `scopus_combine(dedupe=True)` does. It gives each record's citation counts in both and
  marks as `conflict` a record whose DOI the other harvest gives to a different record.
- `write_records()` and `read_records()` save a record set and read it back, the file
  extension choosing parquet, which keeps the provenance and needs the new `parquet`
  extra, or CSV, read back with the record schema.
- `SearchPlan` gains `page_size`, by default the largest page the view allows (200 for
  `STANDARD`, 25 for `COMPLETE`), which `fetch_plan()` sends, and `to_dict()` and
  `from_dict()`, which turn a plan into a plain dict and back.
- `scopus_trend()` gains `field`, which wraps the query in a field tag, as in
  `scopus_count()`.
- `TREND_COLUMNS`, `COMPARISON_COLUMNS` and `ABSTRACT_COLUMNS` are exported from the
  package top level.
- The app's 'Search in' selector offers '(none)', which sends the query without a field
  tag.

### Changed

- `fetch_plan()` records its provenance in the harvest's `attrs`: the plan, the first
  and last retrieval times, the scopusflow version, the paging mode, the view and each
  cell's record count beside the total the API reported.
- A harvest stopped through `should_stop` records `attrs["stopped_early"]`,
  `attrs["cells_planned"]` and `attrs["cells_run"]`, and the app says that it stopped
  after k of N cells, where it announced the records retrieved.
- The app shows a harvest's warnings in its live terminal and says that a harvest that
  warned may be incomplete, where it announced it as a success.
- In demo mode, the app says above the records that they were replayed from the bundled
  example harvest and were not retrieved from Scopus. Before a harvest, the results
  area says that the records will appear there.
- `corpus()` reports its requests and the quota left in `attrs["n_requests"]` and
  `attrs["quota"]`, and records the search expression, when the search that found the
  records ran and the kind of keyword as `attrs["query"]`, `attrs["retrieved_at"]` and
  `attrs["keywords"]`.
- `diff_dois()` counts the records it could not compare for want of a DOI in
  `attrs["n_old_without_doi"]` and `attrs["n_new_without_doi"]`.
- The app draws its buttons, focus rings and progress bars in a deep teal on which the
  buttons' white text has the contrast it needs, each figure has a name a screen reader
  reads and the page has a top-level heading.

### Fixed

- A checkpoint that `fetch_plan()`, `scopus_abstract()` or `corpus()` fails to write, as
  on a full disk, gives a warning, and its records are kept, where they were lost to an
  error.
- `scopus_intersections()` uses as given a concept that opens with a tag of
  `FIELD_TAGS` written with a space before the bracket, as the web interface writes
  `TITLE-ABS-KEY ( x )`, where it wrapped it in `field` again and the API refused it.
- Each app session keeps its checkpoints in a directory of its own, so closing one tab
  no longer deletes another's mid-harvest.
- The app runs one harvest, plan check or comparison at a time, where a harvest could
  start during a comparison and a comparison could start twice.
- `fetch_plan()` runs a plan with `partition="none"` and whole-number float years, such
  as 2015.0, where it raised `ValueError`.
- The app's size note clears when the search whose size it gave changes, where it
  stayed on screen for a different search.
- The app shows a short note in place of a figure it cannot draw, where the error took
  the export buttons away, and shows its year range and progress bar only while they
  apply.

### Security

- The app keeps a pasted API key in memory, where it wrote it to
  `~/.config/pybliometrics.cfg` on a machine without a pybliometrics configuration.
  On such a machine, it caches responses in a temporary directory removed when the app
  stops.

### Documentation

- The guide to designing queries describes the offline query checks and gives a recipe
  for testing a strategy's relative recall against records known to be relevant,
  following Sampson et al. (2006) and Bramer et al. (2018). It also explains loose and
  exact phrases and why a query mixing operators needs brackets.
- The guides no longer present the bundled corpus as the result of an unquoted search.
  It came from an exact-phrase search in OpenAlex, and the demonstration plan and live
  searches quote the phrase, since Scopus joins the words of an unquoted phrase with
  AND.
- The API reference gives a topic comparison's cost as (terms + 1) × years requests,
  where it gave one count request per term per year.
- The app guide no longer promises that a run stopped by the quota resumes in a later
  session, and points to the generated script for a harvest that has to continue after
  the session ends. It says that demo mode is on whenever the app opens in a tab, where
  it said only the first time, and it and the `launch()` docstring no longer say that
  the app binds to `127.0.0.1` whatever host it is given.
- The guide to building a reference set says that a harvest under the default
  `STANDARD` view names the first author of each record alone, so each RIS or BibTeX
  entry has one author, and that `view="COMPLETE"` gives the author list, where it said
  that a live harvest returned every author.
- The guides show `pybliometrics.init()`, which pybliometrics 4 requires in every
  session, before the first live call, where they implied that a configuration file was
  enough.
- The guides and the `scopus_abstract()` and `corpus()` docstrings no longer say that
  REF reference lists are truncated, since `scopus_abstract(view="REF")` and
  `corpus(view="REF")` return the whole list at one request per 40 references.
- The tracking guide keeps its baseline with `write_records()` and `read_records()`,
  where its CSV route read `scopus_id` back as a number, and gives the correct counts of
  new and shared papers, saying that records without a DOI were not compared.
- The guides say that a refused entitlement stops a batch of abstracts, and the planning
  guide that `scopus_count()` also counts the years between those of a year-partitioned
  plan with gaps. The `to_records()` docstring gives a missing author keyword as a value
  that `pandas.isna` recognises, where it said `None`.
- The guides no longer say that the 5000-record offset ceiling forces a partition by
  year, since `fetch_plan()` pages by cursor unless given `cursor=False`, and give the
  partition's reasons as per-year checkpoints, completeness checks and progress.
- Install commands in the documentation give extras in double quotes and carry no
  trailing comments, so they paste into any shell.

## [0.3.0] - 2026-07-23

### Added

- `example_records()` returns a bundled worked-example harvest of 138 real
  journal articles on graphene supercapacitors, 2015 to 2024, over the standard
  `RECORD_COLUMNS` schema. The records come from OpenAlex, whose metadata is
  released under CC0; Scopus terms do not permit redistributing retrieved
  records. They are the same corpus the R twin ships.

### Changed

- Every guide and reference example now runs on that bundled harvest, where a
  fabricated frame used to stand in, with the live API call shown alongside. The
  app's demo mode replays it too, so a first visit shows real articles and a real
  publication curve. A demo cell for a year outside the corpus returns nothing and
  says so in the log, since padding it out with a neighbouring year's rows would
  double records up. The app's year slider opens on the corpus span, and the demo
  comparison, whose counts are still simulated, now says so beneath the figure.

### Fixed

- `extract_dois` no longer emits the literal `<NA>` for a record with no DOI,
  which a nullable string column produces where a float NaN would have been
  skipped.

## [0.2.0] - 2026-07-15

### Added

- Concept intersections: `scopus_intersections` sizes a named set of concepts
  and their overlaps from the count endpoint (one cheap request per row, no
  harvest), accepting bare terms wrapped in a field tag or complete field-tagged
  expressions used as given, with optional short labels for the intersection
  rows. `plot_scopus_intersections` draws the result as a log-scale lollipop
  chart with a focal set accented. This brings the Python package to parity with
  the R `scopus_intersections()` and `plot_scopus_intersections()`.

## [0.1.0] - 2026-07-10

First release: a reproducible workflow layer over
[pybliometrics](https://pybliometrics.readthedocs.io) for Scopus searches, and
the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/).

### Added

- Search planning and queries: `SearchPlan` describes a search before running
  it and can be partitioned by year, a field-tagged boolean query builder
  (`scopus_query`, `wrap_field`) with a reference table of Scopus field tags,
  and cheap result-size lookups (`scopus_count`) for quota-aware pre-flight
  sizing.
- Harvesting: resumable, checkpointed retrieval of a plan (`fetch_plan`), with
  per-cell progress logging on the `scopusflow` logger and co-operative
  cancellation (`should_stop`). Checkpoints are keyed by the whole plan, and on
  resume the recorded query is compared against the cell's, so a cache
  directory written by a different plan is refetched with a warning rather
  than silently reused.
- Records: one stable, tidy record schema across query types (`to_records`,
  `RECORD_COLUMNS`), with an `authkeywords` column added when
  `SearchPlan(view="COMPLETE")` is used, at no request cost beyond that view's
  own smaller page size.
- Abstract retrieval: batch, per-identifier-resilient `scopus_abstract`
  (default `view="META_ABS"`, so a plain call returns the abstract text), with
  `include=("references", "keywords")` for a document's own reference list and
  author keywords, per-identifier caching keyed by view and `include`
  selection (`cache_dir`/`resume`), `n_requests`/`quota` accounting, a warning
  when the references returned fall short of the document's reported
  `refcount`, and a clear `ScopusFlowForbiddenError` on an entitlement 403
  that stops the batch, suggesting the other of `"FULL"`/`"REF"` only when the
  refused view was one of those two.
- Corpus assembly: `corpus` combines a search result with abstract retrieval
  into a minimal `id`/`title`/`year`/`keywords`/`references` shape for
  downstream tools such as keyword co-occurrence or citation-network analysis,
  covered by the *Author keywords and references* guide.
- Trends and comparison: annual publication trends (`scopus_trend`,
  `year_counts`) computed from cheap result-size lookups, and topic-trend
  comparison (`compare_topics`) with per-step progress logging. The
  comparison's documented count-request cost includes the reference topic:
  (terms + 1) x years.
- Summaries and change tracking: source and author top tallies (`top`), DOI
  extraction and change tracking between runs (`extract_dois`, `diff_dois`).
- Plots: brand-themed matplotlib figures for trends (`plot_trend`), top
  tallies (`plot_top`, labelling each bar with its count and reserving x-axis
  headroom so the longest label stays inside the axes) and topic comparison
  (`plot_comparison`, mirroring the R `plot_scopus_comparison`): illustrative
  Wilson stability bands with a Source/Wilson caption, a percent-formatted
  y-axis, record counts in the labels by default (`counts_in_legend`), the
  reference topic named in a subtitle, colour-matched end-of-line labels
  spread apart at draw time in the same order as the line ends, an optional
  `legend_inside` placing the legend in the emptiest corner, and full schema
  validation with a friendly `ValueError`.
- Reference-manager export to BibTeX and RIS (`to_bibtex`, `to_ris`), so a
  search carries into Zotero, EndNote, Mendeley or a LaTeX bibliography.
- A local, code-free NiceGUI app (`scopusflow-gui`, the `app` extra) that
  drives the whole workflow through a browser tab: a background harvest with a
  live progress terminal, every choice (including the chosen `view` and the
  comparison) mirrored back as a runnable Python script, results shown as a
  paginated table and plots with export, a Compare topics card with highlight,
  stability-band and counts-in-label controls plus a count-request cost
  estimate and CSV export, and a demo mode that needs no key. Harvest
  checkpoints live under the temp directory and are removed when the tab
  closes, so search terms do not linger on disk. Duplicate comparison terms
  are dropped, a zero-record harvest is reported as a warning, and the
  controls carry visible labels.
- Documentation guides that execute their examples, so tables and plots appear
  inline as on a knitted vignette.

[Unreleased]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pablobernabeu/scopusflow-py/releases/tag/v0.1.0
