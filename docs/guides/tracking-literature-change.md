# Tracking change over time

A literature is a moving target. Run the same search a few months apart and the result will have grown, and it may also have lost a record that was re-indexed under a different identifier. This guide shows how to compare two harvests of the same plan and see exactly which records the literature gained or lost in between. Both harvests here are cut from the corpus bundled with the package, 138 real articles on graphene supercapacitors that stand in for a Scopus retrieval, since retrieved records may not be redistributed and no key is assumed. The guide closes with the live form, where the later harvest comes from [`fetch_plan`][scopusflow.fetch.fetch_plan] instead.

## Two harvests to compare

A harvest is the normalised frame that [`fetch_plan`][scopusflow.fetch.fetch_plan] returns, with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. The baseline below is that same search as it stood at the start of 2022, which is the bundled harvest cut off after 2021.

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

records = sf.example_records()
baseline = records[records["year"] <= 2021].reset_index(drop=True)
out(baseline[["entry_number", "doi", "title", "year"]].tail(3))
```

That leaves 94 of the 138 records. Every row carries the `entry_number` it held
in the harvest, which is what makes a partial fetch resumable, and a `year`
parsed from the cover date. A live pull arrives in the same shape, because
[`fetch_plan`][scopusflow.fetch.fetch_plan] passes the pybliometrics result
through [`to_records`][scopusflow.records.to_records], which strips the `eid`
back to a bare `scopus_id` and parses the `coverDate`. That identifier column is
empty in the bundled set, these records not having come from Scopus, so the
comparison below rests on the DOI, which is what it would key on in a live
setting anyway.

Some months on the search is repeated, and by then the three later years have
been indexed. This second pull also loses one record from the earlier one, which
is what happens when a paper is re-indexed under a different identifier, so we
drop the first row to stand for it.

```python exec="1" source="material-block" session="tracking"
later = records.drop(index=records.index[0]).reset_index(drop=True)
out(later[["entry_number", "doi", "title", "year"]].tail(3))
```

## Pulling the DOIs out

The comparison runs on DOIs, so it helps to see what a harvest reduces to first. [`extract_dois`][scopusflow.diff.extract_dois] reads the `doi` column from a record frame and returns a cleaned list. It strips a resolver prefix such as `https://doi.org/` and a leading `doi:` label, and by default it de-duplicates case-insensitively, since the same DOI can arrive in different letter cases.

```python exec="1" source="material-block" session="tracking"
dois = sf.extract_dois(baseline)
out((len(dois), dois[:3]))
```

The 94 baseline records reduce to 84 DOIs, the ten records that carry none being
dropped rather than passed on as blanks.

It also accepts a plain list, which is handy when the DOIs come from somewhere other than a harvest, for instance a column you read from a file. The cleaning and de-duplication apply either way.

```python exec="1" source="material-block" session="tracking"
# 10.5555 is the reserved DOI test prefix, so none of these resolve.
out(sf.extract_dois(["https://doi.org/10.5555/AB-1", "doi: 10.5555/ab-1",
                     "10.5555/cd-2"]))
```

That list collapses to two entries because the first two are the same DOI in different cases. Pass `dedupe=False` to keep every entry as it came in, including repeats.

## What changed

[`diff_dois`][scopusflow.diff.diff_dois] compares two harvests and returns a DataFrame with a `doi` column and a `status` column, where the status is `added`, `removed` or `unchanged`. It calls [`extract_dois`][scopusflow.diff.extract_dois] on each side for you, so you can hand it the record frames directly, and the comparison is case-insensitive throughout.

```python exec="1" source="material-block" session="tracking"
changes = sf.diff_dois(old=baseline, new=later)
out(changes.head())
```

The 43 papers indexed since the baseline come back as `added`, the 83 present in
both pulls as `unchanged`, and the one that fell out of the later pull as
`removed`. The frame is sorted by status then DOI, so the categories group
together.

To act on one category, filter the frame on `status` as you would any pandas DataFrame.

```python exec="1" source="material-block" session="tracking"
out(changes[changes["status"] == "removed"])
```

A count per category gives a quick read on how much moved between the two pulls.

```python exec="1" source="material-block" session="tracking"
out(changes["status"].value_counts())
```

## Merging without duplicates

To carry a cumulative set forward across pulls, concatenate the harvests and drop the records they share, which mirrors the R twin's `scopus_combine(dedupe = TRUE)`. Records retrieved from Scopus can be keyed on `scopus_id`; these carry none, so the key here is the cleaned DOI, compared the way [`extract_dois`][scopusflow.diff.extract_dois] compares it.

```python exec="1" source="material-block" session="tracking"
combined = pd.concat([baseline, later], ignore_index=True)
key = (combined["doi"].str.lower()
       .str.replace(r"^https?://(dx\.)?doi\.org/", "", regex=True))
combined = combined[key.isna() | ~key.duplicated()].copy()
combined["entry_number"] = range(1, len(combined) + 1)
out((len(combined), len(sf.extract_dois(combined))))
```

That takes 231 concatenated rows down to 148: the 127 distinct DOIs, plus the 21
records carrying none, which cannot be matched this way and are kept rather than
quietly collapsed into one another.

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

Everything above runs offline because both harvests were cut from the bundled corpus. In practice the later harvest comes from the API, and that call needs a configured Scopus API key, which pybliometrics reads from its own configuration. The shape of the comparison does not change. You re-run the same [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], read back the harvest you saved earlier, and diff the two.

```python
import pandas as pd

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")

later = sf.fetch_plan(plan, cache_dir="graphene-harvest-2")
baseline = pd.read_parquet("baseline.parquet")
sf.diff_dois(old=baseline, new=later)
```

Run that on a schedule against a saved baseline and the `added` and `removed` rows tell you, harvest after harvest, precisely how the literature is shifting under your search.
