# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **A missing value became the literal string `"nan"`.** An absent EID landed in
  `scopus_id` as the four characters `nan`, which every later guard then accepted as a
  perfectly ordinary identifier, and a missing citation count raised instead of yielding
  NA. Both paths, search and abstract, now test for missingness before any string
  coercion.
- **Resuming from a CSV checkpoint changed the identifiers.** `scopus_id`, `year` and
  `citations` were float-promoted on read, so a resumed record exported an identifier
  that differed from the one it was harvested with.
- **The comparison average summed its numerator over years its denominator excluded**, so
  a year with no reference count inflated it above every per-year share printed beside
  it — and that average orders the topics in the plot. It is now computed over the years
  where both counts are present. The R twin carried the same defect and was fixed with it.
- **Checkpoints are written atomically and a damaged one is recoverable.** Both the
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
  checkpoint written before that column existed is old rather than damaged.
- **A short harvest passed unnoticed.** `fetch_plan()` now compares each cell against the
  total the API reports for that cell's query, warns on a shortfall, and attaches the
  summed total as `result.attrs["total_results"]`.
- **Year validation now matches the R twin.** Non-whole, out-of-range and non-numeric
  years are refused at every entry point rather than silently truncated or interpolated
  into the query. Note this newly refuses numeric strings such as `"2015"`, which the R
  half has always rejected.
- `corpus()` carries through `scopus_abstract()`'s request and quota accounting instead
  of discarding it, and `plot_top()` raises a named error on an empty tally like its
  sibling plots.

### Changed

- **The minimum `pybliometrics` is now 4.4, raised from 4.0.** The reference-shaping code
  imports the `Reference` namedtuple from `pybliometrics.scopus`, which no release before
  4.4 provides, so 4.0 through 4.3 installed cleanly and then raised `ImportError` on the
  first call that touched references. The floor now states what the code actually needs.
- `scopusflow-gui` accepts `--version`, `--host`, `--port` and `--no-browser`, and
  rejects an unknown flag instead of ignoring it. The console-script target moved from
  `scopusflow.app:launch` to `scopusflow.app:main`, so an existing editable install needs
  reinstalling for the flags to take effect.
- `TREND_COLUMNS`, `COMPARISON_COLUMNS` and `ABSTRACT_COLUMNS` are exported from the
  package top level alongside `RECORD_COLUMNS`, making the API page's importability claim
  true. CITATION.cff no longer credits this package with rate-limit handling, which only
  the R twin implements. The Python 3.14 classifier is declared, matching the matrix.
- The app's reproducible script records the package version and, in demo mode, states
  that the records were replayed from the bundled harvest rather than retrieved.

### Added

- **CI tests what users install, not only the checkout.** The matrix gains Python
  3.14. A new job installs the built wheel into a bare environment outside the
  repository and imports it there, so packaged data and distribution metadata are
  exercised rather than masked by the source tree an editable install sits next
  to. A second new job installs the declared minimum dependency versions, which
  were an untested promise to anyone resolving against an older stack; a failure
  there means the floors need raising to what actually works. A weekly schedule
  runs the suite when nobody has pushed, so upstream drift surfaces as a dated
  red badge instead of a surprise.

### Changed

- The documentation's five reference pages are now one grouped API reference at
  `/api/`, which is how the other Python packages in the family present theirs.
  The groups and their order are unchanged, so a function still sits under the
  heading the R twin files it under, and each old page URL redirects to the
  merged page and carries any anchor across with it.

## [0.3.0] - 2026-07-23

### Added

- `example_records()` returns a bundled worked-example harvest of 138 real
  journal articles on graphene supercapacitors, 2015 to 2024, over the standard
  `RECORD_COLUMNS` schema. The records come from OpenAlex (CC0) rather than
  Scopus, whose terms do not permit redistributing retrieved records, and they
  are the same corpus the R twin ships.

### Changed

- Every guide and reference example now runs on that bundled harvest instead of
  a fabricated frame, with the live API call shown alongside. The app's demo
  mode replays it too, so a first visit shows real articles and a real
  publication curve; a demo cell for a year outside the corpus returns nothing
  and says so in the log rather than padding itself out. The app's year slider
  opens on the corpus span, and the demo comparison, whose counts are still
  simulated, now says so beneath the figure.

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
