# Building a reference set

A retrieval becomes useful once it leaves the package, as a reading list in a reference manager or as input to a writing project. This guide covers that export end of the workflow, taking a set of records from the API through a clean DOI list and on into the two interchange formats that reference managers read. The worked output runs on the harvest bundled with the package, 138 real articles on graphene supercapacitors, since records retrieved from Scopus may not be redistributed and no key is assumed here. The live call that would replace it is shown first.

```python exec="1" session="building-a-reference-set"
import scopusflow as sf
import pandas as pd
import html as _html


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

## Fetch the record set

Everything here starts from a frame of records. You build one by running a [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], which drives pybliometrics one cell at a time and returns a single frame with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. This step contacts the Scopus API, so it needs a working API key configured for pybliometrics. Run it once and keep the frame in hand for the rest of the guide.

```python
import scopusflow as sf

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")

records = sf.fetch_plan(plan, cache_dir="graphene-harvest")
records.shape
```

[`example_records`][scopusflow.data.example_records] returns the bundled stand-in for that harvest, which is what the output below runs on. The result is an ordinary pandas DataFrame underneath, so it drops straight into any analysis you already have. The columns are always the same whatever the query was, which is what lets the DOI and export helpers that follow rely on them.

```python exec="1" source="material-block" session="building-a-reference-set"
records = sf.example_records()
out(records[["title", "year", "doi"]].head())
```

## A clean, deduplicated DOI list

Reference managers such as Zotero import most reliably from DOIs. [`extract_dois`][scopusflow.diff.extract_dois] pulls them from the `doi` column, strips any resolver prefix or `doi:` label, and removes duplicates compared case-insensitively, so the same article imports once even when its DOI was stored with a `https://doi.org/` prefix or in a different case.

```python exec="1" source="material-block" session="building-a-reference-set"
dois = sf.extract_dois(records)
out(dois[:5])
```

The function works offline because it only reads the frame you already hold. It returns a plain Python list rather than writing a file, so you stay in control of where anything lands. The list runs to 127 entries against 138 records, because the eleven records that carry no DOI are dropped rather than passed on as blanks.

De-duplication earns its keep once two retrievals are put together. Concatenating a pull of 2015 to 2020 with a later one of 2019 onwards repeats every record in the two overlapping years, and a reference manager fed the raw column would import each of those twice. To show what the cleaning has to see through, the second copy of one DOI is rewritten here into the resolver form an aggregator often hands back.

```python exec="1" source="material-block" session="building-a-reference-set"
import pandas as pd

combined = pd.concat(
    [records[records["year"] <= 2020], records[records["year"] >= 2019]],
    ignore_index=True,
)
repeat = combined.index[combined.duplicated("entry_number") & combined["doi"].notna()][0]
combined.loc[repeat, "doi"] = "https://doi.org/" + combined.loc[repeat, "doi"].upper()

all_dois = sf.extract_dois(combined, dedupe=False)
out((len(combined), len(all_dois), len(sf.extract_dois(combined))))
```

The 170 concatenated records yield 155 raw DOIs, the difference being the records with none, and 127 once duplicates are removed. The rewritten entry collapses into its plain twin, since the comparison ignores both the resolver prefix and the letter case. Subtracting one count from the other is the quickest way to see how much overlap two retrievals produced. Pass `dedupe=False` when you want the repeats kept, for instance to count how often a DOI recurs across cells.

Writing the list out is then a one-liner with the standard library, which keeps the package free of any implicit filesystem writes.

```python
from pathlib import Path

Path("reference-set.txt").write_text("\n".join(dois), encoding="utf-8")
```

## Render to BibTeX and RIS

A DOI list is enough for an import-by-identifier, but a full record carries more. [`to_bibtex`][scopusflow.export.to_bibtex] and [`to_ris`][scopusflow.export.to_ris] render the set in the two formats that reference managers read, so a search moves straight into Zotero, EndNote, Mendeley or a LaTeX bibliography. Each record becomes one entry, and both functions are pure and offline, returning a string rather than touching disk. The first three records make the point, the second of them being one of the eleven with no DOI, which simply loses its `DO` line rather than carrying an empty one.

```python exec="1" source="material-block" session="building-a-reference-set"
out(sf.to_ris(records.head(3)))
```

An author string holding several names is split into one `AU` line each. That is not visible above, because the bundled records name only the first author of each paper, whereas a live Scopus harvest returns the full semicolon-joined list and every name in it gets its own line.

BibTeX works the same way, one `@article` entry per record. The citation keys are built from the leading word of the first author's name and the year, and made unique within the export so that biber does not reject duplicates. Scopus returns authors surname first, so that leading word is normally the surname; the bundled records give the given name first, which is why the keys below read the way they do. The three records here are chosen to show the two details worth checking, a journal name carrying an ampersand, which BibTeX has to escape, and two papers by the same first author in the same year, whose keys would otherwise collide.

```python exec="1" source="material-block" session="building-a-reference-set"
ampersand = records[records["publication"].fillna("").str.contains("&")].head(1)
same_author = records[(records["authors"] == "Hao Yang") & (records["year"] == 2017)]

out(sf.to_bibtex(pd.concat([ampersand, same_author])))
```

The `note` field that ordinarily carries the Scopus identifier is absent throughout, since the bundled records have none. A live harvest fills it, and drops it for any record where Scopus itself returned no identifier.

## Save the export

Because both functions hand back a string, writing the whole set is again a plain file write, in whichever format your downstream tool expects. A `.bib` file feeds a LaTeX bibliography directly, while a `.ris` file imports into most reference managers.

```python
from pathlib import Path

Path("reference-set.bib").write_text(sf.to_bibtex(records), encoding="utf-8")
Path("reference-set.ris").write_text(sf.to_ris(records), encoding="utf-8")
```

From there the search is portable. Open the `.ris` file from Zotero or EndNote to bring the whole set into your library, or point a LaTeX project at the `.bib` file and cite by the keys it contains. The DOI list remains a lighter alternative when you only need to seed an import by identifier and would rather let the reference manager fetch the metadata itself.
