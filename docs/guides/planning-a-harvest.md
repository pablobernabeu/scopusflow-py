# Planning a harvest

A harvest is most reproducible when the search is described before it is run. A [`SearchPlan`][scopusflow.plan.SearchPlan] holds that description. It is an object you can print, version-control and partition, so that a large retrieval stays under the API's offset ceiling and can be cached and resumed.

## Describe the search

```python
import scopusflow as sf

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2023), partition="year")

# One cell per year, each carrying the wrapped query and the year.
[(c.cell, c.year) for c in plan.cells()]
```

Partitioning by year keeps each cell small. The wrapped query is the same string the API will receive.

```python
plan.wrapped_query
```

## Run it, with checkpoints

[`fetch_plan`][scopusflow.fetch.fetch_plan] drives pybliometrics one cell at a time. When you give it a `cache_dir`, each cell is written to disk as it completes, so an interrupted or quota-limited run resumes without re-fetching the cells that already finished.

```python
records = sf.fetch_plan(plan, cache_dir="graphene-harvest", resume=True)
records.shape
```

The result is one tidy frame with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema, whatever the query was.

## Track what changed

Re-running the plan later and comparing the DOI sets shows what the literature gained or lost in between.

```python
later = sf.fetch_plan(plan, cache_dir="graphene-harvest-2")
sf.diff_dois(old=records, new=later)
```
