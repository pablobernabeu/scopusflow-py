"""Batch abstract retrieval, resilient per id, mirroring ``scopus_abstract``."""

from __future__ import annotations

import warnings

import pandas as pd

#: The stable column schema for retrieved abstracts.
ABSTRACT_COLUMNS = [
    "scopus_id", "doi", "title", "abstract",
    "publication", "date", "year", "citations",
]

#: Map the user-facing ``by`` argument to a pybliometrics ``id_type``.
_ID_TYPES = {"doi": "doi", "eid": "eid", "scopus_id": "scopus_id"}


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _abstract_row(obj) -> dict:
    """Normalise a single ``AbstractRetrieval``-like object (or dict) into the
    stable :data:`ABSTRACT_COLUMNS` mapping; pure, offline, no network."""
    eid = _get(obj, "eid")
    scopus_id = str(eid).split("2-s2.0-")[-1] if eid else pd.NA
    date = _get(obj, "coverDate")
    head = str(date)[:4] if date else ""
    year = int(head) if head.isdigit() else pd.NA
    cited = _get(obj, "citedby_count")
    citations = int(cited) if cited not in (None, "") else pd.NA
    return {
        "scopus_id": scopus_id,
        "doi": _get(obj, "doi"),
        "title": _get(obj, "title"),
        "abstract": _get(obj, "description"),
        "publication": _get(obj, "publicationName"),
        "date": date,
        "year": year,
        "citations": citations,
    }


def scopus_abstract(
    ids,
    by: str = "doi",
    view: str = "META",
    **kwargs,
) -> pd.DataFrame:
    """Retrieve abstracts for one or many ids, resilient per id.

    ``by`` selects the lookup type ("doi", "eid" or "scopus_id"). Any id that
    fails is warned about and yields an all-NA row that still records the id.
    """
    if by not in _ID_TYPES:
        raise ValueError("by must be one of 'doi', 'eid', 'scopus_id'.")
    id_type = _ID_TYPES[by]
    id_column = "doi" if by == "doi" else "scopus_id"

    if isinstance(ids, str):
        ids = [ids]

    # Resolve the dependency once: a missing pybliometrics is a setup error and
    # must surface clearly, not masquerade as every id failing to retrieve.
    from pybliometrics.scopus import AbstractRetrieval  # lazy; needs a key

    rows = []
    for ident in ids:
        try:
            ab = AbstractRetrieval(ident, id_type=id_type, view=view, **kwargs)
            rows.append(_abstract_row(ab))
        except Exception:  # one bad id must not sink the batch
            warnings.warn(
                f"Could not retrieve abstract for {ident!r}; recording NA row.",
                stacklevel=2,
            )
            row = {col: pd.NA for col in ABSTRACT_COLUMNS}
            row[id_column] = ident
            rows.append(row)
    return pd.DataFrame(rows, columns=ABSTRACT_COLUMNS)
