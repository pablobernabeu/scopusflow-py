# Get started

scopusflow turns a Scopus search into a small, reproducible workflow. You describe a search as a plan, size it before spending quota, retrieve it as a resumable harvest, and then work with the records through one stable schema. This guide walks the whole arc once, lightly, and points to the task guides for the detail. Everything that does not contact the API runs offline, and the few steps that need a key are marked as such.

```python exec="1" session="getting-started"
import html as _html
import pandas as pd


def _clean_table(html_table):
    # Drop pandas' own class and header alignment so the theme's table
    # styling (padding, borders, zebra rows) applies instead.
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
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")
out([(c.cell, c.year) for c in plan.cells()])
```

The [Designing queries](designing-queries.md) and [Search plans and quota](plans-and-quota.md) guides go further into both.

## Size it, then fetch

A count tells you what a harvest will cost before you pay for it. Both calls below contact the Scopus API and need a key configured for pybliometrics, so they are shown here rather than run.

```python
# Both need a configured Scopus key.
sf.scopus_count(q, years=range(2015, 2025))
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)
```

## The bundled harvest

Whether records come from the API or from data you already hold, they share one schema, the columns named in [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS]. So that the rest of this guide, and every other page on this site, runs without a key, the package ships a worked example in exactly that shape. [`example_records`][scopusflow.data.example_records] returns it.

```python exec="1" source="material-block" session="getting-started"
records = sf.example_records()
out(records[["title", "year", "publication", "citations"]].head())
```

Those are real journal articles on graphene supercapacitors, 138 of them published between 2015 and 2024, carrying their real titles, DOIs, journals, first authors and citation counts. They are deliberately not a Scopus harvest, and no package can ship one, because Elsevier's API terms do not permit redistributing the records a key retrieves. These come instead from OpenAlex, whose metadata is released under CC0 and may therefore travel with the package, reshaped into the schema [`fetch_plan`][scopusflow.fetch.fetch_plan] returns. Run the query above against Scopus and you get a frame of the same shape, with the same columns and the same handling, though not an identical set of records.

Two consequences are worth knowing before the examples below. The harvest is complete rather than sampled, so the number of rows in a year is the number of publications the query matched that year, and a trend drawn from it is a real publication curve. And `scopus_id` is empty throughout, these records not having come from Scopus, so anything that would key on the Scopus identifier falls back to the DOI. Eleven records carry no DOI and two no source title, left exactly as they arrive, because a real harvest has gaps of the same kind.

[`top`][scopusflow.records.top] tallies the most frequent sources or authors from the frame, counting each contributor once per record.

```python exec="1" source="material-block" session="getting-started"
out(sf.top(records, by="source", n=5))
```

## Carry the work onward

From the one schema the rest of the workflow follows. You can extract a clean DOI list, compare two harvests to see what changed, summarise growth over time and draw it, compare how sub-topics move within a literature, read fuller records, and export to a reference manager.

```python exec="1" source="material-block" session="getting-started"
dois = sf.extract_dois(records)
out((len(dois), dois[:3]))
```

The list is 127 entries long rather than 138, because the eleven records without a DOI are dropped rather than carried through as blanks.

Each of these has its own guide. [Building a reference set](building-a-reference-set.md) covers DOIs and export to BibTeX and RIS. [Tracking change over time](tracking-literature-change.md) covers comparing two retrievals. [Analysing a literature](analysing-a-literature.md) covers trends, top sources and authors, and abstracts. [Comparing topics](comparing-topics.md) covers the share of a reference literature each sub-topic holds over time. [Author keywords and references](keywords-and-references.md) covers retrieving a document's own keywords and reference list, and assembling a minimal corpus from them, both at a materially different quota cost from an ordinary search. [The code-free app](the-app.md) does all of it through a browser tab, with no code at all.
