"""Reproducible search plans: describe a search before running it."""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass

from .query import _FIELD_RE, _check_query, wrap_field

#: One message for every rejection, so the failure reads the same wherever a
#: year is supplied.
_YEARS_MESSAGE = "years must be whole numbers between 1700 and 2200."

_FIELD_MESSAGE = "field must be None or a Scopus field tag such as 'TITLE-ABS-KEY'."


def _check_field(field):
    """Normalise a field tag as the R twin's ``scopus_check_field()`` does:
    ``None`` passes through, and a string is stripped, upper-cased and held to
    letters and hyphens. Anything else raises ``ValueError``."""
    if field is None:
        return None
    if not isinstance(field, str):
        raise ValueError(_FIELD_MESSAGE)
    tag = field.strip().upper()
    if not _FIELD_RE.match(tag):
        raise ValueError(_FIELD_MESSAGE)
    return tag

#: The Scopus Search API page-size ceiling, which depends on the view: 200
#: records per request for STANDARD, 25 for COMPLETE. These are the counts
#: pybliometrics itself sends for each view, so a plan that leaves ``page_size``
#: unset describes exactly what the harvest will do.
_VIEW_MAX = {"STANDARD": 200, "COMPLETE": 25}


def _check_page_size(page_size, view: str) -> int:
    """Resolve and validate a page size against the view's ceiling.

    ``None`` means "the largest page the view allows", which is the most
    quota-efficient choice and what pybliometrics requests by default: Scopus
    charges quota by the request, whatever it brings back, so a thousand
    records cost five
    requests in pages of 200 and forty in pages of 25.
    """
    max_size = _VIEW_MAX[view]
    if page_size is None:
        return max_size
    if isinstance(page_size, bool) or not isinstance(page_size, numbers.Real):
        raise ValueError("page_size must be a whole number or None.")
    value = float(page_size)
    if not math.isfinite(value) or value != int(value):
        raise ValueError("page_size must be a whole number or None.")
    if not 1 <= value <= max_size:
        raise ValueError(
            f"page_size must be between 1 and {max_size} for the {view} view "
            "(the Scopus Search API page limit)."
        )
    return int(value)


def _check_years(years):
    """Validate and normalise a year sequence, returning a list of ``int``.

    Every entry point that takes years routes through this, the way the R
    twin's ``scopus_check_years()`` does, so the two engines accept and refuse
    the same inputs. Without it each caller coerced with a bare ``int()``,
    which truncates 2015.7 to 2015, or interpolated the value into the query
    untouched, which sends the API ``PUBYEAR IS 2015.0``. ``None`` passes
    through, meaning no year constraint.
    """
    if years is None:
        return None
    checked: list[int] = []
    for y in years:
        # bool is a subclass of int, and True is not a year.
        if isinstance(y, bool) or not isinstance(y, numbers.Real):
            raise ValueError(_YEARS_MESSAGE)
        value = float(y)
        if not math.isfinite(value) or value != int(value) or not 1700 <= value <= 2200:
            raise ValueError(_YEARS_MESSAGE)
        checked.append(int(value))
    return checked


@dataclass(frozen=True)
class PlanCell:
    """One unit of work in a :class:`SearchPlan`."""

    cell: int
    query: str
    date: str | None
    year: int | None
    view: str
    page_size: int = 200


@dataclass(frozen=True)
class SearchPlan:
    """A fully specified, inspectable description of a Scopus search.

    Splitting *describing* a search from *executing* it makes a workflow
    reproducible and lets a large retrieval be partitioned by year, so it can be
    cached and resumed.

    ``page_size`` is the number of records asked for per request, ``None``
    (the default) meaning the largest the view allows: 200 for ``STANDARD``,
    25 for ``COMPLETE``. It is stored on the plan, and sent, because the search
    record :func:`scopusflow.report.scopus_search_report` writes has to state
    how the harvest was paged, and a figure taken from anywhere but the plan
    would be a guess.

    ``field`` is stripped and upper-cased when the plan is built, and a value
    that is not a string of letters and hyphens raises ``ValueError``. The
    query is checked offline at the same time: LIMIT-TO() or EXCLUDE() pasted
    from the web interface's refinement panel, a field tag around a query that
    already opens with one, and unbalanced brackets, quotation marks or braces
    raise ``ValueError``, and INDEXTERMS() issues a
    :class:`scopusflow.query.QuerySyntaxWarning`.
    """

    query: str
    years: Sequence[int] | None = None
    field: str | None = None
    view: str = "STANDARD"
    partition: str = "none"  # "none" or "year"
    page_size: int | None = None

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("query must be a non-empty string.")
        # Normalised here, as the R twin's scopus_plan() normalises it. Stored
        # as passed, " title-abs-key " sent the same query as "TITLE-ABS-KEY"
        # but compared unequal, and the search record printed it raw.
        object.__setattr__(self, "field", _check_field(self.field))
        # Offline checks, so a query the API cannot run as written is refused
        # before fetch_plan() spends a request on it. stacklevel 4 reaches the
        # caller of SearchPlan() through __init__ and __post_init__.
        _check_query(self.query, self.field, stacklevel=4)
        if self.view not in {"STANDARD", "COMPLETE"}:
            raise ValueError("view must be 'STANDARD' or 'COMPLETE'.")
        if self.partition not in {"none", "year"}:
            raise ValueError("partition must be 'none' or 'year'.")
        object.__setattr__(self, "page_size",
                           _check_page_size(self.page_size, self.view))
        # Store the validated integers, never the values as passed: cells() renders the
        # year into the cell's date, and str(2015.0) would reach the API as
        # "2015.0". A tuple, since a list would leave the frozen dataclass unhashable.
        # object.__setattr__ is how a frozen dataclass normalises a field.
        #
        # Sorted and de-duplicated, as every other caller of _check_years already
        # does with its result and as cells() does with this one, so that the
        # stored years say what the search will actually do. Without it two plans
        # describing the same search compared unequal on the order the years
        # happened to be typed in, and the reproduction snippet
        # scopus_search_report() emits (which renders them canonically) rebuilt a
        # plan that ran identically but failed an equality check against its own
        # original.
        checked = _check_years(self.years)
        object.__setattr__(self, "years",
                           None if checked is None else tuple(sorted(set(checked))))
        if self.partition == "year" and not self.years:
            raise ValueError("partition='year' requires years.")

    @property
    def wrapped_query(self) -> str:
        return wrap_field(self.query, self.field)

    def cells(self) -> list[PlanCell]:
        """Expand the plan into the cells that will be fetched."""
        q = self.wrapped_query
        size = int(self.page_size)  # type: ignore[arg-type]
        if self.partition == "year":
            years = sorted(set(self.years))  # type: ignore[arg-type]
            return [
                PlanCell(i + 1, q, str(y), y, self.view, size)
                for i, y in enumerate(years)
            ]
        date = None
        if self.years:
            lo, hi = min(self.years), max(self.years)
            date = str(lo) if lo == hi else f"{lo}-{hi}"
        return [PlanCell(1, q, date, None, self.view, size)]
