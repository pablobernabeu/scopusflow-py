# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pablobernabeu/scopusflow-py/releases/tag/v0.1.0
