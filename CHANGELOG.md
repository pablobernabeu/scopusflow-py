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
- Minimal matplotlib plots for trend and top summaries (`plot_trend`,
  `plot_top`).

[0.1.0.dev0]: https://github.com/pablobernabeu/scopusflow-py
