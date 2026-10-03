"""Cheap result-size lookups for quota-aware sizing: how many records a query
matches, without downloading them.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from ._pyb import require_init, result_size
from .plan import _check_years
from .query import _and_clause, _check_query, wrap_field


def _count_query(query: str, years: Sequence[int] | None = None,
                 field: str | None = None) -> str:
    """Fold the field tag and a year filter into the query (PURE, offline).

    The query is bracketed before the filter only when a top-level operator
    would otherwise regroup it (see :func:`scopusflow.query._and_clause`).
    """
    q = wrap_field(query, field)
    if years:
        ys = sorted(set(_check_years(years)))
        if len(ys) == 1:
            q = _and_clause(q, f"PUBYEAR IS {ys[0]}")
        else:
            q = _and_clause(q, f"PUBYEAR AFT {ys[0] - 1} AND PUBYEAR BEF {ys[-1] + 1}")
    return q


def scopus_count(query: str, years: Sequence[int] | None = None,
                 field: str | None = None, view: str = "STANDARD",
                 **kwargs) -> int:
    """Return how many records the (optionally year-filtered) query matches.

    A single cheap request that does not download the records, so it is the right
    way to size a search before committing quota to a harvest.

    The request is sent with ``refresh=True`` unless you pass ``refresh``.
    pybliometrics keys its own response cache on the query string and view
    alone. Without ``refresh=True``, it would answer a query an earlier harvest
    downloaded with the number of rows the harvest left there, and make no
    request. ``refresh=False``, or a number of days, opts in to that cache, and
    a count it answers is warned about. The key ignores keyword filters such as
    ``subj``, so fold any filter into the query before you opt in.

    Raises :class:`scopusflow.exceptions.ScopusFlowConfigError` before any
    request when ``pybliometrics.init()`` has not been called in the session.
    """
    if not query or not str(query).strip():
        raise ValueError("query must be a non-empty string.")
    # Checked offline first (see scopusflow.plan.SearchPlan), so a query the
    # API cannot run as written costs no request.
    _check_query(str(query).strip(), field)
    q = _count_query(str(query).strip(), years, field)
    kwargs.setdefault("refresh", True)
    require_init()

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    t0 = time.time()
    search = ScopusSearch(q, view=view, download=False, **kwargs)
    return result_size(search, t0, kwargs["refresh"], q, stacklevel=2)
