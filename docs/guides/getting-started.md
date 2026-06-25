# Getting started

scopusflow turns a Scopus search into a small, reproducible workflow. You describe a search as a plan, size it before spending quota, retrieve it as a resumable harvest, and then work with the records through one stable schema. This guide walks the whole arc once, lightly, and points to the task guides for the detail. Everything that does not contact the API runs offline, and the few steps that need a key are marked as such.

```python exec="1" session="getting-started"
import html as _html
import pandas as pd


def out(x):
    if isinstance(x, pd.DataFrame):
        print(x.to_html(index=False, border=0))
    elif isinstance(x, pd.Series):
        print(x.to_frame("count").to_html(border=0))
    else:
        print("<pre>" + _html.escape(str(x)) + "</pre>")
```

```python exec="1" source="material-block" session="getting-started"
import scopusflow as sf
```

## Describe a search

A query is only a string, but composing it by hand invites a missing bracket or a mistyped tag. [`scopus_query`][scopusflow.query.scopus_query] builds a field-tagged, boolean query and returns the exact string the API will receive, so you can read it before you run it.

```python exec="1" source="material-block" session="getting-started"
q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
out(q)
```

A [`SearchPlan`][scopusflow.plan.SearchPlan] wraps that query in a description you can print, version-control and partition. Partitioning by year keeps each cell small enough to stay under the API's offset ceiling, and it makes the harvest resumable cell by cell.

```python exec="1" source="material-block" session="getting-started"
plan = sf.SearchPlan(q, years=range(2018, 2023), partition="year")
out([(c.cell, c.year) for c in plan.cells()])
```

The [Designing queries](designing-queries.md) and [Search plans and quota](plans-and-quota.md) guides go further into both.

## Size it, then fetch

A count tells you what a harvest will cost before you pay for it. Both calls below contact the Scopus API and need a key configured for pybliometrics, so they are shown here rather than run.

```python
# Both need a configured Scopus key.
sf.scopus_count(q, years=range(2018, 2023))
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)
```

## One stable schema

Whether records come from the API or from data you already hold, they share one schema, the columns named in [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS]. To keep the rest of this guide offline, here is a small frame in that shape standing in for a harvest.

```python exec="1" source="material-block" session="getting-started"
import pandas as pd

records = pd.DataFrame([
    {"entry_number": 1, "scopus_id": "1", "doi": "10.1000/aaa",
     "title": "A reproducible workflow", "authors": "Smith J.;Doe A.",
     "year": 2020, "date": "2020-05-01", "publication": "J. Bibliometrics",
     "citations": 12, "query": q},
    {"entry_number": 2, "scopus_id": "2", "doi": "10.1000/bbb",
     "title": "Quota-aware querying", "authors": "Doe A.",
     "year": 2021, "date": "2021-01-10", "publication": "Scientometrics Today",
     "citations": 3, "query": q},
], columns=sf.RECORD_COLUMNS)
out(records[["title", "year", "publication", "citations"]])
```

[`top`][scopusflow.records.top] tallies the most frequent sources or authors from that frame, counting each contributor once per record.

```python exec="1" source="material-block" session="getting-started"
out(sf.top(records, by="source"))
```

## Carry the work onward

From the one schema the rest of the workflow follows. You can extract a clean DOI list, compare two harvests to see what changed, summarise growth over time and draw it, compare how sub-topics move within a literature, read fuller records, and export to a reference manager.

```python exec="1" source="material-block" session="getting-started"
out(sf.extract_dois(records))
```

Each of these has its own guide. [Building a reference set](building-a-reference-set.md) covers DOIs and export to BibTeX and RIS. [Tracking change over time](tracking-literature-change.md) covers comparing two retrievals. [Analysing a literature](analysing-a-literature.md) covers trends, top sources and authors, and abstracts. [Comparing topics](comparing-topics.md) covers the share of a reference literature each sub-topic holds over time. [The code-free app](the-app.md) does all of it through a browser tab, with no code at all.
