# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0.dev0]

Initial scaffold of the reproducible workflow layer over pybliometrics.

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

[0.1.0.dev0]: https://github.com/pablobernabeu/scopusflow-py
