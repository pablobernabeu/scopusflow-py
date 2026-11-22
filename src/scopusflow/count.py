"""Count the records a query matches without downloading them, to size a search
before a harvest spends quota on it.
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
    """Return how many records the query matches, optionally within a range of years.

    It makes one request and downloads no records, so it can size a search
    before a harvest spends quota on it.

    ``years`` are sent as one inclusive range from the earliest year to the
    latest, so ``years=[2015, 2020]`` counts every year from 2015 to 2020.
    [`scopus_intersections`][scopusflow.intersections.scopus_intersections] and
    a [`SearchPlan`][scopusflow.plan.SearchPlan] with ``partition="none"`` do
    the same, while [`scopus_trend`][scopusflow.trend.scopus_trend],
    [`compare_topics`][scopusflow.compare.compare_topics] and
    ``partition="year"`` take each listed year.

    ``field`` wraps the query in a Scopus field tag (see
    [`FIELD_TAGS`][scopusflow.query.FIELD_TAGS]) before the year limit is
    appended, as a plan's ``field`` does. Left ``None``, the query is sent as
    written. ``view`` and any further keyword argument go to pybliometrics'
    ``ScopusSearch``.

    The request is sent with ``refresh=True`` unless you pass ``refresh``.
    pybliometrics keys its own response cache on the query string and view
    alone. Without ``refresh=True``, it would answer a query an earlier harvest
    downloaded with the number of rows the harvest left there, and make no
    request. ``refresh=False``, or a number of days, uses that cache, and a
    count it answers gives a warning. The cache key ignores keyword filters
    such as ``subj``, so write any filter into the query before you use the
    cache.

    The query is checked offline first, as
    [`SearchPlan`][scopusflow.plan.SearchPlan] checks it, so an empty query or
    one the checks refuse raises ``ValueError`` before any request.

    Raises [`ScopusFlowConfigError`][scopusflow.exceptions.ScopusFlowConfigError]
    before any request when ``pybliometrics.init()`` has not been called in the
    session.
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
