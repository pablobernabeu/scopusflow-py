# Tracking change over time

A literature is a moving target. Run the same search a few months apart and the result will have grown, and it may also have lost a record that was re-indexed under a different identifier. This guide shows how to compare two harvests of the same plan and see exactly which records the literature gained or lost in between. The worked examples build both harvests from small lists of records so they run without a key, then close with the live form, where the later harvest comes from [`fetch_plan`][scopusflow.fetch.fetch_plan] instead.

## Two harvests to compare

A harvest is the normalised frame that [`fetch_plan`][scopusflow.fetch.fetch_plan] returns, with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. To keep these examples offline, we build two frames of that same shape with [`to_records`][scopusflow.records.to_records], which normalises a list of record dicts the same way it normalises a real pybliometrics result. The baseline stands in for an earlier pull.

```python exec="1" session="tracking"
import html as _html
import pandas as pd
import scopusflow as sf


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

```python exec="1" source="material-block" session="tracking"
import scopusflow as sf

baseline = sf.to_records(
    [
        {"eid": "2-s2.0-85000000001", "doi": "10.1038/s41586-019-0001-1",
         "title": "Genome editing with CRISPR-Cas9", "coverDate": "2019-04-12"},
        {"eid": "2-s2.0-85000000002", "doi": "10.1038/s41586-020-0002-2",
         "title": "Deep learning for medical image analysis", "coverDate": "2020-02-20"},
        {"eid": "2-s2.0-85000000006", "doi": "10.1103/PhysRevLett.116.061102",
         "title": "Observation of gravitational waves", "coverDate": "2016-02-11"},
    ],
    query="illustrative baseline harvest",
)
out(baseline[["entry_number", "scopus_id", "doi", "title", "year"]])
```

The normalisation is visible in that table. The `eid` has been stripped back to a
bare `scopus_id`, the `coverDate` has been parsed into a `year`, and every row
carries the `entry_number` it held in the harvest, which is what makes a partial
fetch resumable.

Months on, the search is repeated. This second pull keeps most of the original records, drops the one that was re-indexed and adds two newly indexed papers.

```python exec="1" source="material-block" session="tracking"
later = sf.to_records(
    [
        {"eid": "2-s2.0-85000000001", "doi": "10.1038/s41586-019-0001-1",
         "title": "Genome editing with CRISPR-Cas9", "coverDate": "2019-04-12"},
        {"eid": "2-s2.0-85000000002", "doi": "10.1038/s41586-020-0002-2",
         "title": "Deep learning for medical image analysis", "coverDate": "2020-02-20"},
        {"eid": "2-s2.0-85000000007", "doi": "10.1126/science.abc1234",
         "title": "A room-temperature superconductor candidate", "coverDate": "2023-03-08"},
        {"eid": "2-s2.0-85000000008", "doi": "10.1038/s41586-023-0008-8",
         "title": "Large language models for scientific discovery", "coverDate": "2023-06-01"},
    ],
    query="illustrative later harvest",
)
out(later[["entry_number", "scopus_id", "doi", "title", "year"]])
```

## Pulling the DOIs out

The comparison runs on DOIs, so it helps to see what a harvest reduces to first. [`extract_dois`][scopusflow.diff.extract_dois] reads the `doi` column from a record frame and returns a cleaned list. It strips a resolver prefix such as `https://doi.org/` and a leading `doi:` label, and by default it de-duplicates case-insensitively, since the same DOI can arrive in different letter cases.

```python exec="1" source="material-block" session="tracking"
out(sf.extract_dois(baseline))
```

It also accepts a plain list, which is handy when the DOIs come from somewhere other than a harvest, for instance a column you read from a file. The cleaning and de-duplication apply either way.

```python exec="1" source="material-block" session="tracking"
out(sf.extract_dois(["https://doi.org/10.1/A", "doi: 10.1/a", "10.2/B"]))
```

That list collapses to two entries because the first two are the same DOI in different cases. Pass `dedupe=False` to keep every entry as it came in, including repeats.

## What changed

[`diff_dois`][scopusflow.diff.diff_dois] compares two harvests and returns a DataFrame with a `doi` column and a `status` column, where the status is `added`, `removed` or `unchanged`. It calls [`extract_dois`][scopusflow.diff.extract_dois] on each side for you, so you can hand it the record frames directly, and the comparison is case-insensitive throughout.

```python exec="1" source="material-block" session="tracking"
changes = sf.diff_dois(old=baseline, new=later)
out(changes)
```

The two newly indexed papers come back as `added`, the records present in both pulls as `unchanged`, and the re-indexed paper that fell out of the later pull as `removed`. The frame is sorted by status then DOI, so the categories group together.

To act on one category, filter the frame on `status` as you would any pandas DataFrame.

```python exec="1" source="material-block" session="tracking"
out(changes[changes["status"] == "added"])
```

A count per category gives a quick read on how much moved between the two pulls.

```python exec="1" source="material-block" session="tracking"
out(changes["status"].value_counts())
```

## Merging without duplicates

To carry a cumulative set forward across pulls, concatenate the harvests and drop the shared records on `scopus_id`, which mirrors the R twin's `scopus_combine(dedupe = TRUE)` and could equally key on the cleaned DOI through `sf.extract_dois`.

```python exec="1" source="material-block" session="tracking"
combined = (
    pd.concat([baseline, later], ignore_index=True)
      .drop_duplicates(subset="scopus_id", keep="first")
)
combined["entry_number"] = range(1, len(combined) + 1)
out(len(combined))
```

## Keeping a record of each pull

Comparing against a past harvest only works if you kept it, so it is worth saving each pull as you go. A record frame is an ordinary pandas DataFrame, which means the usual pandas writers and readers round-trip it. Parquet preserves the column types exactly, which matters for the nullable integer columns in the schema.

```python
import pandas as pd

baseline.to_parquet("baseline.parquet")
restored = pd.read_parquet("baseline.parquet")
sf.diff_dois(old=restored, new=later)
```

If you would rather have a plain-text artefact to commit alongside the analysis, `baseline.to_csv("baseline.csv", index=False)` works too, with `pandas.read_csv` to read it back.

## In a live setting

Everything above runs offline because both harvests were built by hand. In practice the later harvest comes from the API, and that call needs a configured Scopus API key, which pybliometrics reads from its own configuration. The shape of the comparison does not change. You re-run the same [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], read back the harvest you saved earlier, and diff the two.

```python
import pandas as pd

q = sf.scopus_query("CRISPR", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2019, 2024), partition="year")

later = sf.fetch_plan(plan, cache_dir="crispr-harvest-2")
baseline = pd.read_parquet("baseline.parquet")
sf.diff_dois(old=baseline, new=later)
```

Run that on a schedule against a saved baseline and the `added` and `removed` rows tell you, harvest after harvest, precisely how the literature is shifting under your search.
