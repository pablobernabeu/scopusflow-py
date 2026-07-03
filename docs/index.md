# scopusflow

scopusflow is a reproducible workflow layer over [pybliometrics](https://pybliometrics.readthedocs.io) for Scopus searches. It is the Python twin of the R package [scopusflow](https://pablobernabeu.github.io/scopusflow/) and follows the same design.

!!! note "Status"
    This is an early release (`0.1.1`), covered by an offline test suite. The retrieval and abstract drivers are thin layers over pybliometrics, so a short trial run against your installed version is worth doing before a large live harvest.

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

The other Python options are not live alternatives. elsapy was archived as read-only in January 2025, and pyscopus has had no release since 2018.

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
