# scopusflow (Python)

scopusflow is a reproducible workflow layer over [pybliometrics](https://pybliometrics.readthedocs.io) for Scopus searches. It is the Python twin of the R package [scopusflow](https://pablobernabeu.github.io/scopusflow/) and follows the same design, so a search written in one language reads much the same in the other.

This is an early release (version `0.1.0`), covered by an offline test suite. The retrieval path is a thin driver over pybliometrics, so before you lean on it for a large live harvest it is worth a short trial run against your installed version.

## Why this exists

pybliometrics is the mature way to reach the Scopus API from Python. It wraps around ten endpoints and handles the HTTP, cursor pagination, weekly-quota rotation and per-query caching. What it does not provide is a workflow on top of that plumbing. There is no declarative search plan, no single record schema that stays the same across query types, no resumable harvest with checkpoints, no DOI change-tracking between runs, and nothing ready-made for trends, topic comparisons, abstracts or plots. Researchers tend to hand-roll those around pybliometrics, and that is the work scopusflow takes on. It depends on pybliometrics rather than re-implementing the plumbing that already works well.

| | pybliometrics | scopusflow |
|---|---|---|
| Reach the API (search, retrieval, quota, cursor, cache) | yes | delegates to pybliometrics |
| Declarative, reproducible search plan | no | yes |
| One stable record schema across query types | no | yes |
| Resumable, checkpointed harvest of a plan | no | yes |
| DOI extraction and change-tracking between runs | no | yes |
| Annual publication trends without downloading records | no | yes |
| Topic-trend comparison with stability bands | no | yes |
| Batch abstract retrieval, resilient per id | no | yes |
| Trend and top-source/author plots | no | yes |
| Export to reference managers (BibTeX, RIS) | no | yes |

The other Python options are not live alternatives. elsapy was archived as read-only in January 2025, and pyscopus has had no release since 2018.

## Install

You need a Scopus API key configured for pybliometrics, in its standard `~/.config/pybliometrics.cfg`.

```bash
pip install scopusflow
```

The optional extras add the figures and the app. Install `scopusflow[plot]` for the matplotlib plots and `scopusflow[app]` for the code-free app. To work on the package itself, install from a clone with `pip install -e ".[dev,plot]"`.

## A first search

The example below builds a query, plans a harvest partitioned by year, retrieves it with caching, and then draws on the stable record schema for everything that follows.

```python
import scopusflow as sf

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2010, 2023), partition="year")

records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

sf.top(records, by="source")
dois = sf.extract_dois(records)
```

Re-running the same plan later and comparing the two retrievals shows which records have appeared or disappeared in the meantime.

```python
later = sf.fetch_plan(plan, cache_dir="harvest2")
sf.diff_dois(old=records, new=later)
```

The publication trend can be tallied from a harvest you already hold, or fetched directly as cheap per-year result-size lookups that never download the records themselves.

```python
trend = sf.year_counts(records)
trend = sf.scopus_trend(q, years=range(2010, 2023))
```

A topic comparison shows how sub-topics grow within the reference literature over time. The abstract and export helpers carry the work onward into reading and into a reference manager.

```python
cmp = sf.compare_topics(q, ["lithium-ion", "sodium-ion"], years=range(2015, 2023))
sf.plot_comparison(cmp)

abstracts = sf.scopus_abstract(dois[:10], by="doi")

with open("scopus-records.bib", "w", encoding="utf-8") as fh:
    fh.write(sf.to_bibtex(records))
```

The pure-logic helpers (`scopus_query`, `SearchPlan`, `to_records`, `top`, `extract_dois`, `diff_dois`, `year_counts`) need no API key and are exercised by the offline tests. The helpers that call pybliometrics (`fetch_plan`, `scopus_trend`, `scopus_abstract`, `compare_topics`) need a key, and the plots need the optional `plot` extra.

## A code-free app

A local [NiceGUI](https://nicegui.io) app drives the whole workflow without writing code, and mirrors every choice back as a runnable Python script, so it works as an on-ramp to the package rather than a replacement. It runs on your own machine, so your API key never leaves it, and a demo mode lets you try the flow with synthetic data and no key at all.

```bash
pip install "scopusflow[app]"
scopusflow-gui
```

The retrieval runs in the background with a live progress terminal. Results appear as a paginated table and a pair of plots with one-click export, and a Compare topics card draws the same comparison figure the library produces. It is the Python twin of the R package's `scopusflow::run_app()`.

## Licence

MIT. Scopus is a trademark of Elsevier. This is an independent client and is not affiliated with or endorsed by Elsevier.
