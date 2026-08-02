# API reference

Every public name in `scopusflow` is documented here, grouped along the path a
search takes: describe it, size it, run it as a resumable harvest, normalise
what comes back, see what a later retrieval changed, and summarise and plot the
result. The groups are the ones the
[R package's reference index](https://pablobernabeu.github.io/scopusflow/reference/)
uses, and they come in the same order, so a function documented in both
languages is filed under the same heading on either site.

Two of the group names differ from the R ones because the membership differs.
The R group 'Plan and size' also holds the counting function, which is
documented under Retrieve here alongside the other calls that spend quota, so
the first group is called 'Plan and query' instead. Records is wider than its R
namesake, because it absorbs the R groups 'Export and I/O' and 'Data'. The
BibTeX and RIS writers and the bundled example harvest all work on the record
table, and neither would fill a section of its own. The two remaining R groups
have no counterpart below. 'App' documents a function that launches the
interface, where the Python app is started from the command line and covered by
[The code-free app](guides/the-app.md), and 'Keys' documents a key check that
scopusflow does not need in Python, since pybliometrics holds the key
configuration.

Every name listed under a group heading is importable straight from
`scopusflow`, conventionally as `sf`. The guides linked from the
[home page](index.md) work the same functions through end-to-end examples.

## Plan and query

Describe a search before running it, and build field-tagged Boolean queries.

::: scopusflow.query.scopus_query

::: scopusflow.query.wrap_field

::: scopusflow.query.FIELD_TAGS

::: scopusflow.plan.SearchPlan

::: scopusflow.plan.PlanCell

## Retrieve

Size a search cheaply first, then execute a plan as a resumable, checkpointed
harvest, and pull fuller records.

::: scopusflow.count.scopus_count

::: scopusflow.fetch.fetch_plan

::: scopusflow.abstract.scopus_abstract

::: scopusflow.corpus.corpus

::: scopusflow.exceptions.ScopusFlowForbiddenError

## Records

Normalise results into one stable schema, tally the most frequent values, and
export to reference-manager formats.

--8<-- "_snippets/plot-setup.md"

::: scopusflow.records.to_records

::: scopusflow.records.top

The tally below runs at build time over the bundled example harvest, so it needs
no key.

```python exec="1" source="material-block" session="reference-analyse"
records = sf.example_records()
out(sf.top(records, by="source", n=5))
```

::: scopusflow.records.RECORD_COLUMNS

::: scopusflow.data.example_records

::: scopusflow.export.to_bibtex

::: scopusflow.export.to_ris

## DOIs and change tracking

Extract clean DOIs and compare two retrievals to see exactly what changed.

::: scopusflow.diff.extract_dois

::: scopusflow.diff.diff_dois

## Analyse and visualise

Summarise a literature over time, compare topics within it, and turn the
summaries into figures.

The plotting functions below are pure over the frame they are given, so the
record examples in this section run at build time over the bundled example
harvest, and the topic comparison over a frame of the documented shape. Nothing
here contacts the Scopus API or needs a key. The functions that do retrieve
counts are marked as such and are shown rather than run. The guides linked from
each one demonstrate them against a live key.

::: scopusflow.trend.scopus_trend

This asks the API for a count per year, so it cannot run at build time. See
[Analysing a literature](guides/analysing-a-literature.md) for the worked
example, and `year_counts` below for the offline equivalent over records you
already hold.

::: scopusflow.trend.year_counts

```python exec="1" source="material-block" session="reference-analyse"
out(sf.year_counts(records))
```

::: scopusflow.compare.compare_topics

This makes one count request per term per year, so it cannot run at build time.
See [Comparing topics](guides/comparing-topics.md) for the worked example.

::: scopusflow.compare.COMPARISON_COLUMNS

::: scopusflow.intersections.scopus_intersections

This makes one count request per concept and per intersection, so it cannot run
at build time. See [Analysing a literature](guides/analysing-a-literature.md)
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
sf.plot_scopus_intersections(
    sets, highlight=["semantic priming × mental simulation"]
)
show()
```
