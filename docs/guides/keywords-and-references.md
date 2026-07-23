# Author keywords and references

Keyword co-occurrence and citation-network analysis both need something the Search API alone does not return: a document's author-supplied keywords, and its own reference list. This walks through retrieving both, what each costs, and what your Scopus entitlement needs to cover. The live-API examples are shown rather than run, since they need a configured key. The shapes they return are put together offline from the corpus bundled with the package, 138 real articles on graphene supercapacitors that stand in for a retrieval because Scopus records may not be redistributed.

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

The Search API's `COMPLETE` view carries an `authkeywords` field alongside the usual title, DOI and date. Requesting it costs no extra request beyond `COMPLETE`'s own smaller page size (25 records per page, against 200 for `STANDARD`), which already means more requests, and so more quota, for the same number of records.

```python
import scopusflow as sf

plan = sf.SearchPlan("DOI(10.1038/nature14539)", view="COMPLETE")
recs = sf.fetch_plan(plan)
recs["authkeywords"]
```

In development, this field came back `None` even on a live, otherwise fully-entitled key, for documents that do carry author keywords in Scopus itself, which points to an entitlement gap specific to this one field rather than the documents genuinely having none. If your own keywords come back all empty, it is worth raising with your Scopus/Elsevier account contact.

## References via Abstract Retrieval

The reference list is not available from Search under any view; it needs Abstract Retrieval's `FULL` or `REF` view, an entitlement separate from ordinary abstract access and from Search access. This is a per-document endpoint, so retrieving references for *n* documents costs *n* requests against Abstract Retrieval's own, smaller weekly quota, separate from Search's.

```python
ab = sf.scopus_abstract(
    "10.1038/nature14539",
    view="FULL", include=("references", "keywords"),
)
ab.loc[0, "references"][["title", "authors", "sourcetitle", "publicationyear"]]
```

`view="FULL"` is the recommended default: in development, it returned a complete, correctly counted reference list for every document tried, while `view="REF"` returned an inconsistent, sometimes-truncated subset, on an otherwise identical request made moments apart. `scopus_abstract()` warns when the number of references returned does not match the document's own reported count, rather than returning a partial list silently.

The shape it returns is one DataFrame per document with pybliometrics' own native reference fields. To show that shape offline, the frame below re-labels three bundled records into those fields, as though they were works cited by a fourth. The `id` column is a Scopus identifier in a live result, which the bundled records do not carry, and `citedbycount` comes back empty often enough in practice that it is left so here.

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

```python
ab.attrs["n_requests"]   # requests spent so far
ab.attrs["quota"]["remaining"]
```

A key or subscription tier that does not cover the requested view raises `scopusflow.ScopusFlowForbiddenError` naming the view, rather than a generic HTTP failure, and stops the whole batch rather than repeating the same failure for every remaining identifier, since entitlement is an account-level property, not a per-document one.

For more than a handful of identifiers, pass `cache_dir` so an interrupted or quota-limited batch resumes without re-spending quota already spent. Relying on pybliometrics' own on-disk response cache (its `refresh` parameter, keyed by identifier and view under its configured cache directory) already avoids repeat network calls for the *same* identifier across script runs; `cache_dir` here is for batch-level progress and resumability across *many* identifiers, a separate concern.

```python
dois = sf.extract_dois(recs)

ab = sf.scopus_abstract(
    dois, view="FULL", include=("references", "keywords"),
    cache_dir="abstract-cache",
)
```

## A minimal, cross-tool corpus

[`corpus`][scopusflow.corpus.corpus] combines a search result with this Abstract Retrieval step, returning a minimal shape close to what OpenAlex's `works` API already returns: `id`, `title`, `year`, `keywords` (a list of strings per row) and `references` (a DataFrame of cited works per row), rather than a semicolon-joined citation string. It does not replace [`to_bibtex`][scopusflow.export.to_bibtex]/[`to_ris`][scopusflow.export.to_ris], which keep their own established interchange formats.

```python
recs = sf.fetch_plan(sf.SearchPlan("DOI(10.1038/nature14539)"))
corpus = sf.corpus(recs, view="FULL")
corpus.loc[0, "keywords"]
len(corpus.loc[0, "references"])
```

This costs one Abstract Retrieval request per record in `recs`, on top of whatever retrieved `recs` in the first place. The keywords column, split from the joined `authkeywords` field, is a list per row, which is the shape co-occurrence analysis wants. Counting every unordered pair within each document gives the co-occurrence table the guide opened on, and standard library tools are enough for it.

Author keywords are one of the fields that cannot travel with the package, so the frame below stands them in from each bundled record's own title, keeping a fixed vocabulary of terms and recording those a title mentions. That is a cruder signal than a real keyword list, but the counting is identical and it runs over 138 genuine titles.

```python exec="1" source="material-block" session="keywords-and-references"
import itertools
from collections import Counter

vocabulary = ["graphene", "supercapacitor", "electrode", "energy storage",
              "flexible", "electrochemical"]

corpus = sf.example_records()[["doi", "title", "year"]].rename(columns={"doi": "id"})
corpus["keywords"] = [
    [term for term in vocabulary if term in title.lower()]
    for title in corpus["title"]
]
out(corpus.loc[corpus["keywords"].str.len() > 1, ["title", "keywords"]].head(3))
```

```python exec="1" source="material-block" session="keywords-and-references"
counts = Counter(
    pair
    for keywords in corpus["keywords"]
    for pair in itertools.combinations(sorted(keywords), 2)
)
pairs = pd.DataFrame(
    [(a, b, n) for (a, b), n in counts.most_common()],
    columns=["keyword A", "keyword B", "documents"],
)
out(pairs.head())
```

Each row is one pair of keywords and the number of documents carrying both, which is the edge list a co-occurrence network is built from.
