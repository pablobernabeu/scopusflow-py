# Comparing topics

A bibliometric study often asks not how large a literature is but how its internal emphasis shifts over time. Within deep-learning research, is the share of work that also concerns medical imaging growing faster than the share about computer vision? [`compare_topics`][scopusflow.compare.compare_topics] answers that question by counting, and [`plot_comparison`][scopusflow.plots.plot_comparison] shows the answer. The comparison contacts the Scopus API, so it is shown here but reconstructed offline for the plotting, using a frame of the same shape so the rest of the guide runs without a key.

```python exec="1" session="comparing-topics"
import html as _html
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
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
    plt.gcf().set_size_inches(8, 4.2)
    plt.tight_layout()
    plt.gcf().canvas.draw()  # let the label de-collision settle before saving
    buffer = StringIO()
    plt.savefig(buffer, format="svg")
    plt.close()
    print(buffer.getvalue())
```

## What the comparison measures

For each year and each comparison term, the function counts the records matching the reference topic combined with that term, then expresses that count as a percentage of the records matching the reference alone. A value of 30% for computer vision in 2020 means that 30% of the deep-learning records that year also mention computer vision. The reference is the denominator, so it sits at 100% by construction and is not drawn.

Running [`compare_topics`][scopusflow.compare.compare_topics] makes one count request per term per year, plus one per year for the reference topic, so it needs a configured Scopus key (through pybliometrics) and counts against your quota. Keep the term and year counts modest.

```python
import scopusflow as sf

cmp = sf.compare_topics(
    reference_query="deep learning",
    comparison_terms=[
        "computer vision",
        "natural language processing",
        "medical imaging",
        "drug discovery",
    ],
    years=range(2013, 2022),
    field="TITLE-ABS-KEY",
)
```

The `field` argument wraps every term in the same field tag, the way [`scopus_query`][scopusflow.query.scopus_query] does, so each side of the AND searches the title, abstract and keywords.

## The shape of the result

The result is a tidy pandas frame with one row per topic and year, carrying the stable [`COMPARISON_COLUMNS`][scopusflow.compare.COMPARISON_COLUMNS] schema. We build one here with the same columns so the rest of the guide runs offline. The reference set grows across the period, which the uncertainty band will later reflect.

```python exec="1" source="material-block" session="comparing-topics"
import numpy as np
import pandas as pd
import scopusflow as sf

years = list(range(2013, 2022))
ref_n = np.linspace(400, 1600, len(years)).round().astype(int)
counts = {
    "computer vision": np.linspace(140, 720, len(years)).round().astype(int),
    "natural language processing": np.linspace(90, 540, len(years)).round().astype(int),
    "medical imaging": np.linspace(15, 260, len(years)).round().astype(int),
    "drug discovery": np.linspace(8, 170, len(years)).round().astype(int),
}

rows = []
for year, n in zip(years, ref_n):
    rows.append({
        "query": "deep learning", "query_type": "reference",
        "abridged_query": "deep learning", "year": year, "n": int(n),
        "reference_n": int(n), "comparison_percentage": 100.0,
        "average_comparison_percentage": 100.0,
    })
for topic, series in counts.items():
    avg = 100.0 * series.sum() / ref_n.sum()
    for year, n, ref in zip(years, series, ref_n):
        rows.append({
            "query": topic, "query_type": "comparison",
            "abridged_query": topic, "year": year, "n": int(n),
            "reference_n": int(ref),
            "comparison_percentage": 100.0 * n / ref,
            "average_comparison_percentage": avg,
        })

cmp = pd.DataFrame(rows, columns=sf.compare.COMPARISON_COLUMNS)
out(cmp.head())
```

The `comparison_percentage` column is the per-year share, and `average_comparison_percentage` is the same ratio computed over the whole period, which is what orders the topics in the plot. A year in which the reference has no records has no defined share, so [`compare_topics`][scopusflow.compare.compare_topics] records it as a missing value rather than a misleading zero.

## A first plot

With the optional `plot` extra installed, [`plot_comparison`][scopusflow.plots.plot_comparison] draws each comparison topic as a line and returns the matplotlib `Axes` for any further adjustment.

```python exec="1" source="material-block" html="1" session="comparing-topics"
ax = sf.plot_comparison(cmp)
show()
```

The chart uses a colour-blind-safe palette and, because there are only a few topics, labels the lines directly so the reader need not match colours to a legend. Each label carries the topic's total record count. The shaded band around each line is a Wilson stability range, wide in the early years when the reference set is small and the share would move easily, and narrower as the literature grows. Because Scopus returns exact counts rather than a sample, the band is illustrative rather than a confidence interval, a point the caption on the figure makes plain.

## When lines converge at the right end

Direct labels are legible only if they do not overlap, and topics sometimes end the period at nearly the same share. [`plot_comparison`][scopusflow.plots.plot_comparison] spreads converging labels apart automatically, at the point the figure is actually drawn, so they stay readable at any figure size rather than stacking into an unreadable pile. Here six sub-areas of materials-science research all end 2013–2021 within three points of one another.

```python exec="1" source="material-block" html="1" session="comparing-topics"
years = list(range(2013, 2022))
ends = {"graphene": 18, "perovskites": 18.6, "MXenes": 19.2, "COFs": 19.8, "MOFs": 20.4, "aerogels": 21}
ref_n = np.linspace(500, 2000, len(years)).round().astype(int)

rows = []
for year, n in zip(years, ref_n):
    rows.append({
        "query": "q", "query_type": "reference",
        "abridged_query": "energy materials", "year": year, "n": int(n),
        "reference_n": int(n), "comparison_percentage": 100.0,
        "average_comparison_percentage": 100.0,
    })
for topic, end in ends.items():
    for i, (year, n) in enumerate(zip(years, ref_n)):
        pct = end * (0.5 + 0.5 * i / (len(years) - 1))
        rows.append({
            "query": topic, "query_type": "comparison",
            "abridged_query": topic, "year": year, "n": int(pct * n / 100),
            "reference_n": int(n), "comparison_percentage": pct,
            "average_comparison_percentage": end,
        })

cmp_converging = pd.DataFrame(rows, columns=sf.compare.COMPARISON_COLUMNS)
ax = sf.plot_comparison(cmp_converging)
show()
```

Without this, six labels ending within three points of each other would print on top of one another. Here every one is still readable, and the colour match and shared top-to-bottom order keep each label tied to its line.

## Drawing the eye to one topic

When one topic is the focus of a figure, `highlight` draws it in an accent colour and greys the rest, which keeps the context visible without letting it compete. The named topic must be one of the comparison topics in the frame.

```python exec="1" source="material-block" html="1" session="comparing-topics"
ax = sf.plot_comparison(cmp, highlight="medical imaging")
show()
```

Only the highlighted topic keeps its band, so the eye settles on the one line that matters while the others recede.

## Adjusting the labels and the band

The count suffix on each label can be turned off with `counts_in_legend`, and the band can be removed with `interval`, when a cleaner look is wanted.

```python exec="1" source="material-block" html="1" session="comparing-topics"
ax = sf.plot_comparison(cmp, counts_in_legend=False, interval=False)
show()
```

The return value is an ordinary matplotlib `Axes`, so a different style, a saved file or any further tweak is one method call away, for instance `ax.figure.savefig("topics.png", dpi=200)`.

## Placing the legend

When there are only a few topics the lines are labelled directly, so no legend is needed. Beyond a handful the labels would collide, so [`plot_comparison`][scopusflow.plots.plot_comparison] falls back to a legend instead. By default matplotlib chooses where the legend sits, but `legend_inside=True` places it inside the axes in whichever corner has the most free space (here the top-left, which these rising lines leave empty), which saves the width an outside legend would otherwise take. The argument matches the R package's `legend_inside` and leaves the default placement untouched.

```python exec="1" source="material-block" html="1" session="comparing-topics"
many = list("ABCDEFGHIJ")
ref_n = np.linspace(500, 2000, len(years)).round().astype(int)

rows = []
for year, n in zip(years, ref_n):
    rows.append({
        "query": "q", "query_type": "reference",
        "abridged_query": "energy materials", "year": year, "n": int(n),
        "reference_n": int(n), "comparison_percentage": 100.0,
        "average_comparison_percentage": 100.0,
    })
for i, topic in enumerate(many):
    end = 6 + i
    for j, (year, n) in enumerate(zip(years, ref_n)):
        pct = end * (0.5 + 0.5 * j / (len(years) - 1))
        rows.append({
            "query": topic, "query_type": "comparison",
            "abridged_query": f"topic {topic}", "year": year,
            "n": int(pct * n / 100), "reference_n": int(n),
            "comparison_percentage": pct, "average_comparison_percentage": end,
        })

cmp_many = pd.DataFrame(rows, columns=sf.compare.COMPARISON_COLUMNS)
ax = sf.plot_comparison(cmp_many, legend_inside=True)
show()
```

## Reading the result as a table

Sometimes the numbers matter more than the picture. Because the output is a pandas frame, the usual tools apply. Here are the comparison topics ranked by their average share.

```python exec="1" source="material-block" session="comparing-topics"
comp = cmp[cmp["query_type"] == "comparison"]
ranked = (comp[["abridged_query", "average_comparison_percentage"]]
          .drop_duplicates()
          .sort_values("average_comparison_percentage", ascending=False))
out(ranked)
```
