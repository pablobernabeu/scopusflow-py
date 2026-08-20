# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `scopus_search_report()` writes the search up. It assembles the reproducible
  search-strategy record a systematic review has to report, from a harvest or from a
  plan not yet run: the database and platform, the field-wrapped query of every cell,
  the year limits, view, page size and paging mode, the date searched, the records
  retrieved against the number the API reported as matching, per-cell completeness,
  duplicates removed, the software versions, a runnable snippet that rebuilds the plan,
  and an explicit map of which PRISMA-S items the package can supply and which only the
  author can. `print(report)` shows the readable record,
  `report.format(style="paragraph")` gives a methods paragraph fit to paste into a
  manuscript, and `file=` writes the whole record as Markdown. The standard is PRISMA-S
  (Rethlefsen et al., 2021, Systematic Reviews, 10, 39) with the identification counts
  of the PRISMA 2020 flow diagram.

  Because the output is written for a published methods section, the record states only
  what the objects hold. An absent retrieval time is never replaced by the current one,
  a completeness figure is never given for a harvest whose reported total is unknown,
  duplicates are counted only where a merge recorded removing them, and every
  unverifiable field says it is unrecorded, in words. The rendering is byte-identical to
  the R twin's, pinned in both repositories by `tests/golden-search-record.txt`.

- `scopus_combine()`, the counterpart of the R twin's function of the same name.
  It binds record frames, renumbers `entry_number`, optionally drops the records they
  share (by Scopus identifier, failing that by DOI, case-insensitively), and records the
  merge in `attrs["combined"]`: how many went in, how many were kept, how many were
  removed and whether de-duplication ran. The guides showed this by hand with
  `pandas.concat` and a duplicate mask; that count exists only at the moment of the
  merge, and PRISMA-S asks for it.

- `SearchPlan` carries `page_size`, defaulting to the largest page the view allows
  (200 for `STANDARD`, 25 for `COMPLETE`), which is what pybliometrics already requests
  for each view. It is sent with the search, so the page size a search record states is
  the one the harvest actually used.

- CI now covers what users actually install, over and above the checkout. The
  matrix gains Python 3.14. A new job installs the built wheel into a bare
  environment outside the repository and imports it there, so packaged data and
  distribution metadata are
  exercised in their own right, where the source tree an editable install sits next to
  would otherwise mask them. A second new job installs the declared minimum dependency
  versions, which were an untested promise to anyone resolving against an older stack;
  a failure there means the floors need raising to what actually works. A weekly
  schedule runs the suite when nobody has pushed, so upstream drift shows up as a dated
  red badge before it can surprise anyone.

- `scopus_trend()` accepts a `field` argument, wrapping the query in a Scopus
  field tag once before the per-year counts, as `scopus_count()` and the R
  twin's `scopus_trend()` already do.

### Changed

- `fetch_plan()` attaches the per-cell accounting as `attrs["cell_totals"]` (`cell`,
  `date`, `n_records`, `reported_total`), and `attrs["total_results"]` is now the sum
  only when every cell reported a total, `None` otherwise. It previously summed the
  cells that happened to report one, which understated a search while looking like a
  real figure. The harvest also carries its originating `plan`, `retrieved_at`,
  `scopusflow_version` and `paging`, matching the attributes the R twin records; the
  time and version are omitted when any cell was resumed from a checkpoint, since a
  checkpoint carries no record of when it was taken.

- The minimum `pybliometrics` is now 4.4, raised from 4.0. The reference-shaping code
  imports the `Reference` namedtuple from `pybliometrics.scopus`, which no release
  before 4.4 provides, so 4.0 through 4.3 installed without complaint and then
  raised `ImportError` on the first call that touched references. The floor now
  states what the code actually needs.

- The app extra's minimum NiceGUI is now 2.14, raised from 2.0. Every in-browser
  export goes through `ui.download.content`, which NiceGUI gained in 2.14.0, so 2.0
  through 2.13 installed without complaint and then raised `AttributeError` on the
  first download click. The reasoning is the same as for the `pybliometrics` floor:
  state what the code needs.

- `scopusflow-gui` accepts `--version`, `--host`, `--port` and `--no-browser`, and
  rejects an unknown flag where it used to ignore one. The console-script target moved
  from `scopusflow.app:launch` to `scopusflow.app:main`, so an existing editable install
  needs reinstalling for the flags to take effect.

- `TREND_COLUMNS`, `COMPARISON_COLUMNS` and `ABSTRACT_COLUMNS` are exported from the
  package top level alongside `RECORD_COLUMNS`, making the API page's importability claim
  true. CITATION.cff no longer credits this package with rate-limit handling, which only
  the R twin implements. The Python 3.14 classifier is declared, matching the matrix.

- The app's reproducible script records the package version and, in demo mode, states
  that the records were replayed from the bundled harvest.

- The documentation's five reference pages are now one grouped API reference at
  `/api/`, which is how the other Python packages in the family present theirs. The
  groups and their order are unchanged, so a function still sits under the heading the
  R twin files it under, and each old page URL redirects to the merged page and carries
  any anchor across with it.

### Fixed

- `scopus_combine()` raised on two harvests, and mixed them up when it did not.
  `concat` decides whether to hand the inputs' `attrs` to the result by comparing the
  dicts, and two `fetch_plan()` harvests each carry a `cell_totals` frame, so the
  comparison ended up evaluating one frame against another and pandas raised "The truth
  value of a DataFrame is ambiguous". Where it did succeed, because the inputs happened
  to carry the very same objects, the union inherited one harvest's `plan`,
  `total_results` and `cell_totals`, and the search record then reported two harvests as
  complete against a total belonging to one of them. The merged set is now built from
  the rows alone, as the R twin's is, and carries only the merge counts.
- The PRISMA 2020 identification block counted the records identified after
  de-duplication, so the two figures it gives could not both be right: the diagram
  subtracts the duplicates removed from the records identified to reach the records
  screened, and 138 identified less 11 removed is not the 138 rows the set holds. Where
  a merge recorded how many records went into it, that is now the identification count.
  The R twin carried the same defect and was fixed with it.
- A plan not yet run was described in the past tense, and its date line said the set
  did not carry a retrieval time, when the truth was that no retrieval had happened.
- `SearchPlan` kept its years in the order they were typed, so two plans describing
  the same search compared unequal, and the reproduction snippet
  `scopus_search_report()` emits, which renders them canonically, rebuilt a plan that
  ran identically but failed an equality check against its own original. Years are now
  stored sorted and de-duplicated, as every other caller of the year check already
  treated them and as `cells()` already did with them.
- A missing value became the literal string `"nan"`. An absent EID landed in
  `scopus_id` as the four characters `nan`, which every later guard then accepted as a
  perfectly ordinary identifier, and a missing citation count raised where it should
  have yielded NA. Both paths, search and abstract, now test for missingness before any
  string coercion.
- Resuming from a CSV checkpoint changed the identifiers. `scopus_id`, `year` and
  `citations` were float-promoted on read, so a resumed record exported an identifier
  that differed from the one it was harvested with.
- The comparison average summed its numerator over years its denominator excluded, so
  a year with no reference count inflated it above every per-year share printed beside
  it, and that average orders the topics in the plot. It is now computed over the years
  where both counts are present. The R twin carried the same defect and was fixed with
  it.
- Checkpoints are written atomically, and a damaged one is recoverable. Both the
  per-cell harvest cache and the per-identifier abstract cache wrote straight at their
  destination, so an interrupted run left a half-written file that raised out of the next
  resume and blocked it permanently. Each now writes to a sibling temporary file and
  renames it into place, and a checkpoint that cannot be read back is discarded with a
  warning and refetched. The warning text is byte-identical to the R twin's. That last
  guard only worked for parquet: a truncated CSV is still a well-formed CSV, and a row
  wider than its header does not raise either, because pandas reads the surplus field as
  an index and returns a tidy frame. A damaged CSV checkpoint was therefore parsed into
  whatever it happened to look like and merged into the results. A checkpoint must now
  also carry every `RECORD_COLUMNS` name to be accepted, `authkeywords` aside, since a
  checkpoint written before that column existed simply predates it, and is
  accepted as such.
- A short harvest passed unnoticed. `fetch_plan()` now compares each cell against the
  total the API reports for that cell's query, warns on a shortfall, and attaches the
  summed total as `result.attrs["total_results"]`.
- Year validation now matches the R twin. Non-whole, out-of-range and non-numeric
  years are refused at every entry point, where they used to be silently truncated or
  interpolated into the query. Note this newly refuses numeric strings such as `"2015"`,
  which the R half has always rejected.
- `corpus()` carries through `scopus_abstract()`'s request and quota accounting, where
  it used to discard it, and `plot_top()` raises a named error on an empty tally like
  its sibling plots.
- A transient failure was checkpointed as data. `scopus_abstract()` wrote the all-NA
  row a failed retrieval records into the per-identifier cache, so a timeout, a quota
  refusal or a server error became permanent cached data that every later resume read
  back in place of the real record. Only successful retrievals are checkpointed now, and
  a failed identifier still yields its warned-about NA row and is retried on the next
  resumed run. The R twin carried the same defect and was fixed with it.
- A quota lookup could turn a successful retrieval into an NA row. The quota block in
  `scopus_abstract()` guarded `get_key_remaining_quota` but called
  `get_key_reset_time()` unguarded, so an object exposing only the first failed the
  whole row after the retrieval had already succeeded. Both lookups are now optional.
- Resuming a `COMPLETE`-view cache under a `STANDARD` plan returned `authkeywords`,
  a column the documentation says `STANDARD` output never carries. The checkpoint plan
  check now compares the view as well as the query, and a mismatched checkpoint is
  warned about and refetched in either direction. New checkpoints record the view they
  were written under (stripped again on resume), and a checkpoint from before
  `authkeywords` existed is still accepted under `COMPLETE`, since it predates the
  column and so cannot be foreign.
- Closing one app tab deleted every session's checkpoints. The GUI's disconnect
  cleanup removed the shared temp base, one level above its own directory, so a second
  tab's harvest lost its cache mid-run. Each page scope now works under a per-session
  subdirectory and removes only that when its tab closes.

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
