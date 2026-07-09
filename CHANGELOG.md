# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `plot_comparison` gains an optional `legend_inside` argument. When a legend is
  drawn (too many topics to label the lines directly), passing `True` tucks it
  into the top-left of the axes where the rising-share lines leave room, rather
  than letting matplotlib pick a spot. The default `False` keeps the existing
  behaviour, and the argument mirrors the R package's `legend_inside`.

## [0.2.0] - 2026-07-07

### Added

- `fetch_plan`/`to_records` add an `authkeywords` column when
  `SearchPlan(view="COMPLETE")` is used, at no request cost beyond that
  view's own smaller page size; `view="STANDARD"` output is unchanged.
- `scopus_abstract` gains `view` and `include=("references", "keywords")`,
  retrieving a document's own reference list (one DataFrame per document,
  using pybliometrics' native reference fields, not a joined string) and
  author keywords via Abstract Retrieval, with per-identifier caching
  (`cache_dir`/`resume`), a `n_requests`/`quota` attribute, and a clear,
  actionable `ScopusFlowForbiddenError` on an entitlement 403 that stops the
  batch rather than repeating the same failure for every identifier.
- A new `corpus` combines a search result with this Abstract Retrieval step
  into a minimal `id`/`title`/`year`/`keywords`/`references` shape for
  downstream tools such as keyword co-occurrence or citation-network
  analysis, without replacing `to_bibtex`/`to_ris`. A new guide, *Author
  keywords and references*, walks through all of this.

### Changed

- `plot_comparison` no longer draws leader lines from each label to its line:
  the labels are colour-matched and spread in the same top-to-bottom order as
  the line ends, so the link is clear without a leader that would otherwise cut
  across neighbouring labels.

## [0.1.1] - 2026-06-27

Prepared as the first PyPI release; the upload was not completed, so the
package will first appear on PyPI with a later version.

### Fixed

- `plot_comparison` spreads converging end-of-line labels apart when the figure
  is drawn, measuring the rendered text height, so the labels no longer overlap
  at small figure sizes such as the app's comparison card.

### Changed

- The documentation guides now execute their examples, so their tables and plots
  appear inline as on a knitted vignette.

## [0.1.0] - 2026-06-24

First release of the reproducible workflow layer over pybliometrics (tagged on
GitHub; superseded by 0.1.1 before any upload to PyPI).

### Added

- Reproducible search plans (`SearchPlan`) that describe a search before
  running it and can be partitioned by year.
- Field-tagged, boolean query builder (`scopus_query`, `wrap_field`) with a
  reference table of Scopus field tags.
- One stable, tidy record schema (`to_records`, `RECORD_COLUMNS`) across query
  types.
- Source and author top tally (`top`).
- DOI extraction and change-tracking between runs (`extract_dois`, `diff_dois`).
- Resumable, checkpointed harvest of a plan (`fetch_plan`).
- Annual publication trends (`scopus_trend`, `year_counts`) computed from cheap
  result-size lookups.
- Batch abstract retrieval, resilient per id (`scopus_abstract`).
- Brand-themed matplotlib plots for trend and top summaries (`plot_trend`,
  `plot_top`).
- Cheap result-size sizing (`scopus_count`) for quota-aware pre-flight.
- Topic-trend comparison (`compare_topics`) and a `plot_comparison` line chart
  with illustrative Wilson stability bands, mirroring the R package.
- Reference-manager export to BibTeX and RIS (`to_bibtex`, `to_ris`), so a
  search carries into Zotero, EndNote, Mendeley or a LaTeX bibliography.
- Per-cell progress logging on the `scopusflow` logger and co-operative
  cancellation (`should_stop`) in `fetch_plan`.
- A local, code-free NiceGUI app (`scopusflow-gui`, the `app` extra) that drives
  the whole workflow through a browser tab. It runs a background harvest with a
  live progress terminal, mirrors every choice back as a runnable Python script,
  shows the result as a table and plots with export, and offers a demo mode that
  needs no key. It is the Python twin of the R package's `run_app()`.

### Changed

- `plot_comparison` labels each line with its total record count by default
  (`counts_in_legend`), names the reference topic in a subtitle, carries a
  Source/Wilson caption (so the band is not misread as a confidence interval)
  and a percent-formatted y-axis, matching the R `plot_scopus_comparison`.
- The app's *Compare topics* card now exposes highlight, stability-band and
  counts-in-label controls, estimates the comparison's count-request cost,
  mirrors the comparison in the reproducible script, and exports the comparison
  table to CSV.
- `compare_topics` logs per-step progress (`Cell k/N: …`, mirroring the R
  `verbose` output), which the app streams into a per-term progress bar and the
  live terminal.

### Fixed

- The app now passes the chosen `view` (`STANDARD`/`COMPLETE`) into the harvest,
  not only into the count pre-flight, comparison and generated script.
- Harvest checkpoints now use a stable key over the whole plan, so a resumed run
  reuses them and two searches that differ only by year no longer collide. They
  are written under the temp directory rather than the working directory and are
  removed when the tab closes, so search terms do not linger on disk.
- The comparison drops duplicate terms, the Check plan button is blocked while a
  harvest runs, the comparison log handler is detached on disconnect, a
  zero-record harvest is reported as a warning rather than a success, and the
  Years range and Detail radio carry visible labels.

[0.2.0]: https://github.com/pablobernabeu/scopusflow-py/releases/tag/v0.2.0
[0.1.0]: https://github.com/pablobernabeu/scopusflow-py/releases/tag/v0.1.0
