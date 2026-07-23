"""Cheap result-size lookups for quota-aware sizing: how many records a query
matches, without downloading them.
"""

from __future__ import annotations

from collections.abc import Sequence

from .query import wrap_field


def _count_query(query: str, years: Sequence[int] | None = None,
                 field: str | None = None) -> str:
    """Fold the field tag and a year filter into the query (PURE, offline)."""
    q = wrap_field(query, field)
    if years:
        ys = sorted({int(y) for y in years})
        if len(ys) == 1:
            q += f" AND PUBYEAR IS {ys[0]}"
        else:
            q += f" AND PUBYEAR AFT {ys[0] - 1} AND PUBYEAR BEF {ys[-1] + 1}"
    return q


def scopus_count(query: str, years: Sequence[int] | None = None,
                 field: str | None = None, view: str = "STANDARD",
                 **kwargs) -> int:
    """Return how many records the (optionally year-filtered) query matches.

    A single cheap request that does not download the records, so it is the right
    way to size a search before committing quota to a harvest.
    """
    if not query or not str(query).strip():
        raise ValueError("query must be a non-empty string.")
    q = _count_query(str(query).strip(), years, field)

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    return int(ScopusSearch(q, view=view, download=False, **kwargs).get_results_size())
