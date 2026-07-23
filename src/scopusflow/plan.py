"""Reproducible search plans: describe a search before running it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .query import wrap_field


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
