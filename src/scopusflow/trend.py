"""Summarise publication trends over time."""

from __future__ import annotations

import time
from collections.abc import Sequence

import pandas as pd

from ._pyb import require_init, result_size
from .plan import _check_years
from .query import _and_clause, _check_query, wrap_field

#: The stable column schema for a trend table.
TREND_COLUMNS = ["year", "n"]


def _trend_frame(counts: dict[int, int]) -> pd.DataFrame:
    """Assemble a ``{year: n}`` mapping into a tidy, year-sorted DataFrame."""
    rows = sorted((int(y), int(n)) for y, n in counts.items())
    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def year_counts(records: pd.DataFrame) -> pd.DataFrame:
    """Count records per publication year, dropping rows with a missing year.

    Returns a :data:`TREND_COLUMNS` frame sorted ascending by year, with both
    columns as plain integers.
    """
    years = pd.to_numeric(records["year"], errors="coerce").dropna()
    counts = {int(y): int(n) for y, n in years.astype(int).value_counts().items()}
    return _trend_frame(counts)


def scopus_trend(
    query: str,
    years: Sequence[int],
    field: str | None = None,
    view: str = "STANDARD",
    **kwargs,
) -> pd.DataFrame:
    """Count Scopus hits for ``query`` in each of ``years`` without downloading them.

    Each year is a cheap result-size lookup, so this gives a publication trend
    far faster than harvesting every record. ``field`` wraps the query in a
    Scopus field tag (see :data:`scopusflow.query.FIELD_TAGS`), the way
    :func:`scopusflow.count.scopus_count` and the R twin's ``scopus_trend()``
    do; left ``None``, the query is sent as given.

    Each count is sent with ``refresh=True`` unless you pass ``refresh``.
    pybliometrics keys its own response cache on the query string and view
    alone. Without ``refresh=True``, it could answer a year with the number of
    rows an earlier harvest of the same query left there. ``refresh=False``,
    or a number of days, opts in to that cache, and a year it answers is
    warned about. The key ignores keyword filters such as ``subj``, so fold any
    filter into the query before you opt in.

    Raises :class:`scopusflow.exceptions.ScopusFlowConfigError` before any
    request when ``pybliometrics.init()`` has not been called in the session.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
    # Checked offline first (see scopusflow.plan.SearchPlan), so a query the
    # API cannot run as written costs no request.
    _check_query(query, field)
    years = list(years)
    if not years:
        raise ValueError("years must be a non-empty sequence.")
    # Validated before it reaches the query: the year used to be
    # interpolated raw, so a float year sent the API "PUBYEAR IS 2015.0" while
    # the result was filed under 2015.
    years = _check_years(years)
    # Wrapped once, before the loop: the tag applies to the query alone, never
    # to the year
    # filter folded in beside it.
    query = wrap_field(query, field)
    kwargs.setdefault("refresh", True)
    require_init()

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    counts: dict[int, int] = {}
    for y in years:
        # Bracketed first when a top-level OR or AND NOT would otherwise take
        # the year filter from part of the query.
        year_query = _and_clause(query, f"PUBYEAR IS {y}")
        t0 = time.time()
        search = ScopusSearch(year_query, view=view, download=False, **kwargs)
        counts[y] = result_size(search, t0, kwargs["refresh"], year_query, stacklevel=2)
    return _trend_frame(counts)
