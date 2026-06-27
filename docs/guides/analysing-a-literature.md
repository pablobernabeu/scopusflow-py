# Analysing a literature

Once records are in hand, scopusflow turns them into the figures a bibliometric study usually needs, all from the one stable schema. The examples here run on a small synthetic record set so they work without a key. In practice `records` comes from a harvest.

```python exec="1" session="analysing-a-literature"
import html as _html
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import scopusflow as sf
from io import StringIO


def out(x):
    if isinstance(x, pd.DataFrame):
        print(x.to_html(index=False, border=0))
    elif isinstance(x, pd.Series):
        print(x.to_frame("count").to_html(border=0))
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
            "publication": sources[(year + j) % len(sources)],
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

## Read the fuller record

[`scopus_abstract`][scopusflow.abstract.scopus_abstract] pulls the abstract and fuller metadata for a known identifier, and is resilient to the odd id that fails. It calls the Abstract Retrieval API, so it needs a key.

```python
abstracts = sf.scopus_abstract(dois[:10], by="doi")
abstracts[["doi", "title", "year"]]
```
