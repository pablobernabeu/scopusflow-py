"""Summarise publication trends over time."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

import pandas as pd

from ._provenance import as_datetime, iso_utc
from ._pyb import UNDATED, require_init, result_size_and_time
from .plan import _check_years
from .query import _and_clause, _check_query, wrap_field
from .report import _searched_years, _utc

#: The stable column schema for a trend table.
TREND_COLUMNS = ["year", "n"]


def _trend_frame(counts: dict[int, int]) -> pd.DataFrame:
    """Assemble a ``{year: n}`` mapping into a tidy, year-sorted DataFrame."""
    rows = sorted((int(y), int(n)) for y, n in counts.items())
    # dtype is set, so an empty mapping still gives integer columns.
    return pd.DataFrame(rows, columns=TREND_COLUMNS).astype("int64")


def year_counts(records: pd.DataFrame, fill: bool = True) -> pd.DataFrame:
    """Count records per publication year, dropping rows with a missing year.

    Returns a [`TREND_COLUMNS`][scopusflow.trend.TREND_COLUMNS] frame sorted
    ascending by year, with both columns as plain integers.

    With ``fill`` (the default), every year the records' searches covered is
    counted, a year without records as zero.
    [`plot_trend`][scopusflow.plots.plot_trend] therefore draws the line down
    to zero there. The years searched are read from the plan in
    ``records.attrs["plan"]``, which
    [`fetch_plan`][scopusflow.fetch.fetch_plan] attaches: the year of each cell
    under ``partition="year"``, and every year of the range under
    ``partition="none"``. A year no cell searched is not added, so a plan over
    2015, 2016, 2019 and 2020 gives no row for 2017 or 2018. A harvest stopped
    before its last cell covers only the cells it ran. Without a plan, or with
    one that sent no year limit, the years run from the first year in the
    records to the last. A year that holds records keeps its row in every case,
    and a set in which no record has a year gives an empty frame. The R twin's
    ``autoplot()`` counts a record set's years by the same rule.

    ``fill=False`` counts only the years that hold records.

    The records' ``attrs["retrieved_at"]`` is carried to the result, so
    [`plot_trend`][scopusflow.plots.plot_trend] can say when the last year
    plotted was still being indexed.
    """
    years = pd.to_numeric(records["year"], errors="coerce").dropna()
    counts = {int(y): int(n) for y, n in years.astype(int).value_counts().items()}
    if fill and counts:
        span = _searched_years(records) or range(min(counts), max(counts) + 1)
        for year in span:
            counts.setdefault(int(year), 0)
    out = _trend_frame(counts)
    stamp = records.attrs.get("retrieved_at")
    if stamp is not None:
        out.attrs["retrieved_at"] = stamp
    return out


def _incomplete_note(years: Iterable, retrieved_at) -> str | None:
    """The note a record-count figure carries when the years it plots reach the
    year its counts were retrieved in.

    Scopus is updated daily, so a count for the year of retrieval, or for a
    later year that an article in press already carries, was a count so far. A
    final point that drops is easily read as a decline. The year and the date
    are read in UTC from the recorded retrieval time, as the search record
    reads it. The clock of the session drawing the figure is never read, since
    it says nothing about when the counts were taken. ``None`` when nothing
    records the time or no plotted year reaches it. The R twin words the note
    identically.
    """
    stamp = as_datetime(retrieved_at)
    if stamp is None:
        return None
    utc = _utc(stamp)
    late = sorted({int(y) for y in years if not pd.isna(y) and int(y) >= utc.year})
    if not late:
        return None
    day = utc.strftime("%Y-%m-%d")
    if len(late) == 1:
        return f"{late[0]} was incomplete when retrieved on {day}."
    return f"{late[0]} and later years were incomplete when retrieved on {day}."


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
    Scopus field tag (see [`FIELD_TAGS`][scopusflow.query.FIELD_TAGS]), the way
    [`scopus_count`][scopusflow.count.scopus_count] and the R twin's
    ``scopus_trend()`` do; left ``None``, the query is sent as given.

    Returns a [`TREND_COLUMNS`][scopusflow.trend.TREND_COLUMNS] frame, one row
    per year, sorted by year. ``view`` and any further keyword argument go to
    pybliometrics' ``ScopusSearch``.

    Each count is sent with ``refresh=True`` unless you pass ``refresh``.
    pybliometrics keys its own response cache on the query string and view
    alone. Without ``refresh=True``, it could answer a year with the number of
    rows an earlier harvest of the same query left there. ``refresh=False``,
    or a number of days, opts in to that cache, and a year it answers is
    warned about. The key ignores keyword filters such as ``subj``, so fold any
    filter into the query before you opt in.

    The result records when the counts were taken, in ``attrs["retrieved_at"]``
    as ISO 8601 text in UTC, as a harvest records its own. Scopus goes on
    indexing a year's publications after the year has begun, so a count for
    the year of retrieval is a count so far, and
    [`plot_trend`][scopusflow.plots.plot_trend] says so from this time. A count
    answered from pybliometrics' cache is dated by its cache file, and the
    earliest time is kept. When a cached count's file time cannot be read, the
    attribute is left out, since a trend dated by its other counts would be
    dated later than that one.

    Raises [`ScopusFlowConfigError`][scopusflow.exceptions.ScopusFlowConfigError]
    before any request when ``pybliometrics.init()`` has not been called in the
    session.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
    # Checked offline first (see scopusflow.plan.SearchPlan), so a query the
    # API cannot run as written costs no request.
    _check_query(query, field)
    years = list(years)
    if not years:
        raise ValueError("years must be a non-empty sequence.")
    # Validated before it reaches the query, so a whole-number float such as
    # 2015.0 is sent as PUBYEAR IS 2015, the year its count is filed under.
    years = _check_years(years)
    # Wrapped once, before the loop: the tag applies to the query alone, never
    # to the year
    # filter folded in beside it.
    query = wrap_field(query, field)
    kwargs.setdefault("refresh", True)
    require_init()

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    counts: dict[int, int] = {}
    cached: list = []
    for y in years:
        # Bracketed first when a top-level OR or AND NOT would otherwise take
        # the year filter from part of the query.
        year_query = _and_clause(query, f"PUBYEAR IS {y}")
        t0 = time.time()
        search = ScopusSearch(year_query, view=view, download=False, **kwargs)
        counts[y], written = result_size_and_time(
            search, t0, kwargs["refresh"], year_query, stacklevel=2
        )
        if written is not None:
            cached.append(written)
    out = _trend_frame(counts)
    # Dated as fetch_plan() dates its cells: a count the API gave by the time
    # the counting finished, a count from pybliometrics' cache by its file,
    # and the earliest kept, so the trend never claims fresher counts than
    # it holds.
    if UNDATED not in cached:
        out.attrs["retrieved_at"] = iso_utc(min([datetime.now(timezone.utc), *cached]))
    return out
