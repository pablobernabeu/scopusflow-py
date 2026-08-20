"""Summarise publication trends over time."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .plan import _check_years
from .query import wrap_field

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
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
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

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    counts: dict[int, int] = {}
    for y in years:
        search = ScopusSearch(
            f"{query} AND PUBYEAR IS {y}", view=view, download=False, **kwargs
        )
        counts[y] = int(search.get_results_size())
    return _trend_frame(counts)
