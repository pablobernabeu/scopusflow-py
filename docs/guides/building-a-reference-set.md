# Building a reference set

This guide covers the export end of the workflow, which turns a retrieval into a reading list in a reference manager or into input for a writing project. A set of records from the API becomes a clean DOI list and then an export in the two interchange formats that reference managers read. The worked output runs on the harvest bundled with the package, 138 real articles on graphene supercapacitors, since records retrieved from Scopus may not be redistributed and no key is assumed here. The live call that would replace it is shown first.

```python exec="1" session="building-a-reference-set"
import scopusflow as sf
import pandas as pd
import html as _html


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

## Fetch the record set

Everything here starts from a frame of records. You build one by running a [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], which calls pybliometrics one cell at a time and returns a single frame with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. This step contacts the Scopus API, so it needs a working API key configured for pybliometrics. Run it once and keep the frame for the rest of the guide.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

q = sf.scopus_query('"graphene supercapacitor"', field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")

records = sf.fetch_plan(plan, cache_dir="graphene-harvest")
records.shape
```

[`example_records`][scopusflow.data.example_records] returns the bundled stand-in, and the output below runs on it. Its records came from OpenAlex's exact-phrase search for the same phrase in titles and abstracts, limited to journal articles, so the harvest above would return a different set. [Get started](getting-started.md#the-bundled-harvest) says more about where they come from.

A frame of records is an ordinary pandas DataFrame, so it works in any analysis you already have. Its columns are the same for every query, so the DOI and export helpers that follow can rely on them.

```python exec="1" source="material-block" session="building-a-reference-set"
records = sf.example_records()
out(records[["title", "year", "doi"]].head())
```

## Document types, errata and retractions

A harvest can keep more than the record columns. With `fields="extended"`, [`fetch_plan`][scopusflow.fetch.fetch_plan] also keeps the document type, source type, volume, issue, pages, ISSN, PubMed identifier and open-access status the Search API sends with every record, the columns [`EXTENDED_COLUMNS`][scopusflow.records.EXTENDED_COLUMNS] names. Under the `COMPLETE` view, it keeps the abstract too. These fields are part of the responses the harvest already receives, so they cost no extra quota. The bundled harvest came from OpenAlex and carries none of them, so this step is shown but not run.

```python
records = sf.fetch_plan(plan, fields="extended")
records["doc_type"].value_counts()
articles = records[records["doc_type"].isin(["ar", "re"])]
```

`doc_type` holds the code Scopus gives a record's document type, such as `ar` for an article, `re` a review or `cp` a conference paper, and `doc_type_description` holds its name. Scopus labels an erratum `er` and a retracted item `tb`, and its errata cover retraction notices as well as corrections. Such labels do not screen a set for retractions, since Scopus does not label every retracted item ([Ortega & Delgado-Quirós, 2024](https://doi.org/10.1007/s11192-024-05034-y)). A review should still check its included records against the [Retraction Watch database](https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/).

Errata can also be left out of the search itself. [`scopus_query`][scopusflow.query.scopus_query] brackets the rest of the query before it adds `AND NOT DOCTYPE(er)`, so the exclusion applies to the whole of it under either operator order the [guide to designing queries](designing-queries.md) describes.

```python exec="1" source="material-block" session="building-a-reference-set"
out(sf.scopus_query(
    sf.scopus_query("graphene", "graphite", op="OR", field="TITLE-ABS-KEY"),
    "DOCTYPE(er)", op="AND NOT",
))
```

## A clean, deduplicated DOI list

Reference managers such as Zotero import most reliably from DOIs. [`extract_dois`][scopusflow.diff.extract_dois] pulls them from the `doi` column, strips any resolver prefix or `doi:` label and removes duplicates compared case-insensitively. The same article then imports once even when its DOI was stored with a `https://doi.org/` prefix or in a different case.

```python exec="1" source="material-block" session="building-a-reference-set"
dois = sf.extract_dois(records)
out(dois[:5])
```

The function works offline because it only reads the frame you already hold. It returns a plain Python list and writes no file. The list runs to 127 entries against 138 records, because the eleven records that carry no DOI are dropped.

De-duplication matters once two retrievals are put together. Concatenating a retrieval of 2015 to 2020 with a later one of 2019 onwards repeats every record in the two overlapping years, and a reference manager given the raw column would import each of those twice. To show what the cleaning has to handle, the second copy of one DOI is rewritten here into the resolver form an aggregator often returns.

```python exec="1" source="material-block" session="building-a-reference-set"
import pandas as pd

combined = pd.concat(
    [records[records["year"] <= 2020], records[records["year"] >= 2019]],
    ignore_index=True,
)
repeat = combined.index[
    combined.duplicated("entry_number") & combined["doi"].notna()
][0]
combined.loc[repeat, "doi"] = "https://doi.org/" + combined.loc[
    repeat, "doi"
].upper()

all_dois = sf.extract_dois(combined, dedupe=False)
out((len(combined), len(all_dois), len(sf.extract_dois(combined))))
```

The 170 concatenated records yield 155 raw DOIs, the difference being the records with none, and 127 once duplicates are removed. The rewritten entry collapses into its plain copy, since the comparison ignores the resolver prefix and the letter case. Subtracting one count from the other shows how much two retrievals overlap. Pass `dedupe=False` when you want the repeats kept, for instance to count how often a DOI recurs across cells.

Writing the list to a file takes one line of standard-library code.

```python
from pathlib import Path

Path("reference-set.txt").write_text("\n".join(dois), encoding="utf-8")
```

## Render to BibTeX and RIS

A DOI list is enough for an import-by-identifier, but a record carries more than its DOI. [`to_bibtex`][scopusflow.export.to_bibtex] and [`to_ris`][scopusflow.export.to_ris] render the set in the two formats that reference managers read, for use in Zotero, EndNote, Mendeley or a LaTeX bibliography. Each record becomes one entry. Both functions are pure and offline, and return a string without writing a file. The output below shows the first three records, of which the second is one of the eleven with no DOI and has no `DO` line.

```python exec="1" source="material-block" session="building-a-reference-set"
out(sf.to_ris(records.head(3)))
```

An author string holding several names is split into one `AU` line each. That is not visible above, because the bundled records name only the first author of each paper. A harvest run with `view="COMPLETE"` carries the author list, up to 100 names per record joined by `"; "`, and every name in it gets its own line. Under `STANDARD`, the default, the API sends the first author alone, so each entry has one `AU` line. That name comes as `Zhang F.`, with no comma, and both exporters write it as `Zhang, F.`, so that a reference manager or BibTeX reads Zhang as the family name.

The source title goes under `T2`, the tag Scopus's own RIS export uses. Every entry names the database (`DB  - Scopus`), and an entry whose record has a Scopus identifier gives its EID as the accession number (`AN`).

Every bundled record is a journal article, exported as `JOUR` and `@article`. A harvest run with `fields="extended"` carries the document type Scopus gives each record. A conference paper is then exported as `CPAPER` and `@inproceedings`, a chapter as `CHAP` and `@incollection` and a book as `BOOK` and `@book`. The entries of such a harvest also carry the volume, issue, pages and ISSN, and under `view="COMPLETE"` the abstract and the author keywords, which screening and de-duplication tools read. The docstrings of [`to_ris`][scopusflow.export.to_ris] and [`to_bibtex`][scopusflow.export.to_bibtex] list where each field goes.

In the BibTeX output, the citation keys are built from the leading word of the first author's name and the year, and made unique within the export so that biber does not reject duplicates. Scopus returns authors surname first, so that leading word is normally the surname. Because the bundled records put the given name first, their keys start with a given name. The three records below show two details worth checking. One has a journal name carrying an ampersand, which BibTeX has to escape, and the other two are papers by the same first author in the same year, whose keys would otherwise collide.

```python exec="1" source="material-block" session="building-a-reference-set"
ampersand = records[records["publication"].fillna("").str.contains("&")].head(1)
same_author = records[
    (records["authors"] == "Hao Yang") & (records["year"] == 2017)
]

out(sf.to_bibtex(pd.concat([ampersand, same_author])))
```

The `note` field that ordinarily carries the Scopus identifier is absent throughout, since the bundled records have none. A live harvest fills it, and drops it for any record where Scopus itself returned no identifier.

## Save the export

Both functions return a string, so writing the whole set is again a plain file write.

```python
from pathlib import Path

Path("reference-set.bib").write_text(sf.to_bibtex(records), encoding="utf-8")
Path("reference-set.ris").write_text(sf.to_ris(records), encoding="utf-8")
```

Most reference managers import a `.ris` file. Open it from Zotero or EndNote to bring the whole set into your library, or use the `.bib` file as the bibliography of a LaTeX project and cite by the keys it contains. The DOI list remains a lighter alternative when you only need to start an import by identifier and would rather let the reference manager fetch the metadata itself.
