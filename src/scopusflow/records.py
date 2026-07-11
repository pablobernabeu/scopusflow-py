"""Normalise pybliometrics results into one stable record schema."""

from __future__ import annotations

import pandas as pd

#: The stable column schema for a record table.
RECORD_COLUMNS = [
    "entry_number", "scopus_id", "doi", "title", "authors",
    "year", "date", "publication", "citations", "query",
]


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _year(date) -> "int | pd._libs.missing.NAType":
    if not date:
        return pd.NA
    head = str(date)[:4]
    return int(head) if head.isdigit() else pd.NA


def to_records(results, query: str | None = None, view: str | None = None) -> pd.DataFrame:
    """Normalise a pybliometrics ``ScopusSearch().results`` list (named tuples)
    or a list of dicts into a tidy :data:`RECORD_COLUMNS` DataFrame.

    Whatever the query type, the columns are the same, so the downstream DOI,
    diff and analysis helpers can rely on them.

    When ``view="COMPLETE"``, an ``authkeywords`` column is added: the author-
    supplied keywords the Scopus Search API returns under that view, as a
    single string in Scopus's own ``" | "``-delimited form (``None`` when the
    document has none, or when the API omits the field for a given key's
    entitlement: this was observed directly against a live, otherwise
    fully-entitled key during development, on documents that do carry author
    keywords in Scopus itself, so an all-``None`` column is more likely an
    entitlement gap worth raising with your Scopus/Elsevier account contact
    than genuinely absent data). Any other ``view``, including the default
    ``None``, reproduces :data:`RECORD_COLUMNS` exactly, so existing callers
    that never pass ``view`` see no change at all.
    """
    add_keywords = view == "COMPLETE"
    columns = [*RECORD_COLUMNS, "authkeywords"] if add_keywords else RECORD_COLUMNS
    rows = []
    for i, r in enumerate(results or [], start=1):
        eid = _get(r, "eid")
        scopus_id = str(eid).split("2-s2.0-")[-1] if eid else pd.NA
        date = _get(r, "coverDate")
        cited = _get(r, "citedby_count")
        row = {
            "entry_number": i,
            "scopus_id": scopus_id,
            "doi": _get(r, "doi"),
            "title": _get(r, "title"),
            # pybliometrics joins multiple authors with ';' in author_names.
            "authors": _get(r, "author_names") or _get(r, "creator"),
            "year": _year(date),
            "date": date,
            "publication": _get(r, "publicationName"),
            "citations": int(cited) if cited not in (None, "") else pd.NA,
            "query": query,
        }
        if add_keywords:
            row["authkeywords"] = _get(r, "authkeywords") or pd.NA
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def top(records: pd.DataFrame, by: str = "source", n: int = 10) -> pd.DataFrame:
    """Tally the most frequent sources or authors in a record set."""
    if by == "source":
        values = records["publication"].dropna()
    elif by == "author":
        values = (
            records["authors"].dropna().str.split(";").explode().str.strip()
        )
        values = values[values != ""]
    else:
        raise ValueError("by must be 'source' or 'author'.")
    counts = values.value_counts().head(n)
    return counts.rename_axis("value").reset_index(name="n")
