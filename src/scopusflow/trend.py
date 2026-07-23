"""Summarise publication trends over time."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

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
    view: str = "STANDARD",
    **kwargs,
) -> pd.DataFrame:
    """Count Scopus hits for ``query`` in each of ``years`` without downloading them.

    Each year is a cheap result-size lookup, so this gives a publication trend
    far faster than harvesting every record.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
    years = list(years)
    if not years:
        raise ValueError("years must be a non-empty sequence.")

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    counts: dict[int, int] = {}
    for y in years:
        search = ScopusSearch(
            f"{query} AND PUBYEAR IS {y}", view=view, download=False, **kwargs
        )
        counts[int(y)] = int(search.get_results_size())
    return _trend_frame(counts)
