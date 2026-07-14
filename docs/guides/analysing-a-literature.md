# Analysing a literature

Once records are in hand, scopusflow turns them into the figures a bibliometric study usually needs, all from the one stable schema. The examples here run on a small synthetic record set so they work without a key. In practice `records` comes from a harvest.

```python exec="1" session="analysing-a-literature"
import html as _html
import random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import scopusflow as sf
from io import StringIO


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
        print("<pre>" + _html.escape(str(x)) + "</pre>")


def show():
    plt.tight_layout()
    plt.gcf().canvas.draw()  # let the label de-collision settle before saving
    buffer = StringIO()
    plt.savefig(buffer, format="svg")
    plt.close()
    print(buffer.getvalue())


sources = ["Nature", "Science", "Carbon", "Nano Letters", "Advanced Materials"]
authors = ["Lee J.", "Park S.", "Kim H.", "Garcia M.", "Zhang F.", "Abbott B."]
# Draw sources with unequal weights, as in a real literature, so the tally
# and its plot show a clear ordering rather than a near-uniform split.
picker = random.Random(8)
rows = []
for yi, year in enumerate(range(2016, 2023)):
    for j in range(4 + yi * 2):
        rows.append({
            "entry_number": len(rows) + 1,
            "scopus_id": f"{year}{j:03d}",
            "doi": f"10.1000/demo.{year}.{j:03d}",
            "title": f"Record {j + 1} from {year}",
            "authors": authors[j % len(authors)] + ";" + authors[(j + 1) % len(authors)],
            "year": year, "date": f"{year}-01-01",
            "publication": picker.choices(sources, weights=(9, 7, 5, 3, 2))[0],
            "citations": (j * 7 + year) % 120,
            "query": "graphene supercapacitor",
        })
records = pd.DataFrame(rows, columns=sf.RECORD_COLUMNS)
```

## What is in a record set

[`top`][scopusflow.records.top] tallies the most frequent sources or authors. Author strings that hold several names are split, so each contributor is counted once per record.

```python exec="1" source="material-block" session="analysing-a-literature"
out(sf.top(records, by="source"))
out(sf.top(records, by="author", n=6))
```

## How a literature grows

[`year_counts`][scopusflow.trend.year_counts] is the offline tally of records per year from a set you already hold.

```python exec="1" source="material-block" session="analysing-a-literature"
trend = sf.year_counts(records)
out(trend)
```

[`scopus_trend`][scopusflow.trend.scopus_trend] instead asks the API for the count in each year without downloading the records, which is far cheaper when all you want is the shape of the growth. It needs a key, so it is shown rather than run.

```python
trend = sf.scopus_trend(q, years=range(2010, 2023))
```

## Turn it into figures

With the optional `plot` extra installed, the summaries become matplotlib figures.

```python exec="1" source="material-block" html="1" session="analysing-a-literature"
sf.plot_trend(sf.year_counts(records))
show()
```

```python exec="1" source="material-block" html="1" session="analysing-a-literature"
sf.plot_top(sf.top(records, by="source"))
show()
```

## Size a niche

Where the figures above summarise records already in hand, [`scopus_intersections`][scopusflow.intersections.scopus_intersections] sizes a set of concepts and their overlap straight from the count endpoint, one cheap request per row, so a whole landscape costs no harvest. A concept value can be a bare term, wrapped in `field` for you, or a complete field-tagged expression such as a synonym set, used as given.

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

The result has a fixed shape, one row per concept and per intersection, which we reproduce here so the chart renders without a key. [`plot_scopus_intersections`][scopusflow.plots.plot_scopus_intersections] draws it as a lollipop chart on a log axis, with the intersection accented.

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

[`scopus_abstract`][scopusflow.abstract.scopus_abstract] pulls the abstract and fuller metadata for a known identifier, and is resilient to the odd id that fails. It calls the Abstract Retrieval API, so it needs a key.

```python
abstracts = sf.scopus_abstract(dois[:10], by="doi")
abstracts[["doi", "title", "year"]]
```

The result is one row per identifier, over the stable `ABSTRACT_COLUMNS` schema. To show its shape without a key, here is a stand-in with the same columns.

```python exec="1" source="material-block" session="analysing-a-literature"
abstracts = pd.DataFrame([
    {"scopus_id": "85012345678", "doi": "10.1038/s41586-018-0001-x",
     "title": "Graphene supercapacitors for fast energy storage",
     "abstract": "We report a graphene-based supercapacitor with a high power "
                 "density and long cycle life, characterised across a range of "
                 "scan rates.",
     "publication": "Nature", "date": "2018-05-03", "year": 2018,
     "citations": 214},
    {"scopus_id": "85023456789", "doi": "10.1126/science.abc1234",
     "title": "Porous carbon electrodes at scale",
     "abstract": "A scalable route to porous carbon electrodes is described, with "
                 "capacitance retention benchmarked against commercial baselines.",
     "publication": "Science", "date": "2020-11-20", "year": 2020,
     "citations": 88},
], columns=sf.abstract.ABSTRACT_COLUMNS)
out(abstracts[["title", "publication", "year", "citations"]])
out(abstracts.loc[0, "abstract"][:40] + "...")
```

A failed identifier does not stop the batch, but yields an all-NA row that still records the id, together with a warning.
