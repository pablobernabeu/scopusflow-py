# scopusflow

A reproducible **workflow layer over [pybliometrics](https://pybliometrics.readthedocs.io)**
for Scopus searches. It is the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/).

!!! note "Status"
    Early scaffold (`0.1.0.dev0`). The pure-logic parts — plans, query building,
    the record schema, DOI diffing, trends — work today and are covered by the
    offline tests. The live `fetch_plan` and `scopus_abstract` drivers are thin
    layers over pybliometrics; confirm them against your installed version.

## Why this exists

pybliometrics is the mature, well-maintained way to *reach* the Scopus API in
Python: it wraps about ten endpoints and handles HTTP, cursor pagination,
weekly-quota rotation and per-query caching. It does **not** give you a
*workflow* — a declarative search plan, a single stable record schema across
query types, a resumable project-level harvest with checkpoints, or DOI
change-tracking between runs. scopusflow fills exactly that gap, and deliberately
depends on pybliometrics rather than re-implementing the plumbing it already does
well.

| | pybliometrics | scopusflow |
|---|---|---|
| Reach the API (search, retrieval, quota, cursor, cache) | :material-check: | delegates |
| Declarative, reproducible search plan | — | :material-check: |
| One stable tidy record schema across query types | — | :material-check: |
| Resumable, checkpointed harvest of a plan | — | :material-check: |
| DOI extraction + change-tracking between runs | — | :material-check: |
| Annual publication trends without downloading records | — | :material-check: |
| Batch abstract retrieval, resilient per id | — | :material-check: |
| Ready-made trend and top-source/author plots | — | :material-check: |

The other Python options are not live competitors: `elsapy` was archived
(read-only, January 2025) and `pyscopus` has had no release since 2018.

## Install

```bash
pip install scopusflow            # once published
pip install -e ".[dev,plot]"      # from a clone, for development
```

A Scopus API key configured for pybliometrics (its standard
`~/.config/pybliometrics.cfg`) is needed only for the live steps.

## Quick start

```python
import scopusflow as sf

# Build a field-tagged query and a reproducible, year-partitioned plan.
q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2010, 2023), partition="year")

# Harvest it, caching each year so an interrupted run resumes.
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

# A stable schema feeds the rest.
sf.top(records, by="source")
dois = sf.extract_dois(records)

# Re-run later and see exactly what changed.
later = sf.fetch_plan(plan, cache_dir="harvest2")
sf.diff_dois(old=records, new=later)

# Publication trend, then a figure (needs the optional `plot` extra).
trend = sf.scopus_trend(q, years=range(2010, 2023))
sf.plot_trend(trend)
```

See the [guides](guides/planning-a-harvest.md) for worked walk-throughs, and the
[reference](reference/plan-and-query.md) for the full API.
