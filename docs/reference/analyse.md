# Analyse & plot

Summarise a literature over time, compare topics within it, and turn the
summaries into figures.

The plotting functions below are pure over the frame they are given, so the
examples on this page build a small synthetic frame of the documented shape and
render the real figure from it at build time. Nothing here contacts the Scopus
API or needs a key. The functions that do retrieve counts are marked as such and
are shown rather than run; the guides linked from each one demonstrate them
against a live key.

--8<-- "_snippets/plot-setup.md"

::: scopusflow.trend.scopus_trend

This asks the API for a count per year, so it cannot run at build time. See
[Analysing a literature](../guides/analysing-a-literature.md) for the worked
example, and `year_counts` below for the offline equivalent over records you
already hold.

::: scopusflow.trend.year_counts

```python exec="1" source="material-block" session="reference-analyse"
out(sf.year_counts(records))
```

::: scopusflow.compare.compare_topics

This makes one count request per term per year, so it cannot run at build time.
See [Comparing topics](../guides/comparing-topics.md) for the worked example.

::: scopusflow.compare.COMPARISON_COLUMNS

::: scopusflow.intersections.scopus_intersections

This makes one count request per concept and per intersection, so it cannot run
at build time. See [Analysing a literature](../guides/analysing-a-literature.md)
for the worked example.

::: scopusflow.plots.plot_trend

```python exec="1" source="material-block" html="1" session="reference-analyse"
sf.plot_trend(sf.year_counts(records))
show()
```

::: scopusflow.plots.plot_top

```python exec="1" source="material-block" html="1" session="reference-analyse"
sf.plot_top(sf.top(records, by="source"))
show()
```

::: scopusflow.plots.plot_comparison

```python exec="1" source="material-block" html="1" session="reference-analyse"
years = list(range(2013, 2022))
ref_n = [400, 550, 700, 850, 1000, 1150, 1300, 1450, 1600]
shares = {"computer vision": 34.0, "natural language processing": 24.0,
          "medical imaging": 11.0, "drug discovery": 6.0}

rows = [{"query": "deep learning", "query_type": "reference",
         "abridged_query": "deep learning", "year": year, "n": n,
         "reference_n": n, "comparison_percentage": 100.0,
         "average_comparison_percentage": 100.0}
        for year, n in zip(years, ref_n)]
for topic, end in shares.items():
    for i, (year, n) in enumerate(zip(years, ref_n)):
        pct = end * (0.45 + 0.55 * i / (len(years) - 1))
        rows.append({"query": topic, "query_type": "comparison",
                     "abridged_query": topic, "year": year,
                     "n": int(pct * n / 100), "reference_n": n,
                     "comparison_percentage": pct,
                     "average_comparison_percentage": end})

comparison = pd.DataFrame(rows, columns=sf.compare.COMPARISON_COLUMNS)
sf.plot_comparison(comparison)
show()
```

::: scopusflow.plots.plot_scopus_intersections

```python exec="1" source="material-block" html="1" session="reference-analyse"
sets = pd.DataFrame({
    "label": ["semantic priming", "mental simulation",
              "semantic priming × mental simulation"],
    "query": ["TITLE-ABS-KEY(semantic priming)",
              "TITLE-ABS-KEY(mental simulation)",
              "(TITLE-ABS-KEY(semantic priming)) AND "
              "(TITLE-ABS-KEY(mental simulation))"],
    "n": pd.array([6600, 2600, 18], dtype="Int64"),
    "type": ["concept", "concept", "intersection"],
    "size": [1, 1, 2],
    "members": ["semantic priming", "mental simulation",
                "semantic priming; mental simulation"],
})
sf.plot_scopus_intersections(sets, highlight=["semantic priming × mental simulation"])
show()
```
