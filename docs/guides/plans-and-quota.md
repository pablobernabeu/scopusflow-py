# Sizing and quotas

The Scopus Search API is generous but bounded. A weekly quota limits how many requests you may make, a rate limit caps how fast you may make them, and no single query will page past its first few thousand records. This guide shows how scopusflow works within those bounds so that a large retrieval stays cheap to plan, honest about its size and resumable when it stops. Every example assumes `import scopusflow as sf`. The steps that count or fetch records contact the API and need a Scopus key configured for pybliometrics, so they are shown rather than run here; building queries and plans is offline and runs anywhere.

## Size before you spend

Counting is cheap. [`scopus_count`][scopusflow.count.scopus_count] issues a single request that asks the API how many records a query matches without downloading any of them, which makes it the right way to size a search before committing quota to a harvest. It takes the same `years` and `field` arguments as a plan, so you can size exactly what you intend to fetch.

```python
import scopusflow as sf

q = sf.scopus_query("language learning", "effect size", field="TITLE-ABS-KEY")

# One cheap request; returns an int. Needs a Scopus key.
n = sf.scopus_count(q, years=range(2010, 2021))
n
```

Because the result is a plain integer you can branch on it before paying for anything heavier, asking whether the search is small enough to fetch in one piece or large enough to need partitioning.

```python
if sf.scopus_count(q) > 5000:
    print("Too large for a single pull; partition by year.")
```

## Why the offset ceiling forces a partition

A single query cannot be paged indefinitely. The API stops serving results once the start offset reaches a few thousand records, so a query matching more than that ceiling can never be retrieved in full from one uninterrupted search. The remedy is to split the search into pieces that each stay under the ceiling, and the year of publication is the natural facet to split on because it is recorded on every record and divides a literature cleanly.

A [`SearchPlan`][scopusflow.plan.SearchPlan] with `partition="year"` does exactly this, turning one oversized search into one cell per year. Each cell carries the same wrapped query and a single year, so each contacts the API as its own bounded search.

```python
plan = sf.SearchPlan(q, years=range(2010, 2021), partition="year")

# One cell per year, each well under the offset ceiling.
[(c.cell, c.year) for c in plan.cells()]
```

The string each cell will send is the `wrapped_query`, with the field tag already folded in. Inspecting it is offline and shows precisely what the API receives before any request is made.

```python
plan.wrapped_query
```

Counting and partitioning compose. Run [`scopus_count`][scopusflow.count.scopus_count] over the same years first, and if the total clears the ceiling you already know the year partition is needed rather than discovering it part way through a fetch.

```python
total = sf.scopus_count(q, years=range(2010, 2021))
plan = sf.SearchPlan(
    q,
    years=range(2010, 2021),
    partition="year" if total > 5000 else "none",
)
```

## A resumable, checkpointed harvest

[`fetch_plan`][scopusflow.fetch.fetch_plan] runs the cells in turn and returns one normalised frame. Given a `cache_dir` it writes each cell to disk as soon as that cell completes, so a run interrupted halfway, or stopped by the quota, resumes from where it left off rather than paying again for the cells that already finished. Resuming is the default, so a second call against the same directory reads the finished cells back from disk and only fetches what is missing.

```python
records = sf.fetch_plan(plan, cache_dir="language-harvest", resume=True)
records.shape
```

The checkpoint format is `parquet` by default and falls back to CSV when no parquet engine is installed. You can ask for CSV explicitly when you want checkpoints you can open in any tool.

```python
records = sf.fetch_plan(plan, cache_dir="language-harvest", format="csv")
```

For a long harvest you can hand `fetch_plan` a zero-argument `should_stop` callable. It is checked before each cell, and when it returns `True` the harvest stops early and returns what it has gathered so far. Because every completed cell is already on disk, stopping this way costs nothing for the work already done, and the next call resumes cleanly.

```python
import time

deadline = time.monotonic() + 600  # stop politely after ten minutes

records = sf.fetch_plan(
    plan,
    cache_dir="language-harvest",
    should_stop=lambda: time.monotonic() > deadline,
)
```

Whatever the query was, the result is one tidy frame with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema, the same shape a single fetch would return, with `entry_number` renumbered across the combined cells.

## Watching progress

Per-cell progress is emitted on the `scopusflow` logger, which is silent by default. Attaching a handler surfaces a line as each cell is fetched or loaded from cache, which is worth doing for a harvest that spans many years.

```python
import logging

logging.getLogger("scopusflow").addHandler(logging.StreamHandler())
logging.getLogger("scopusflow").setLevel(logging.INFO)

records = sf.fetch_plan(plan, cache_dir="language-harvest")
```

## Re-running and tracking change

Pointing a later run at a fresh directory fetches the plan again, and comparing the two DOI sets with [`diff_dois`][scopusflow.diff.diff_dois] shows what the literature gained or lost in between. The earlier checkpoints stay untouched, so the original harvest remains exactly as it was.

```python
later = sf.fetch_plan(plan, cache_dir="language-harvest-2")
sf.diff_dois(old=records, new=later)
```
