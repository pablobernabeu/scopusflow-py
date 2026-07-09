# scopusflow <span class="mrd-lang">(Python)</span>

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21252666.svg)](https://doi.org/10.5281/zenodo.21252666)

<p class="mrd-tagline">A reproducible workflow layer over <a href="https://pybliometrics.readthedocs.io">pybliometrics</a> for Scopus searches.</p>

This is the feature-parity twin of [the R package](https://pablobernabeu.github.io/scopusflow/) of the same name, and follows the same design, keeping a search reproducible and its results legible across both languages.

[Get started](guides/getting-started.md){ .md-button .md-button--primary }
[Try the code-free app](guides/the-app.md){ .md-button }

!!! note "Status"
    scopusflow is at version `0.2.0` and carries an offline test suite. Its retrieval and abstract drivers are thin layers over pybliometrics, so a short trial run against your installed version is worth doing before a large live harvest.

## Why this exists

pybliometrics is the mature way to reach the Scopus API from Python. It wraps around ten endpoints and handles the HTTP, cursor pagination, weekly-quota rotation and per-query caching. What it does not provide is a workflow on top of that plumbing, such as a declarative search plan, a single record schema that holds across query types, a resumable harvest with checkpoints, or DOI change-tracking between runs. scopusflow fills that gap, and depends on pybliometrics rather than re-implementing the plumbing it already does well.

| | pybliometrics | scopusflow |
|---|---|---|
| Reach the API (search, retrieval, quota, cursor, cache) | yes | delegates |
| Declarative, reproducible search plan | no | yes |
| One stable record schema across query types | no | yes |
| Resumable, checkpointed harvest of a plan | no | yes |
| DOI extraction and change-tracking between runs | no | yes |
| Annual publication trends without downloading records | no | yes |
| Topic-trend comparison with stability bands | no | yes |
| Batch abstract retrieval, resilient per id | no | yes |
| Trend and top-source/author plots | no | yes |
| Export to reference managers (BibTeX, RIS) | no | yes |
| Minimal, uniform keyword/reference corpus export | delegates | yes |

The other Python options are not live alternatives. elsapy was archived as read-only in January 2025, and pyscopus last saw a release in January 2019.

## Install

```bash
pip install scopusflow          # add [plot] for figures, [app] for the code-free app
```

A Scopus API key configured for pybliometrics, in its standard `~/.config/pybliometrics.cfg`, is needed only for the steps that contact the API.

## A first search

```python
import scopusflow as sf

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2010, 2023), partition="year")

records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

sf.top(records, by="source")
dois = sf.extract_dois(records)

later = sf.fetch_plan(plan, cache_dir="harvest2")
sf.diff_dois(old=records, new=later)

trend = sf.scopus_trend(q, years=range(2010, 2023))
sf.plot_trend(trend)
```

The [guides](guides/planning-a-harvest.md) give worked walk-throughs of each part of the workflow, from designing a query to comparing topics and exporting the result. The [reference](reference/plan-and-query.md) documents the full API.

If scopusflow contributes to published work, please [cite it](about.md#citing-scopusflow).
