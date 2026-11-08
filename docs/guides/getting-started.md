# Get started

scopusflow turns a Scopus search into a reproducible workflow. You describe a search as a plan, size it before spending quota, retrieve it as a resumable harvest and then work with the records through one stable schema. This guide covers each step briefly and points to the task guides for the detail. Everything that does not contact the API runs offline, and the few steps that need a key are marked as such.

```python exec="1" session="getting-started"
import html as _html
import pandas as pd


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
```

```python exec="1" source="material-block" session="getting-started"
import scopusflow as sf
```

## Describe a search

A query is only a string, but composing it by hand risks a missing bracket or a mistyped tag. [`scopus_query`][scopusflow.query.scopus_query] builds a field-tagged, boolean query and returns it as a plain string that you can read before you run it. A count or a harvest sends that string with any year limit appended.

```python exec="1" source="material-block" session="getting-started"
q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
out(q)
```

A [`SearchPlan`][scopusflow.plan.SearchPlan] wraps that query in a description you can print, version-control and partition. Partitioning by year makes the harvest resumable cell by cell and checks each year against the API's own count. Under offset paging, partitioning also keeps each cell under the API's 5000-record ceiling, provided that no single year matches more than 5000 records.

```python exec="1" source="material-block" session="getting-started"
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")
out([(c.cell, c.year) for c in plan.cells()])
```

The [Designing queries](designing-queries.md) and [Search plans and quota-aware retrieval](plans-and-quota.md) guides go further into both.

## Size it, then fetch

A count tells you what a harvest will cost before you spend any quota on it. Both calls below contact the Scopus API and need your key, so they are shown here but not run. pybliometrics reads the key from its configuration file only when `pybliometrics.init()` is called, once in every session, and the first call creates that file and asks for the key. A search made before it raises [`ScopusFlowConfigError`][scopusflow.exceptions.ScopusFlowConfigError].

```python
import pybliometrics

pybliometrics.init()   # once per session, before the first search

sf.scopus_count(q, years=range(2015, 2025))
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)
```

## The bundled harvest

Whether records come from the API or from data you already hold, they share one schema, the columns named in [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS]. So that this guide and every other page on this site can run without a key, the package bundles a harvest in that schema. [`example_records`][scopusflow.data.example_records] returns it.

```python exec="1" source="material-block" session="getting-started"
records = sf.example_records()
out(records[["title", "year", "publication", "citations"]].head())
```

The harvest holds 138 real journal articles on graphene supercapacitors published between 2015 and 2024, with their titles, DOIs, journals, first authors and citation counts. Elsevier's API terms do not permit redistributing retrieved records, so no package can include a Scopus harvest. These records come from OpenAlex, whose metadata is released under CC0 and may therefore be distributed with the package. They are reshaped into the schema [`fetch_plan`][scopusflow.fetch.fetch_plan] returns. OpenAlex's exact-phrase search for 'graphene supercapacitor' in titles and abstracts, limited to journal articles, returned them on 22 July 2026.

The harvest is complete, so the number of rows in a year is the number of publications that search matched that year, and a trend drawn from it is the publication curve of that search. Because these records did not come from Scopus, `scopus_id` is empty throughout, and anything that would match records on the Scopus identifier falls back to the DOI. Eleven records carry no DOI and two no source title, left as they arrive, because a live harvest has gaps of the same kind.

A Scopus search returns a frame of the same shape, with the same columns and the same handling, but a different set of records. The query above matches far more than the phrase, since it joins the two words with AND. In OpenAlex, the two words joined that way match about a hundred times as many records.

[`top`][scopusflow.records.top] tallies the most frequent sources or authors from the frame, counting each contributor once per record.

```python exec="1" source="material-block" session="getting-started"
out(sf.top(records, by="source", n=5))
```

## Carry the work onward

The rest of the workflow uses the same schema. You can extract a clean DOI list, compare two retrievals to see what changed, summarise growth over time and draw it, compare how sub-topics move within a literature, read fuller records, export to a reference manager, and write the search up for a methods section.

```python exec="1" source="material-block" session="getting-started"
dois = sf.extract_dois(records)
out((len(dois), dois[:3]))
```

Eleven of the 138 records arrived without a DOI and are dropped, so 127 come back.

Each of those tasks has its own guide. [Building a reference set](building-a-reference-set.md) covers DOIs and export to BibTeX and RIS. [Tracking change over time](tracking-literature-change.md) covers comparing two retrievals. [Analysing a literature](analysing-a-literature.md) covers trends, top sources and authors, and abstracts. [Comparing topics](comparing-topics.md) covers the share of a reference literature each sub-topic holds over time. [Author keywords and references](keywords-and-references.md) covers retrieving a document's own keywords and reference list, both at a materially different quota cost from an ordinary search, and assembling a minimal corpus from them. [Search plans and quota-aware retrieval](plans-and-quota.md) covers the resumable harvest and the PRISMA-S record of the search. [The code-free app](the-app.md) covers planning, retrieval, export, the PRISMA-S record of the search and the trend, top and comparison analyses in a browser tab.
