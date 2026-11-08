# Analysing a literature

Once records are in hand, scopusflow turns them into the figures a bibliometric study usually needs, all from the one stable schema. The examples here run on the harvest bundled with the package, which holds 138 real articles on graphene supercapacitors published between 2015 and 2024. It stands in for a Scopus retrieval because retrieved records cannot be redistributed, and it lets every figure on this page be drawn without a key. A live harvest of the same phrase is shown alongside. [Get started](getting-started.md#the-bundled-harvest) gives the fuller account of where the bundled harvest comes from.

```python exec="1" session="analysing-a-literature"
import html as _html
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import scopusflow as sf
from io import StringIO


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


def show():
    plt.tight_layout()
    plt.gcf().canvas.draw()  # let the label de-collision settle before saving
    buffer = StringIO()
    # Transparent so the page background shows through in both colour schemes;
    # matplotlib otherwise paints an opaque white figure and axes patch.
    plt.savefig(buffer, format="svg", transparent=True)
    plt.close()
    print(buffer.getvalue())
```

## Where the records come from

For a live harvest, you build a query and a plan, and run the plan through [`fetch_plan`][scopusflow.fetch.fetch_plan]. Only that last step contacts the API and needs a configured key.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

q = sf.scopus_query('"graphene supercapacitor"', field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")
records = sf.fetch_plan(plan, cache_dir="graphene-harvest")
```

[`example_records`][scopusflow.data.example_records] returns the bundled harvest, already normalised into the same schema, and the rest of this page works on it. Its records came from OpenAlex's exact-phrase search for the same phrase in titles and abstracts, limited to journal articles, so the harvest above would return a different set. Without the quotation marks, the harvest above would be far larger, since Scopus joins the words of an unquoted phrase with AND, and in OpenAlex the unquoted words match about a hundred times as many records.

```python exec="1" source="material-block" session="analysing-a-literature"
records = sf.example_records()
out(records[["title", "year", "publication", "citations"]].head(3))
```

## What is in a record set

[`top`][scopusflow.records.top] tallies the most frequent sources or authors. Author strings that hold several names are split, so each contributor is counted once per record.

```python exec="1" source="material-block" session="analysing-a-literature"
out(sf.top(records, by="source", n=5))
out(sf.top(records, by="author", n=6))
```

The source tally has a long tail, as a topic literature usually does. *ACS Applied Materials & Interfaces* heads it with eight records, while 77 of the 90 journals represented appear only once or twice. The two records with no source title are left out of the tally.

## How a literature grows

[`year_counts`][scopusflow.trend.year_counts] is the offline tally of records per year from a set you already hold. Because the bundled harvest is complete for its OpenAlex search, these counts are the publications that search matched in each year. A year without records is counted as zero, so a trend never runs straight across an empty year. For a harvest of your own, the counts cover the years its plan searched, and a year no cell searched is left out unless a record carries it.

```python exec="1" source="material-block" session="analysing-a-literature"
trend = sf.year_counts(records)
out(trend)
```

[`scopus_trend`][scopusflow.trend.scopus_trend] asks the API for the count in each year without downloading the records, which is far cheaper when all you want is the shape of the growth. It needs a key, so it is shown but not run.

```python
trend = sf.scopus_trend(q, years=range(2015, 2025))
```

## Turn it into figures

With the optional `plot` extra installed, the summaries are drawn as matplotlib figures. When the years of a trend reach the year its counts were retrieved in, [`plot_trend`][scopusflow.plots.plot_trend] adds a note below the axis saying that year was incomplete at retrieval. Scopus goes on indexing a year's publications after the year has begun. The bundled harvest records no retrieval time, so its figure carries no such note.

```python exec="1" source="material-block" html="1" session="analysing-a-literature"
sf.plot_trend(sf.year_counts(records))
show()
```

```python exec="1" source="material-block" html="1" session="analysing-a-literature"
sf.plot_top(sf.top(records, by="source"))
show()
```

## Size a niche

Without a harvest, [`scopus_intersections`][scopusflow.intersections.scopus_intersections] sizes a set of concepts and their overlap from the count endpoint, at one cheap request per row. A concept value can be a bare term, wrapped in `field` for you, or a complete field-tagged expression such as a synonym set, used exactly as given.

```python
sets = sf.scopus_intersections(
    concepts={
        "semantic priming": "semantic priming",
        "mental simulation":
            "TITLE-ABS-KEY(mental simulation) OR TITLE-ABS-KEY(embodied simulation)",
    },
    intersections=[["semantic priming", "mental simulation"]],
    field="TITLE-ABS-KEY",
)
```

The result has a fixed shape, one row per concept and per intersection, which we reproduce here with illustrative counts so the chart renders without a key. [`plot_scopus_intersections`][scopusflow.plots.plot_scopus_intersections] draws it as a lollipop chart on a log axis, with the intersection accented.

```python exec="1" source="material-block" html="1" session="analysing-a-literature"
sets = pd.DataFrame({
    "label": ["semantic priming", "mental simulation",
              "semantic priming × mental simulation"],
    "query": ["TITLE-ABS-KEY(semantic priming)",
              "TITLE-ABS-KEY(mental simulation) OR "
              "TITLE-ABS-KEY(embodied simulation)",
              "(TITLE-ABS-KEY(semantic priming)) AND "
              "(TITLE-ABS-KEY(mental simulation) OR "
              "TITLE-ABS-KEY(embodied simulation))"],
    "n": pd.array([6600, 2600, 18], dtype="Int64"),
    "type": ["concept", "concept", "intersection"],
    "size": [1, 1, 2],
    "members": ["semantic priming", "mental simulation",
                "semantic priming; mental simulation"],
})
focal = sets.loc[sets["type"] == "intersection", "label"].tolist()
sf.plot_scopus_intersections(sets, highlight=focal)
show()
```

## Read the fuller record

[`scopus_abstract`][scopusflow.abstract.scopus_abstract] retrieves the abstract and fuller metadata for a known identifier from the Abstract Retrieval API, so it needs a key.

```python
dois = sf.extract_dois(records)
abstracts = sf.scopus_abstract(dois[:10], by="doi")
abstracts[["doi", "title", "year"]]
```

The result is one row per identifier, over the stable `ABSTRACT_COLUMNS` schema. The bundled harvest carries the bibliographic fields but no abstract text or Scopus identifier, so the frame below takes its two most-cited records, puts a placeholder in the abstract column and leaves `scopus_id` missing. Every other value in those rows is taken from the records.

```python exec="1" source="material-block" session="analysing-a-literature"
most_cited = records.nlargest(2, "citations")
abstracts = pd.DataFrame({
    "scopus_id": pd.NA,
    "doi": most_cited["doi"],
    "title": most_cited["title"],
    "abstract": "(the bundled harvest carries no abstract text)",
    "publication": most_cited["publication"],
    "date": most_cited["date"],
    "year": most_cited["year"],
    "citations": most_cited["citations"],
}, columns=sf.abstract.ABSTRACT_COLUMNS)
out(abstracts[["title", "publication", "year", "citations"]])
```

A failed identifier yields a warning and an all-NA row that still records it, and the batch continues. Two failures concern the key rather than one identifier, as [Author keywords and references](keywords-and-references.md) describes. A refused entitlement (HTTP 403) raises [`ScopusFlowForbiddenError`][scopusflow.exceptions.ScopusFlowForbiddenError] and stops the batch. A spent weekly quota stops the requests, keeps the rows already retrieved and warns once with [`ScopusFlowQuotaWarning`][scopusflow.exceptions.ScopusFlowQuotaWarning].
