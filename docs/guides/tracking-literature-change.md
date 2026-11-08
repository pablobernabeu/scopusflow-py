# Tracking change over time

Run the same search a few months apart and the result will have grown, and it may also have lost a record that was re-indexed. This guide shows how to compare two harvests of the same plan and see which records the literature gained or lost in between. Both harvests here are cut from the corpus bundled with the package, 138 real articles on graphene supercapacitors. They stand in for a Scopus retrieval, since retrieved records may not be redistributed and no key is assumed.

## Two harvests to compare

A harvest is the normalised frame that [`fetch_plan`][scopusflow.fetch.fetch_plan] returns, with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. The baseline below is that same search as it stood at the start of 2022, which is the bundled harvest cut off after 2021.

```python exec="1" session="tracking"
import html as _html
import pandas as pd
import scopusflow as sf


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

```python exec="1" source="material-block" session="tracking"
import scopusflow as sf

records = sf.example_records()
baseline = records[records["year"] <= 2021].reset_index(drop=True)
out(baseline[["entry_number", "doi", "title", "year"]].tail(3))
```

That leaves 94 of the 138 records. Every row keeps the `entry_number` it held
in the full harvest, and a `year` parsed from the cover date. A live pull
arrives in the same shape, because
[`fetch_plan`][scopusflow.fetch.fetch_plan] passes the pybliometrics result
through [`to_records`][scopusflow.records.to_records], which strips the `eid`
back to a bare `scopus_id` and parses the `coverDate`. That identifier column is
empty in the bundled set, since these records did not come from Scopus. The
record comparison and the merge below therefore rest on the DOI, where the
records of a live harvest are matched on their `scopus_id`.

Some months on, the search is repeated, and by then the three later years have
been indexed. This second pull also loses one record from the earlier one, which
is what happens when a paper is re-indexed and no longer matches the search.
Dropping the first row stands for that loss.

```python exec="1" source="material-block" session="tracking"
later = records.drop(index=records.index[0]).reset_index(drop=True)
out(later[["entry_number", "doi", "title", "year"]].tail(3))
```

## Pulling the DOIs out

The comparison runs on the DOIs a harvest reduces to. [`extract_dois`][scopusflow.diff.extract_dois] reads the `doi` column from a record frame and returns a cleaned list. It strips a resolver prefix such as `https://doi.org/` and a leading `doi:` label, and by default it de-duplicates case-insensitively, since the same DOI can arrive in different letter cases.

```python exec="1" source="material-block" session="tracking"
dois = sf.extract_dois(baseline)
out((len(dois), dois[:3]))
```

The 94 baseline records reduce to 84 DOIs, because the ten records that carry
none are dropped.

`extract_dois` also accepts a plain list, for DOIs that come from somewhere other than a harvest, such as a column you read from a file. The cleaning and de-duplication apply either way.

```python exec="1" source="material-block" session="tracking"
# 10.5555 is the reserved DOI test prefix, so none of these resolve.
out(sf.extract_dois(["https://doi.org/10.5555/AB-1", "doi: 10.5555/ab-1",
                     "10.5555/cd-2"]))
```

That list collapses to two entries because the first two are the same DOI in different cases. Pass `dedupe=False` to keep every entry as it came in, including repeats.

## What changed

[`diff_dois`][scopusflow.diff.diff_dois] compares two harvests and returns a DataFrame with a `doi` column and a `status` column, where the status is `added`, `removed` or `unchanged`. It calls [`extract_dois`][scopusflow.diff.extract_dois] on each side, so you can pass it the record frames directly. The comparison is case-insensitive throughout.

```python exec="1" source="material-block" session="tracking"
changes = sf.diff_dois(old=baseline, new=later)
out(changes.head())
```

The papers indexed since the baseline come back as `added`, those present in
both pulls as `unchanged` and the one that fell out of the later pull as
`removed`. The later pull holds 44 papers from 2022 on, 43 of them with a DOI,
so 43 are added. The two pulls share 93 records, 83 of them with a DOI, so 83
are unchanged. The records without a DOI, ten in the baseline and eleven in the
later pull, are not compared. The frame counts them in
`attrs["n_old_without_doi"]` and `attrs["n_new_without_doi"]`. Its rows are
sorted by status, then by DOI.

```python exec="1" source="material-block" session="tracking"
out((changes.attrs["n_old_without_doi"], changes.attrs["n_new_without_doi"]))
```

To act on one category, filter the frame on `status` as you would any pandas DataFrame.

```python exec="1" source="material-block" session="tracking"
out(changes[changes["status"] == "removed"])
```

A count per category shows how much changed between the two pulls.

```python exec="1" source="material-block" session="tracking"
out(changes["status"].value_counts())
```

## Comparing records

[`diff_records`][scopusflow.diff.diff_records] compares the records themselves, matching them as [`scopus_combine`][scopusflow.combine.scopus_combine] de-duplicates them with `dedupe=True`: on a shared `scopus_id`, or on a shared DOI where one of the two records lacks an identifier. A record without a DOI is then tracked by its identifier. Where a record is found in one pull only and the other pull gives its DOI to a different record, it is marked `conflict`. It may have been re-indexed under a new identifier or may be a distinct paper sharing the DOI, and which it is can be decided only by inspecting the records.

The bundled records carry no identifier, so here they are matched on their DOIs, and the records without one cannot be compared. Each row carries the record's title and year and its citation counts in both pulls. The table below leaves out the `scopus_id` and `title` columns to fit the page.

```python exec="1" source="material-block" session="tracking"
records_changed = sf.diff_records(baseline, later)
out(records_changed[["status", "doi", "year", "citations_old", "citations_new"]].head())
```

The citation columns show how much each record's count changed between the two pulls. They are equal here, because both pulls were cut from one snapshot.

The counts agree with the DOI comparison above, and the records that cannot be compared are counted in `attrs["n_old_without_id_or_doi"]` and `attrs["n_new_without_id_or_doi"]`.

```python exec="1" source="material-block" session="tracking"
out(records_changed["status"].value_counts())
```

## Merging without duplicates

To keep a cumulative set across pulls, [`scopus_combine`][scopusflow.combine.scopus_combine] binds the harvests, renumbers `entry_number` across the result and, with `dedupe=True`, keeps one copy of each record. Records with the same `scopus_id` are one record, and a record without one joins the identified record that carries its DOI. DOIs are compared ignoring case and any resolver prefix. These records carry no identifier, so they are matched on the DOI alone.

```python exec="1" source="material-block" session="tracking"
combined = sf.scopus_combine(baseline, later, dedupe=True)
out((len(combined), len(sf.extract_dois(combined))))
```

That takes 231 concatenated rows down to 148. The records that carry no DOI
cannot be matched this way and are kept, so the 148 rows are one record for
each of the 127 distinct DOIs plus the 21 records without one.

`scopus_combine` stores a record of the merge, because afterwards the rows
themselves do not show how many went in. PRISMA-S asks for that figure, and
[`scopus_search_report`][scopusflow.report.scopus_search_report] reads it back
from this merge record to answer the item. The merge record also names the
rule the records were matched by.

Records with different identifiers that share a DOI are both kept, since Scopus
gives one DOI to distinct papers as well as holding duplicate records of one
paper. The merge counts the DOIs that such records share, and the search record
gives this count so that the records can be checked by hand. Once they have
been checked, `dedupe="id_or_doi"` merges them.

```python exec="1" source="material-block" session="tracking"
out(combined.attrs["combined"])
```

## Keeping a record of each pull

Saving each harvest lets you compare against it next time. [`write_records`][scopusflow.io.write_records] saves a record set and [`read_records`][scopusflow.io.read_records] reads it back, choosing the format from the file extension. A `.parquet` file keeps the provenance a harvest carries in its `attrs`: the plan, the time it was retrieved, the per-cell totals and the software version. [`scopus_search_report`][scopusflow.report.scopus_search_report] therefore still writes the search record of a baseline read back from parquet. Parquet needs pyarrow, which `pip install "scopusflow[parquet]"` installs.

```python
sf.write_records(baseline, "baseline.parquet")
restored = sf.read_records("baseline.parquet")
sf.diff_dois(old=restored, new=later)
```

A `.csv` path gives a plain-text artefact to commit alongside the analysis. It keeps the columns and loses the provenance. `read_records` reads it back with the record schema imposed, so `scopus_id` stays text and `year` and `citations` stay whole numbers. When the file is read with `pandas.read_csv` alone, an all-digit identifier becomes a number, or a float once one identifier is missing. A de-duplicating merge with a fresh harvest then matches none of its records.

## In a live setting

Everything above runs offline because both harvests were cut from the bundled corpus. In a live setting, the later harvest comes from the API. That call needs a configured Scopus API key, which pybliometrics reads from its own configuration once `pybliometrics.init()` has been called in the session. The shape of the comparison does not change. You re-run the same [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], read back the harvest you saved earlier and diff the two. The earlier harvest is one of your own, since the bundled corpus came from OpenAlex and would differ from any Scopus harvest for that reason alone. Both harvests carry a Scopus identifier on every record, so [`diff_records`][scopusflow.diff.diff_records] can compare them all.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

q = sf.scopus_query('"graphene supercapacitor"', field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")

later = sf.fetch_plan(plan, cache_dir="graphene-harvest-2")
sf.write_records(later, "later.parquet")
baseline = sf.read_records("baseline.parquet")
sf.diff_dois(old=baseline, new=later)
sf.diff_records(baseline, later)
```

That second pull asks the API afresh and spends quota, since scopusflow sends `refresh=True` to pybliometrics unless you pass `refresh` yourself. Without it, pybliometrics' own response cache, which is keyed on the query string and view alone, would return the earlier pull, dated as if it had just been retrieved. The diff would then compare a harvest with itself. [Search plans and quota-aware retrieval](plans-and-quota.md#re-running-and-tracking-change) explains the two caches.
