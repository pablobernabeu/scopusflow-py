"""Reproducible search plans: describe a search before running it."""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass

from .query import wrap_field

#: One message for every rejection, so the failure reads the same wherever a
#: year is supplied.
_YEARS_MESSAGE = "years must be whole numbers between 1700 and 2200."


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


@dataclass(frozen=True)
class SearchPlan:
    """A fully specified, inspectable description of a Scopus search.

    Splitting *describing* a search from *executing* it makes a workflow
    reproducible and lets a large retrieval be partitioned by year, so it can be
    cached and resumed.
    """

    query: str
    years: Sequence[int] | None = None
    field: str | None = None
    view: str = "STANDARD"
    partition: str = "none"  # "none" or "year"

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("query must be a non-empty string.")
        if self.view not in {"STANDARD", "COMPLETE"}:
            raise ValueError("view must be 'STANDARD' or 'COMPLETE'.")
        if self.partition not in {"none", "year"}:
            raise ValueError("partition must be 'none' or 'year'.")
        # Store the validated integers, not what was passed: cells() renders the
        # year into the cell's date, and str(2015.0) would reach the API as
        # "2015.0". A tuple, not a list, so the frozen dataclass stays hashable.
        # object.__setattr__ is how a frozen dataclass normalises a field.
        checked = _check_years(self.years)
        object.__setattr__(self, "years", None if checked is None else tuple(checked))
        if self.partition == "year" and not self.years:
            raise ValueError("partition='year' requires years.")

    @property
    def wrapped_query(self) -> str:
        return wrap_field(self.query, self.field)

    def cells(self) -> list[PlanCell]:
        """Expand the plan into the cells that will be fetched."""
        q = self.wrapped_query
        if self.partition == "year":
            years = sorted(set(self.years))  # type: ignore[arg-type]
            return [
                PlanCell(i + 1, q, str(y), y, self.view) for i, y in enumerate(years)
            ]
        date = None
        if self.years:
            lo, hi = min(self.years), max(self.years)
            date = str(lo) if lo == hi else f"{lo}-{hi}"
        return [PlanCell(1, q, date, None, self.view)]
