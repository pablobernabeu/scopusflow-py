# Author keywords and references

Keyword co-occurrence and citation-network analysis need a document's author-supplied keywords and its own reference list, which the Search API alone does not return. This guide covers how to retrieve them, what each costs and what your Scopus entitlement needs to cover.

The live-API examples are shown but not run, since they need a configured key. The shapes they return are put together offline from the harvest bundled with the package, 138 real articles on graphene supercapacitors that stand in for a retrieval because Scopus records may not be redistributed.

```python exec="1" session="keywords-and-references"
import html as _html
import pandas as pd
import scopusflow as sf


def _clean_table(html_table):
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
    elif isinstance(x, list):
        print("<pre><code>" + _html.escape(repr(x)) + "</code></pre>")
    else:
        print("<pre><code>" + _html.escape(str(x)) + "</code></pre>")
```

## Author keywords from a search

The Search API's `COMPLETE` view carries an `authkeywords` field alongside the usual title, DOI and date. The field adds no request of its own, but `COMPLETE` serves 25 records per page, against 200 for `STANDARD`. The same number of records therefore already takes more requests and more quota.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

plan = sf.SearchPlan("DOI(10.1038/nature14539)", view="COMPLETE")
recs = sf.fetch_plan(plan)
recs["authkeywords"]
```

In this package's development testing, this field came back `None` even on a live, otherwise fully entitled key, for documents that do carry author keywords in Scopus itself. This points to an entitlement gap specific to this field. If your own keywords come back all empty, it is worth raising with your Scopus/Elsevier account contact.

## References via Abstract Retrieval

The reference list is not available from Search under any view. It needs Abstract Retrieval's `FULL` or `REF` view, an entitlement separate from ordinary abstract access and from Search access. This is a per-document endpoint, so retrieving references for *n* documents under `FULL` costs *n* requests against Abstract Retrieval's own weekly quota, which is smaller than Search's.

```python
ab = sf.scopus_abstract(
    "10.1038/nature14539",
    view="FULL", include=("references", "keywords"),
)
ab.loc[0, "references"][["title", "authors", "sourcetitle", "publicationyear"]]
```

`view="FULL"` is the recommended default, since it returns the whole bibliography in one request. `view="REF"` serves it about 40 references at a time. pybliometrics pages REF itself, following the view's `startref` parameter until the list is complete, so a document with *N* references costs `ceil(N / 40)` requests under `REF`. `n_requests` still counts each document once, however many pages pybliometrics requested for it. `scopus_abstract()` warns when the number of references returned does not match the document's own reported count. Author keywords come only with `FULL`, so `include=("keywords",)` under any other view raises `ValueError` before a request.

The shape `scopus_abstract()` returns is one DataFrame per document with pybliometrics' native reference fields. To show that shape offline, the frame below relabels three bundled records into those fields, as though they were works cited by a fourth document. In a live result, the `id` column holds a Scopus identifier, which the bundled records do not carry, and `citedbycount` often comes back empty, so both are left empty here.

```python exec="1" source="material-block" session="keywords-and-references"
cited = sf.example_records().head(3)
references = pd.DataFrame({
    "position": [str(i) for i in range(1, len(cited) + 1)],
    "id": pd.NA,
    "doi": cited["doi"].to_numpy(),
    "title": cited["title"].to_numpy(),
    "authors": cited["authors"].to_numpy(),
    "sourcetitle": cited["publication"].to_numpy(),
    "publicationyear": cited["year"].astype(str).to_numpy(),
    "citedbycount": pd.NA,
})
out(references[["title", "authors", "sourcetitle", "publicationyear"]])
```

The number of requests spent and the remaining Abstract Retrieval quota are attached to the result's `attrs`, since that smaller quota is easy to exhaust unnoticed.

```python
ab.attrs["n_requests"]   # requests spent so far
ab.attrs["quota"]["remaining"]
```

A key or subscription tier that does not cover the requested view raises `scopusflow.ScopusFlowForbiddenError` naming the view. It also stops the whole batch, because entitlement is a property of the account and the same error would recur for every remaining identifier.

A spent weekly quota stops the requests as well, but `scopus_abstract()` keeps what the batch holds. pybliometrics raises `Scopus429Error` once the quota of every configured key is spent, and `scopus_abstract()` then returns the rows already retrieved, gives each identifier not retrieved a row of NA and warns once with `scopusflow.ScopusFlowQuotaWarning`. The NA rows are not checkpointed, so, with `cache_dir` set, a run after the reset requests only the identifiers still missing.

For more than a handful of identifiers, pass `cache_dir` so an interrupted or quota-limited batch resumes without spending quota again on the identifiers it has already retrieved. pybliometrics' own on-disk response cache, keyed by identifier and view under its configured cache directory and controlled by its `refresh` parameter, already avoids repeat network calls for the same identifier across script runs. `cache_dir` adds batch-level progress and resumability across many identifiers. A row read from either cache sent no request, so `n_requests` leaves it out, and its citation count dates from when the cache was written. Pass `refresh=True` to fetch every identifier afresh.

The identifiers are checked before the first request. A missing or blank one raises `ValueError` naming its position, so drop those records first, or let `corpus()` drop them. Surrounding whitespace is trimmed and a `SCOPUS_ID:` prefix is dropped under `by="scopus_id"`.

```python
dois = sf.extract_dois(recs)

ab = sf.scopus_abstract(
    dois, view="FULL", include=("references", "keywords"),
    cache_dir="abstract-cache",
)
```

## Index keywords

Scopus records a second kind of keyword. Authors choose their own keywords, whereas Scopus chooses the index keywords and standardises them to vocabularies derived from thesauri Elsevier owns or licenses, with synonyms, spellings and plurals brought together. `include=("index_terms",)` adds them as an `idxterms` column, read from pybliometrics' `idxterms` and joined with `"; "` as the author keywords are. Like the author keywords, they come only with `view="FULL"`, in the same request.

```python
ab = sf.scopus_abstract(
    "10.1038/nature14539",
    view="FULL", include=("keywords", "index_terms"),
)
ab.loc[0, "idxterms"]
```

Elsevier's guide lists index keywords in the `FULL` view as not available by default, so whether they arrive depends on your key's entitlement. In this package's development testing, they did arrive on the same key whose author keywords came back empty. Where that happens, the index keywords may be the only keyword signal a Scopus harvest can give, but the two kinds are not interchangeable. A standard vocabulary merges terms that authors phrase differently, so the two give different co-occurrence networks from the same documents, and a study should say which it used.

## A minimal, cross-tool corpus

[`corpus`][scopusflow.corpus.corpus] combines a search result with this Abstract Retrieval step. It returns a minimal shape close to what OpenAlex's `works` API already returns: `id`, `scopus_id`, `title`, `year`, `keywords` (a list of strings per row) and `references` (a DataFrame of cited works per row). A bibliometrics export holds the references as a semicolon-joined citation string instead. `corpus()` does not replace [`to_bibtex`][scopusflow.export.to_bibtex]/[`to_ris`][scopusflow.export.to_ris], which keep their own established interchange formats.

```python
recs = sf.fetch_plan(sf.SearchPlan("DOI(10.1038/nature14539)"))
corpus = sf.corpus(recs, view="FULL")
corpus.loc[0, "keywords"]
len(corpus.loc[0, "references"])
```

This costs one Abstract Retrieval request per record in `recs`, on top of whatever retrieved `recs` in the first place. The keywords column, split from the joined `authkeywords` field, is a list per row, which is the shape co-occurrence analysis needs. `keywords="index"` fills it with the index keywords instead, and `keywords="both"` with the author keywords followed by each index keyword not already among them. Either costs what the default costs, and both need `view="FULL"`. Under `view="REF"`, only the references are requested, since that view carries no author keywords, and every keywords entry is empty. With `keywords="both"`, the match is on the exact text, so `"graphene"` from the author and `"Graphene"` from the index both stay.

```python
corpus = sf.corpus(recs, view="FULL", keywords="both")
```

Counting every unordered pair of keywords within each document gives the co-occurrence table the guide opened on, and standard library tools are enough for it. Author keywords are one of the fields that cannot be included with the package, so the frame below replaces them with terms from each bundled record's own title. It keeps a fixed vocabulary of terms and records those a title mentions. That is a cruder signal than an author keyword list, but the counting is identical and it runs over 138 published titles.

```python exec="1" source="material-block" session="keywords-and-references"
import itertools
from collections import Counter

vocabulary = ["graphene", "supercapacitor", "electrode", "energy storage",
              "flexible", "electrochemical"]

title_terms = (
    sf.example_records()[["doi", "title", "year"]]
    .rename(columns={"doi": "id"})
)
title_terms["keywords"] = [
    [term for term in vocabulary if term in title.lower()]
    for title in title_terms["title"]
]
out(title_terms.loc[title_terms["keywords"].str.len() > 1, ["title", "keywords"]].head(3))
```

```python exec="1" source="material-block" session="keywords-and-references"
counts = Counter(
    pair
    for keywords in title_terms["keywords"]
    for pair in itertools.combinations(sorted(keywords), 2)
)
pairs = pd.DataFrame(
    [(a, b, n) for (a, b), n in counts.most_common()],
    columns=["keyword A", "keyword B", "documents"],
)
out(pairs.head())
```

Each row is one pair of keywords and the number of documents carrying both, which is the edge list a co-occurrence network is built from.

## Handing the corpus to theoryforge

theoryforge maps a literature from a corpus file in its own schema, and [`write_corpus`][scopusflow.corpus.write_corpus] writes one from a `corpus()` result. The file needs a name for the corpus, since the result carries none.

```python
sf.write_corpus(corpus, "corpus.json", "graphene-supercapacitors")
```

theoryforge compares cited works as exact strings, so the writer gives each one a single key across the corpus, its Scopus identifier, as `scopus:<id>`. Scopus gives a cited work's DOI in some bibliographies only, and in different cases. A key built from the DOI wherever there is one would therefore split the work into several nodes and lose its co-citation edges. A reference that carries only a DOI takes the identifier that another reference pairs with the same DOI, and a DOI that nothing pairs with is keyed as `doi:<doi>`, lower-cased. Keywords are lower-cased as well, so the `"graphene"` and `"Graphene"` that `keywords="both"` keeps apart become one.

[`to_theoryforge_corpus`][scopusflow.corpus.to_theoryforge_corpus] returns the same document as a dict. The block below runs it on two bundled records, each made to cite the same two others, the second with the DOIs in capitals. In the output, both records cite the same two keys.

```python exec="1" source="material-block" session="keywords-and-references"
docs = sf.example_records().dropna(subset=["doi"]).head(4)
cited = list(docs["doi"].iloc[2:4])


def cites(dois):
    return pd.DataFrame({"id": [None] * len(dois), "doi": dois})


frame = pd.DataFrame({
    "id": list(docs["doi"].iloc[:2]),
    "title": list(docs["title"].iloc[:2]),
    "year": list(docs["year"].iloc[:2]),
    "keywords": [["Graphene", "supercapacitor"], ["graphene"]],
    "references": [cites(cited), cites([d.upper() for d in cited])],
})
doc = sf.to_theoryforge_corpus(frame, "graphene-supercapacitors")
out([record["references"] for record in doc["records"]])
```

The file also carries a `provenance` block recording the search expression, when the search ran and the kind of keyword, with counts of the references dropped and of the records without keywords. An entitlement that returns no author keywords shows up in that last count, and it leaves theoryforge's keyword themes empty whatever the writer does.
