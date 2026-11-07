# Search plans and quota-aware retrieval

The Elsevier Scopus Search API bounds a retrieval in three ways. A weekly quota limits how many requests you may make, a short-term rate limit caps how fast you may make them, and offset paging stops at the first 5000 records of a query. This guide shows how scopusflow works within those bounds to make a large retrieval cheap to plan, accurate about its size and resumable when it stops. Every example assumes `import scopusflow as sf`. The steps that count or fetch records contact the API and need a Scopus key configured for pybliometrics, so they are shown but not run here. Building queries and plans is offline and runs anywhere.

```python exec="1" session="plans-and-quota"
import html as _html
import pandas as pd
import scopusflow as sf


def _clean_table(html_table):
    # Drop pandas' own class and header alignment so the theme's table
    # styling (padding, borders, the navy header band) applies instead.
    return (html_table.replace(' class="dataframe"', "")
                      .replace(' style="text-align: right;"', ""))


def out(x):
    if isinstance(x, pd.DataFrame):
        print(_clean_table(x.to_html(index=False, border=0)))
    elif isinstance(x, pd.Series):
        label = x.index.name or "value"
        df = x.rename("count").reset_index()
        df.columns = [label, "count"]
        print(_clean_table(df.to_html(index=False, border=0)))
    else:
        print("<pre><code>" + _html.escape(str(x)) + "</code></pre>")

q = sf.scopus_query("language learning", "effect size", field="TITLE-ABS-KEY")
```

## Size before you spend

Counting is cheap. [`scopus_count`][scopusflow.count.scopus_count] issues a single request that asks the API how many records a query matches without downloading any of them. Use it to size a search before committing quota to a harvest. It takes the same `years` and `field` arguments as a plan, so you can size what you intend to fetch. It counts the years as one inclusive range from the earliest to the latest, as an unpartitioned plan sends them. For a year-partitioned plan over years with gaps between them, such as `[2015, 2020]`, it therefore also counts the years between.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

q = sf.scopus_query("language learning", "effect size", field="TITLE-ABS-KEY")

# One cheap request; returns an int. Needs a Scopus key.
n = sf.scopus_count(q, years=range(2010, 2021))
n
```

Because the result is a plain integer, you can branch on it before spending more quota, for instance to check whether the search fits within the 5000 records that offset paging can retrieve.

```python
if sf.scopus_count(q) > 5000:
    print("More than offset paging can retrieve in one piece. Page by cursor or partition.")
```

## Why partition by year

A [`SearchPlan`][scopusflow.plan.SearchPlan] with `partition="year"` turns one search into one cell per year. Each cell carries the same wrapped query and a single year, so it contacts the API as a search of its own. A finished year is checkpointed, so an interrupted harvest resumes from the first unfinished one. Each year's row count is checked against the total the API reports for it, so a shortfall is traced to the year in which it occurred. A long harvest also reports its progress year by year.

The year of publication is the natural facet to split on, because it is recorded on every record and divides a literature without leaving gaps or overlaps. The plan is a plain object that describes the search before it is run, so it can be printed and version-controlled alongside the analysis.

```python exec="1" source="material-block" session="plans-and-quota"
plan = sf.SearchPlan(q, years=range(2010, 2021), partition="year")

# One cell per year, each fetched, checkpointed and checked on its own.
out([(c.cell, c.year) for c in plan.cells()])
```

Each cell sends the `wrapped_query`, with the field tag already applied, and appends its own year, as `AND PUBYEAR IS 2010` for the first cell. A query with a top-level OR, AND NOT or proximity operator is put in brackets before the year is added, so the limit applies to all of it. Inspecting the query is offline, so you can read what each cell will ask for before any request is made.

```python exec="1" source="material-block" session="plans-and-quota"
out(plan.wrapped_query)
```

The partition matters most under offset paging. By default, [`fetch_plan`][scopusflow.fetch.fetch_plan] pages each cell by cursor, and a cursor retrieves a cell of any size. Given `cursor=False`, it pages by offset instead, the route pybliometrics documents for keys without a Scopus subscription. Offset paging cannot retrieve a search that matches more than 5000 records. pybliometrics raises a `ScopusQueryError` for such a cell after one request, and `fetch_plan` raises it again with the cell named. Under offset paging, the partition is therefore what makes a large search retrievable, and each year has to stay under the ceiling on its own.

Before an offset-paged harvest, run [`scopus_count`][scopusflow.count.scopus_count] over the same years. If the total exceeds 5000, you know before any fetch begins that the year partition is needed. [`scopus_trend`][scopusflow.trend.scopus_trend] counts the years one by one, which also shows whether any single year exceeds the ceiling.

```python
total = sf.scopus_count(q, years=range(2010, 2021))
plan = sf.SearchPlan(
    q,
    years=range(2010, 2021),
    partition="year" if total > 5000 else "none",
)
records = sf.fetch_plan(plan, cursor=False)
```

The R twin's `scopus_fetch_plan()` pages by offset unless given `cursor = TRUE`. Each twin keeps the default it has always had, since a checkpoint records the paging mode it was fetched under and serves only a harvest in the same mode. A changed default would refetch every cell of every existing cache, each with a warning that names both modes.

## A resumable, checkpointed harvest

[`fetch_plan`][scopusflow.fetch.fetch_plan] runs the cells in turn and returns one normalised frame. Given a `cache_dir`, it writes each cell to disk as it completes, so a run interrupted halfway, or stopped by the quota, resumes from where it left off and never spends quota twice on the same cell. Resuming is the default, so a second call against the same directory reads the finished cells back from disk and only fetches what is missing.

```python
records = sf.fetch_plan(plan, cache_dir="language-harvest", resume=True)
records.shape
```

A cache directory belongs to one plan. Checkpoints are keyed by cell number, and each is written with a manifest beside it, `cell-001.json` for the first cell. The manifest records the query as sent, the view, the page size and the paging mode. On resume, a checkpoint is served only when all four match the cell, so a checkpoint written by a different plan is warned about and refetched. The check also covers a cell that found nothing, whose empty checkpoint holds no records to show which search wrote it. Give each plan its own directory all the same, since that refetch spends the quota the cache was meant to save.

The manifest also records the cell's reported total, the time it was retrieved and the scopusflow version. A harvest resumed from its checkpoints is therefore dated, and its completeness stated, in the [search record](#writing-the-search-up). It is dated from its first cell's retrieval to its last cell's, so a harvest finished days after it began gives the date of its last search, as PRISMA-S asks.

Checkpoints written by earlier versions of scopusflow have no manifest. A non-empty one is still served when the query and view its records carry match the cell and the harvest is paged by cursor, as every earlier version paged. It comes without a total, time or version, so the search record reports those as unrecorded. An empty one is fetched again, at one request per cell, and the harvest warns once.

The checkpoint format is `parquet` by default and falls back to CSV when no parquet engine is installed. You can ask for CSV explicitly when you want checkpoints you can open in any tool.

```python
records = sf.fetch_plan(plan, cache_dir="language-harvest", format="csv")
```

For a long harvest, you can pass `fetch_plan` a zero-argument `should_stop` callable. It is checked before each cell, and when it returns `True`, the harvest stops early and returns what it has gathered so far. Because every completed cell is on disk, stopping this way costs nothing for the work already done, and the next call resumes from the first unfinished cell.

```python
import time

deadline = time.monotonic() + 600  # stop politely after ten minutes

records = sf.fetch_plan(
    plan,
    cache_dir="language-harvest",
    should_stop=lambda: time.monotonic() > deadline,
)
```

A harvest stopped this way records `attrs["stopped_early"]`, with the number of cells planned and the number run, and carries no overall total, since the cells it never reached were never counted. Its [search record](#writing-the-search-up) gives the cells and years that were searched, marks the rest 'not run' and calls the harvest incomplete.

The frame `fetch_plan` returns has the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema, the same shape a single fetch would return, with `entry_number` renumbered across the combined cells.

## Writing the search up

A harvest is rarely the end of the work. A systematic review has to report the search itself, in enough detail that a reader can repeat it, and the reporting standard for that is PRISMA-S ([Rethlefsen et al., 2021](https://doi.org/10.1186/s13643-020-01542-z)). [`scopus_search_report`][scopusflow.report.scopus_search_report] assembles the search record from what the plan and the harvest already carry.

A plan on its own can be reported before it is run, which is useful when a protocol has to be registered in advance. The plan below describes a Scopus search for the phrase the bundled corpus was drawn on. The corpus itself came from OpenAlex's exact-phrase search for 'graphene supercapacitor' in titles and abstracts, limited to journal articles, on 22 July 2026. A Scopus run of this plan would return a different set of records. The query puts the two words in quotation marks so that Scopus searches them as a phrase. Without the quotation marks, Scopus would join the two words with AND, and in OpenAlex the unquoted words match about a hundred times as many records.

```python exec="1" source="material-block" session="plans-and-quota"
graphene = sf.SearchPlan('"graphene supercapacitor"', years=range(2015, 2025),
                         field="TITLE-ABS-KEY", partition="year")
out(sf.scopus_search_report(graphene))
```

Much of the record says 'unrecorded'. Nothing has been retrieved yet, so there is nothing to state, and the record says so in words because a blank would be read as a zero. Throughout, the record states only what the objects hold. It never substitutes the current time for a retrieval that did not record one, never gives a completeness figure for a harvest whose reported total is unknown, and never counts duplicates unless a merge recorded removing them.

After a harvest, the record fills in. `fetch_plan` attaches the plan, the retrieval time, the version, the paging mode and the per-cell accounting, and you never set any of them yourself. Here, the bundled corpus stands in for a harvest, since Scopus records may not be redistributed. Those attributes are therefore written out below to show what each one contributes. Their values are illustrative, so the record they produce describes no search that was run. The retrieval time and the version are set by hand. Each cell's reported total is the number of bundled records in its year, a count from the OpenAlex search that the Scopus API never gave.

```python exec="1" source="material-block" session="plans-and-quota"
from datetime import datetime, timezone

# Illustrative values, set by hand. No Scopus search was run.
records = sf.example_records()
records.attrs["plan"] = graphene
records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
records.attrs["scopusflow_version"] = "0.3.0"
records.attrs["paging"] = "cursor"
per_year = records.groupby("year").size()
records.attrs["cell_totals"] = pd.DataFrame({
    "cell": range(1, len(per_year) + 1),
    "date": [str(y) for y in per_year.index],
    "n_records": per_year.values,
    "reported_total": per_year.values,
})

report = sf.scopus_search_report(records)
out(report)
```

The completeness lines show each cell against the number of records the API reported for it, so a cell that came back short stays visible where a total would have hidden it. The overall figure is given only because every cell reported one. Drop any of those attributes and the corresponding line says so instead.

The methods paragraph is the same record as prose, ready to paste into a manuscript and edit.

```python exec="1" source="material-block" session="plans-and-quota"
out(report.format(style="paragraph"))
```

Supplying a `file` writes the whole record as Markdown, including a runnable snippet that rebuilds the plan. The file can serve as supplementary material.

```python
sf.scopus_search_report(records, file="search-record.md")
```

Six of the sixteen PRISMA-S items are answered here from the objects, and a seventh, de-duplication, would be too had these records been merged with [`scopus_combine`][scopusflow.combine.scopus_combine]. The rest, among them peer review of the strategy and grey literature, are listed as yours to supply, because the objects do not record them. Any other database the review searched is yours to name as well.

## Watching progress

Per-cell progress is emitted on the `scopusflow` logger, which is silent by default. For a harvest that spans many years, it is worth attaching a handler, which prints a line as each cell is fetched or loaded from cache.

```python
import logging

logging.getLogger("scopusflow").addHandler(logging.StreamHandler())
logging.getLogger("scopusflow").setLevel(logging.INFO)

records = sf.fetch_plan(plan, cache_dir="language-harvest")
```

## Re-running and tracking change

Pointing a later run at a fresh directory fetches the plan again and leaves the earlier checkpoints untouched. Comparing the two DOI sets with [`diff_dois`][scopusflow.diff.diff_dois] then shows which DOIs were added or removed in between.

```python
later = sf.fetch_plan(plan, cache_dir="language-harvest-2")
sf.diff_dois(old=records, new=later)
```

Two caches are involved here, and only one of them is scopusflow's. The checkpoints in `cache_dir` let an interrupted harvest resume. pybliometrics keeps a response cache of its own, in the directories its configuration names, and stores each search there in a file keyed by its query string and view alone. With its default settings, pybliometrics would serve the later run from that file without contacting the API, and the comparison would set the harvest against a copy of itself, dated now and reported as complete. scopusflow therefore sends `refresh=True` with every search unless you pass `refresh` yourself, so the later run spends as much quota as the first.

Passing `refresh=False` opts in to pybliometrics' cache, and a number of days opts in for cache files younger than that. A cell served from the cache is dated by its cache file, reports no total and comes with a warning. The counting functions [`scopus_count`][scopusflow.count.scopus_count], [`scopus_trend`][scopusflow.trend.scopus_trend], [`compare_topics`][scopusflow.compare.compare_topics] and [`scopus_intersections`][scopusflow.intersections.scopus_intersections] follow the same rule. A count they take from the cache is the number of rows an earlier harvest of the same query left there, and it is warned about in the same way. The cache key ignores keyword arguments such as `subj` or `date`, so put any filter in the query before you opt in. The [pybliometrics reference for `ScopusSearch`](https://pybliometrics.readthedocs.io/en/stable/reference/scopus/ScopusSearch.html) describes the cache and its `refresh` argument.
