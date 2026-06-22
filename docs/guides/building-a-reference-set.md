# Building a reference set

A retrieval becomes useful once it leaves the package, as a reading list in a reference manager or as input to a writing project. This guide covers that export end of the workflow, taking a set of records from the API through a clean DOI list and on into the two interchange formats that reference managers read.

## Fetch the record set

Everything here starts from a frame of records. You build one by running a [`SearchPlan`][scopusflow.plan.SearchPlan] through [`fetch_plan`][scopusflow.fetch.fetch_plan], which drives pybliometrics one cell at a time and returns a single frame with the stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema. This step contacts the Scopus API, so it needs a working API key configured for pybliometrics. Run it once and keep the frame in hand for the rest of the guide.

```python
import scopusflow as sf

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2018, 2023), partition="year")

records = sf.fetch_plan(plan, cache_dir="graphene-harvest")
records.shape
```

The result is an ordinary pandas DataFrame underneath, so it drops straight into any analysis you already have. The columns are always the same whatever the query was, which is what lets the DOI and export helpers that follow rely on them.

```python
records[["title", "year", "doi"]].head()
```

## A clean, deduplicated DOI list

Reference managers such as Zotero import most reliably from DOIs. [`extract_dois`][scopusflow.diff.extract_dois] pulls them from the `doi` column, strips any resolver prefix or `doi:` label, and removes duplicates compared case-insensitively, so the same article imports once even when its DOI was stored with a `https://doi.org/` prefix or in a different case.

```python
dois = sf.extract_dois(records)
dois[:5]
```

The function works offline because it only reads the frame you already hold. It returns a plain Python list rather than writing a file, so you stay in control of where anything lands. Pass `dedupe=False` if you want to keep every occurrence, for instance to count how often a DOI recurs across cells.

```python
all_dois = sf.extract_dois(records, dedupe=False)
len(all_dois), len(dois)
```

Writing the list out is then a one-liner with the standard library, which keeps the package free of any implicit filesystem writes.

```python
from pathlib import Path

Path("reference-set.txt").write_text("\n".join(dois), encoding="utf-8")
```

## Render to BibTeX and RIS

A DOI list is enough for an import-by-identifier, but a full record carries more. [`to_bibtex`][scopusflow.export.to_bibtex] and [`to_ris`][scopusflow.export.to_ris] render the set in the two formats that reference managers read, so a search moves straight into Zotero, EndNote, Mendeley or a LaTeX bibliography. Each record becomes one entry with its authors split out, and both functions are pure and offline, returning a string rather than touching disk.

```python
ris = sf.to_ris(records)
print(ris[:320])
```

BibTeX works the same way, one `@article` entry per record. The citation keys are built from the first author's surname and the year, and made unique within the export so that biber does not reject duplicates.

```python
bibtex = sf.to_bibtex(records)
print(bibtex[:320])
```

## Save the export

Because both functions hand back a string, writing the whole set is again a plain file write, in whichever format your downstream tool expects. A `.bib` file feeds a LaTeX bibliography directly, while a `.ris` file imports into most reference managers.

```python
from pathlib import Path

Path("reference-set.bib").write_text(sf.to_bibtex(records), encoding="utf-8")
Path("reference-set.ris").write_text(sf.to_ris(records), encoding="utf-8")
```

From there the search is portable. Open the `.ris` file from Zotero or EndNote to bring the whole set into your library, or point a LaTeX project at the `.bib` file and cite by the keys it contains. The DOI list remains a lighter alternative when you only need to seed an import by identifier and would rather let the reference manager fetch the metadata itself.
