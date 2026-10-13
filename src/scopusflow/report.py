"""A reproducible search-strategy record, rendered for a methods section.

The one rule this module exists to keep: nothing here may be inferred from the
running session. No ``datetime.now()`` stands in for an absent retrieval stamp,
no total is guessed from the row count, no duplicate count is reported unless a
merge recorded one, and no PRISMA-S item is claimed without evidence in the
object. The output is destined for a published methods section, where a
plausible figure nobody can check is worse than an admitted gap, so every field
the objects cannot vouch for says so in words.

The rendering is held byte for byte against the R twin's, so a search written up
in one language reads identically in the other. Only the reproduction snippet
differs, being code in the host language.
"""

from __future__ import annotations

import json
import math
import numbers
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone

import pandas as pd

from ._provenance import as_datetime, as_plan, cell_totals_frame
from .plan import SearchPlan

__all__ = ["SearchReport", "scopus_search_report"]

#: The 16 PRISMA-S items, in the order and under the names the checklist gives
#: them (Rethlefsen et al., 2021). Which side of the map an item falls on is
#: decided per report from the evidence, so this list holds only the names.
PRISMA_S_ITEMS = [
    "Database name", "Multi-database searching", "Study registries",
    "Online resources and browsing", "Citation searching", "Contacts",
    "Other methods", "Full search strategies", "Limits and restrictions",
    "Search filters", "Prior work", "Updates", "Dates of searches",
    "Peer review", "Total records", "Deduplication",
]

# English month names, spelled out here and never read from the locale: the
# paragraph is compared byte for byte against the R twin's, and a locale-aware
# month name would make that comparison depend on the machine.
_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

_REFERENCE = (
    "The reporting standard is PRISMA-S (Rethlefsen et al., 2021, Systematic "
    "Reviews, 10, 39, https://doi.org/10.1186/s13643-020-01542-z), with the "
    "identification counts of the PRISMA 2020 flow diagram."
)

_NOT_RUN = "unrecorded, this plan has not been run"


def _count(n) -> str:
    """A whole number, thousands grouped, as both engines render it."""
    return f"{int(n):,}"


def _utc(t: datetime) -> datetime:
    """``t`` in UTC. A naive time is read as local time, as everywhere the
    record renders one."""
    return t.astimezone(timezone.utc)


def _stamp(t: datetime) -> str:
    """An instant, always shown in UTC. A retrieval stamp is an absolute time,
    and a methods section that says when a search ran should not depend on the
    reader's machine to interpret it."""
    return _utc(t).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _date(t: datetime) -> str:
    utc = _utc(t)
    return f"{utc.day} {_MONTHS[utc.month - 1]} {utc.year}"


def _spans_days(x: SearchReport) -> bool:
    """Whether the earliest and latest retrieval times fall on different UTC
    days. Only then is the search dated as a span. Stamps a few hours apart on
    one day give that day, as a single stamp always has, so the record of a
    one-day harvest, compared byte for byte with the R twin's, is unchanged."""
    if x.searched_at is None or x.searched_until is None:
        return False
    return _utc(x.searched_at).date() != _utc(x.searched_until).date()


@dataclass(eq=False)
class SearchReport:
    """The fields a search record is built from, and its three renderings.

    Every attribute is either what the objects recorded or ``None``, which the
    renderings spell out as unrecorded. ``cells`` is a frame of ``cell``,
    ``limit``, ``n_records`` and ``reported_total``; ``prisma`` a frame of
    ``item``, ``name``, ``source`` (``"record"`` or ``"author"``) and ``note``.
    ``searched_at`` and ``searched_until`` are the earliest and latest
    retrieval times. ``max_results`` is the cap on records per cell a set
    records. ``stopped_early``, ``cells_planned`` and ``cells_run`` describe a
    harvest stopped before its last cell, ``not_run`` lists the cells it never
    reached and ``years_run`` the years of those it ran.
    """

    database: str = "Scopus"
    platform: str = "Elsevier Scopus Search API"
    query: str | None = None
    field: str | None = None
    expression: list[str] | None = None
    view: str | None = None
    page_size: int | None = None
    paging: str | None = None
    max_results: int | None = None
    partition: str | None = None
    n_cells: int | None = None
    years: str | None = None
    years_run: str | None = None
    cells: pd.DataFrame = dataclass_field(default_factory=pd.DataFrame)
    searched_at: datetime | None = None
    searched_until: datetime | None = None
    version: str | None = None
    n_records: int | None = None
    n_with_doi: int | None = None
    reported_total: int | None = None
    cells_reported: int = 0
    stopped_early: bool = False
    cells_planned: int | None = None
    cells_run: int | None = None
    not_run: list[int] = dataclass_field(default_factory=list)
    records_combined: int | None = None
    duplicates_removed: int | None = None
    deduplicated: bool | None = None
    snippet: str | None = None
    prisma: pd.DataFrame = dataclass_field(default_factory=pd.DataFrame)

    def format(self, style: str = "report") -> str:
        """Render the record: ``"report"`` for the readable record ``print``
        shows, ``"paragraph"`` for the methods paragraph, or ``"markdown"`` for
        the whole record as Markdown, which is what ``file`` writes."""
        if style == "report":
            return _render_report(self)
        if style == "paragraph":
            return _render_paragraph(self)
        if style == "markdown":
            return _render_markdown(self)
        raise ValueError("style must be 'report', 'paragraph' or 'markdown'.")

    def __str__(self) -> str:
        return _render_report(self)

    __repr__ = __str__


def scopus_search_report(x, plan: SearchPlan | None = None, file=None) -> SearchReport:
    """Assemble a reproducible record of a Scopus search.

    Turns a harvest, or a plan not yet run, into the search-strategy record a
    systematic review has to report: what was searched, exactly how, when, how
    much came back, and how much the API said there was. The record prints as a
    readable report, formats as a methods paragraph fit to paste into a
    manuscript, and writes as Markdown. The reporting standard it follows is
    PRISMA-S (Rethlefsen et al., 2021), together with the identification counts
    of the PRISMA 2020 flow diagram.

    Everything in the record comes from the objects handed to it. The dates of
    the search are the ``retrieved_at`` and ``retrieved_until`` attributes
    :func:`scopusflow.fetch.fetch_plan` attaches, never the current time. A
    harvest resumed over several days, or a baseline merged with its update,
    is dated from its first retrieval to its last. PRISMA-S item 13 then gives
    the date of the last search, as the checklist asks. Stamps that fall on
    one UTC day give that single date. The years are those the cells'
    limits sent, and years with gaps between them are listed, since a span
    would claim years no cell searched. The number of records the API reported
    as matching is the per-cell accounting in ``cell_totals``, or, for a set
    from a single search, its ``total_results``, never an inference from the
    number of rows; and the duplicates removed are those
    :func:`scopusflow.combine.scopus_combine` recorded removing. Where an
    attribute is absent, as it is for a frame read back from CSV, for the
    bundled corpus, and for a harvest with a cell resumed from a checkpoint
    written without a manifest by an earlier version of scopusflow, the record
    says the field is unrecorded and fills nothing in. This matters
    most for completeness: a harvest whose reported total is unknown is never
    described as exhaustive.

    A harvest stopped through ``should_stop``, as the app's Cancel stops one,
    says so. The record gives how many of the planned cells ran and which
    years they covered, marks the rest "not run" and calls the harvest
    incomplete, keeping the totals the cells that ran recorded. The R twin's
    ``scopus_fetch_plan()`` can also cap the records per cell, and its record
    then names the cap in the cells it stopped, the completeness line and
    item 9. A frame carrying ``attrs["max_results"]`` is described the same
    way here, so the two records stay one rendering, although
    :func:`~scopusflow.fetch.fetch_plan` takes no cap and so never records one.

    The PRISMA-S map is decided the same way. Items the package holds evidence
    for (the database and platform, that Scopus was searched on its own, the
    full strategy and the limits where a plan records them, the date, the
    totals, and de-duplication where it was performed) are listed as supplied.
    Without a plan, the year limit is unrecorded, not absent, and the record
    says so. The rest, among them peer review of the strategy, grey literature
    and citation searching, are listed as the author's to supply, because the
    package has no way to know them.

    Parameters
    ----------
    x:
        A records frame, which supplies the counts and the retrieval provenance
        and, through ``attrs["plan"]``, the plan; or a bare
        :class:`~scopusflow.plan.SearchPlan` for a search not yet run. The
        attributes are read in the JSON-safe forms
        :func:`~scopusflow.fetch.fetch_plan` writes (the plan as a dict, the
        time as ISO 8601 text, the cell totals as a list of dicts) and in the
        richer forms a guide may set by hand (a ``SearchPlan``, a
        ``datetime``, a DataFrame).
    plan:
        The plan describing ``x``. Supply it when a records frame does not carry
        one, for instance one read back from CSV or a merged set. An explicit
        plan takes precedence over the one ``x`` carries. A one-cell plan
        supplied for a frame without per-cell counts takes the frame's own row
        count and ``total_results``.
    file:
        Path at which to write the record as Markdown. A file is written only
        when this is supplied, and only to the exact path given, so nothing is
        written to the working directory unless asked.

    Returns
    -------
    SearchReport
        The record. ``print`` shows it, ``report.format(style="paragraph")``
        gives the methods paragraph.

    References
    ----------
    Rethlefsen, M. L., Kirtley, S., Waffenschmidt, S., Ayala, A. P., Moher, D.,
    Page, M. J., & Koffel, J. B. (2021). PRISMA-S: an extension to the PRISMA
    Statement for Reporting Literature Searches in Systematic Reviews.
    *Systematic Reviews*, *10*, 39. https://doi.org/10.1186/s13643-020-01542-z

    Examples
    --------
    A search described but not yet run. The record says so throughout rather
    than implying figures it cannot have.

    >>> import scopusflow as sf
    >>> plan = sf.SearchPlan('"graphene supercapacitor"', years=range(2015, 2025),
    ...                      field="TITLE-ABS-KEY", partition="year")
    >>> report = sf.scopus_search_report(plan)
    >>> report.n_records is None
    True

    The same search after a harvest. The bundled corpus stands in for one, since
    Scopus records may not be redistributed, so the attributes a live retrieval
    records are set here by hand. Their values are illustrative, and the records
    came from OpenAlex, so the record below describes no search that was run.

    >>> from datetime import datetime, timezone
    >>> records = sf.example_records()
    >>> records.attrs["plan"] = plan
    >>> records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15,
    ...                                          tzinfo=timezone.utc)
    >>> records.attrs["scopusflow_version"] = "0.3.0"
    >>> report = sf.scopus_search_report(records)
    >>> report.n_records
    138
    >>> "22 July 2026" in report.format(style="paragraph")
    True
    """
    if plan is not None and not isinstance(plan, SearchPlan):
        raise ValueError("The plan must be a search plan.")
    if isinstance(x, SearchPlan):
        records = None
        plan = plan or x
    elif isinstance(x, pd.DataFrame):
        records = x
        if plan is None:
            plan = as_plan(x.attrs.get("plan"))
    else:
        raise ValueError("A search report needs a record set or a search plan.")

    report = _build(records, plan)

    if file is not None:
        if not isinstance(file, (str, bytes)) and not hasattr(file, "__fspath__"):
            raise ValueError("The file must be a single non-empty path.")
        if isinstance(file, (str, bytes)) and not str(file).strip():
            raise ValueError("The file must be a single non-empty path.")
        # Newline fixed to LF, so the record is byte-identical on every platform
        # and against the R twin, which writes its text artefacts the same way.
        with open(file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_render_markdown(report) + "\n")
    return report


# Field extraction ----------------------------------------------------------


def _build(records, plan) -> SearchReport:
    stoppage = _stop(records, plan)
    cells = _cells(records, plan, joined=stoppage.joined)
    reported = cells["reported_total"]
    n_reported = int(reported.notna().sum())
    total = int(reported.sum()) if len(cells) and n_reported == len(cells) else None

    combined = records.attrs.get("combined") if records is not None else None
    stamp = as_datetime(records.attrs.get("retrieved_at")) if records is not None else None
    # The last search, read only beside a first one. A set written before
    # retrieved_until existed has the one stamp, and a latest time recorded
    # before the earliest cannot widen the span backwards.
    until = None
    if stamp is not None:
        latest = as_datetime(records.attrs.get("retrieved_until"))
        until = stamp if latest is None or _utc(latest) < _utc(stamp) else latest
    version = records.attrs.get("scopusflow_version") if records is not None else None
    if isinstance(version, (list, tuple)):
        version = ", ".join(str(v) for v in version)

    paging = records.attrs.get("paging") if records is not None else None
    # The years of the cells a stopped harvest ran, read from their limits as
    # the years of the plan are.
    years_run = (_years(cells.loc[[c not in stoppage.not_run for c in cells["cell"]]])
                 if stoppage.joined else None)
    report = SearchReport(
        query=plan.query if plan is not None else None,
        field=plan.field if plan is not None else None,
        expression=_expression(records, plan),
        view=plan.view if plan is not None else None,
        page_size=int(plan.page_size) if plan is not None else None,
        paging=paging,
        max_results=_cap(records),
        partition=plan.partition if plan is not None else None,
        n_cells=len(plan.cells()) if plan is not None else None,
        years=_years(cells),
        years_run=years_run,
        cells=cells,
        searched_at=stamp,
        searched_until=until,
        version=str(version) if version is not None else None,
        n_records=len(records) if records is not None else None,
        n_with_doi=int(records["doi"].notna().sum()) if records is not None else None,
        reported_total=total,
        cells_reported=n_reported,
        stopped_early=stoppage.stopped,
        cells_planned=stoppage.cells_planned,
        cells_run=stoppage.cells_run,
        not_run=stoppage.not_run,
        records_combined=_combined(combined, "n_in"),
        duplicates_removed=_combined(combined, "n_removed"),
        deduplicated=bool(combined["deduplicated"]) if combined else None,
        snippet=_snippet(plan, paging),
    )
    report.prisma = _prisma(report)
    return report


@dataclass(frozen=True)
class _Stoppage:
    """What the records say about a harvest stopped before its last cell."""

    stopped: bool = False
    cells_planned: int | None = None
    cells_run: int | None = None
    joined: bool = False
    not_run: list[int] = dataclass_field(default_factory=list)


def _stop(records, plan) -> _Stoppage:
    """Read the stop :func:`~scopusflow.fetch.fetch_plan` records.

    A harvest ended by ``should_stop``, as the app's Cancel ends one, records
    ``stopped_early``, ``cells_planned`` and ``cells_run``. The recorded cells
    are placed on the plan's cells only when the plan is the one the harvest
    ran. It must hold as many cells as were planned, the recorded ones among
    them. A plan passed by hand that does not leaves the cells unrecorded, as
    before, while the set still says that it was stopped. The R twin cannot
    stop a harvest part-way, but its record reads the same attributes the same
    way.
    """
    if records is None or records.attrs.get("stopped_early") is not True:
        return _Stoppage()
    counts = cell_totals_frame(records.attrs.get("cell_totals"))
    # A missing cell number matches no cell of the plan, so it prevents the
    # join, as it does in the R twin.
    recorded = (None if counts is None else
                [None if pd.isna(c) else int(c) for c in counts["cell"]])
    run = _whole(records.attrs.get("cells_run"))
    if run is None and recorded is not None:
        run = len(recorded)
    planned = _whole(records.attrs.get("cells_planned"))
    if planned is None and plan is not None:
        planned = len(plan.cells())
    if run is None or planned is None:
        return _Stoppage()
    plan_cells = [c.cell for c in plan.cells()] if plan is not None else []
    joined = (plan is not None and recorded is not None and len(plan_cells) == planned
              and len(set(recorded)) == len(recorded) and set(recorded) <= set(plan_cells))
    not_run = [c for c in plan_cells if c not in recorded] if joined else []
    return _Stoppage(True, planned, run, joined, not_run)


def _whole(value) -> int | None:
    """Turn a count recorded as an attribute into an int, giving ``None`` for
    anything but one whole number."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    if not math.isfinite(value) or value < 0 or value != int(value):
        return None
    return int(value)


def _cap(records) -> int | None:
    """The cap on records per cell a set was retrieved under, or ``None``.

    The R twin's ``scopus_fetch()`` and ``scopus_fetch_plan()`` record it as
    ``max_results`` when one was set. :func:`~scopusflow.fetch.fetch_plan`
    takes no cap, so only a frame given the attribute by hand carries one
    here. A plan not yet run has none to report.
    """
    cap = records.attrs.get("max_results") if records is not None else None
    if isinstance(cap, bool) or not isinstance(cap, numbers.Real):
        return None
    if not math.isfinite(cap) or cap < 1 or cap != int(cap):
        return None
    return int(cap)


def _known(value):
    """A cell's count, or ``None`` where it is missing."""
    return None if value is None or pd.isna(value) else value


def _capped(cells: pd.DataFrame, cap: int | None) -> list[bool]:
    """Which cells stopped at the cap: those holding as many records as it
    allowed, where the API reported more or reported nothing. A cell holding
    all the records the API reported is complete, whatever the cap."""
    flags = []
    for n, reported in zip(cells["n_records"], cells["reported_total"], strict=True):
        n, reported = _known(n), _known(reported)
        flags.append(cap is not None and n is not None and n >= cap
                     and (reported is None or reported > n))
    return flags


def _cells(records, plan, joined: bool = False) -> pd.DataFrame:
    """The per-cell table.

    A plan supplies the cells and their year limits; the counts come from the
    ``cell_totals`` attribute ``fetch_plan`` records, and stay missing when the
    frame never carried one (a CSV round trip, the bundled corpus, a frame
    assembled by hand). A frame from a single search carries no cell counts,
    only its own total, so a plan with one cell, which stands for that search,
    takes the frame's figures, as in the R twin. A harvest stopped part-way
    recorded only the cells it ran. When ``joined`` says the plan is the one it
    ran (see :func:`_stop`), those cells take their counts and the rest stay
    missing, to be read as not run. Without a plan the whole retrieval is
    treated as one cell, so the rest of the module has a single shape to
    render.
    """
    counts = cell_totals_frame(records.attrs.get("cell_totals")) if records is not None else None
    if plan is not None:
        planned = plan.cells()
        out = pd.DataFrame({
            "cell": [c.cell for c in planned],
            "limit": [c.date for c in planned],
            "n_records": [None] * len(planned),
            "reported_total": [None] * len(planned),
        })
        if (isinstance(counts, pd.DataFrame) and len(counts) == len(out)
                and list(counts["cell"]) == list(out["cell"])):
            out["n_records"] = list(counts["n_records"])
            out["reported_total"] = list(counts["reported_total"])
        elif joined:
            position = {cell: i for i, cell in enumerate(out["cell"])}
            n_records = list(out["n_records"])
            reported = list(out["reported_total"])
            for row in counts.itertuples(index=False):
                i = position[int(row.cell)]
                n_records[i] = row.n_records
                reported[i] = row.reported_total
            out["n_records"] = n_records
            out["reported_total"] = reported
        elif len(out) == 1 and records is not None:
            out["n_records"] = [len(records)]
            out["reported_total"] = [records.attrs.get("total_results")]
        return out
    if records is not None:
        total = records.attrs.get("total_results")
        return pd.DataFrame({
            "cell": [1], "limit": [None], "n_records": [len(records)],
            "reported_total": [total],
        })
    return pd.DataFrame(columns=["cell", "limit", "n_records", "reported_total"])


def _expression(records, plan) -> list[str] | None:
    """The field-wrapped query of each cell. The plan holds it; failing that the
    records' own ``query`` column does, which is what a frame fetched without a
    plan carries."""
    if plan is not None:
        values = [c.query for c in plan.cells()]
    elif records is not None and "query" in records.columns:
        values = list(records["query"].dropna())
    else:
        return None
    seen: list[str] = []
    for v in values:
        if v is not None and str(v) not in seen:
            seen.append(str(v))
    return seen or None


def _years(cells: pd.DataFrame) -> str | None:
    """The years actually searched, read back from the cells' date limits rather
    than from any year sequence, because the limit is what reached the API. A
    range limit such as ``"2015-2025"`` covers every year in it, since the API
    takes the range inclusively, and a single-year limit covers that year."""
    limits = [str(v) for v in cells["limit"] if v is not None and not pd.isna(v)]
    covered: set[int] = set()
    for limit in limits:
        found = [int(m) for m in _digits(limit)]
        if found:
            covered.update(range(min(found), max(found) + 1))
    if not covered:
        return None
    return _year_list(sorted(covered))


def _year_list(years: list[int]) -> str:
    """Sorted years as a methods section states them.

    One unbroken run reads as a span, "2015 to 2024". Years with gaps between
    them are listed, "2015, 2020 and 2025", because a span over the gaps would
    claim years no cell searched. Within such a list, a run of three or more
    years is still written as a span, so that a decade is not spelled out year
    by year. A run of two is listed, since a span saves no words there. The R
    twin renders the same years identically.
    """
    runs = [[years[0]]]
    for year in years[1:]:
        if year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    if len(runs) == 1:
        run = runs[0]
        return str(run[0]) if len(run) == 1 else f"{run[0]} to {run[-1]}"
    parts: list[str] = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{run[0]} to {run[-1]}")
        else:
            parts.extend(str(year) for year in run)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _digits(text: str) -> list[str]:
    out, run = [], ""
    for ch in text:
        if ch.isdigit():
            run += ch
        else:
            if len(run) == 4:
                out.append(run)
            run = ""
    if len(run) == 4:
        out.append(run)
    return out


def _combined(combined, key: str) -> int | None:
    if not combined or combined.get(key) is None:
        return None
    return int(combined[key])


def _snippet(plan, paging=None) -> str | None:
    """The runnable reproduction.

    Built from what the plan records, so that running it returns a plan equal to
    the one the report describes; the test suite asserts exactly that over a
    grid of plans. Without a plan there is nothing to reproduce. The paging
    mode is settled by the fetch, not the plan, and ``fetch_plan()`` pages by
    cursor unless told otherwise, so a harvest the records say was paged by
    offset is reproduced with ``cursor=False``. ``fetch_plan()`` takes no cap
    on records per cell, so a cap recorded on the frame, which the R twin's
    snippet passes, is left out here, where it would not run.
    """
    if plan is None:
        return None
    # Imported inside the function, and never at module scope: app_helpers
    # reads the package version at import time, and this module is imported
    # while the package's own __init__ is still executing.
    from .app_helpers import app_years_code

    args = [f"    query={json.dumps(plan.query)},"]
    years = app_years_code(plan.years)
    if years:
        args.append(f"    years={years},")
    if plan.field:
        args.append(f"    field={json.dumps(plan.field)},")
    args += [
        f"    view={json.dumps(plan.view)},",
        f"    page_size={int(plan.page_size)},",
        f"    partition={json.dumps(plan.partition)},",
    ]
    body = "\n".join(args)
    fetch = ("records = sf.fetch_plan(plan, cursor=False)" if paging == "offset"
             else "records = sf.fetch_plan(plan)")
    return (
        "import scopusflow as sf\n"
        "\n"
        f"plan = sf.SearchPlan(\n{body}\n)\n"
        "\n"
        f"{fetch}"
    )


def _prisma(x: SearchReport) -> pd.DataFrame:
    """The PRISMA-S map.

    An item is listed as supplied only where the objects hold the evidence for
    it; everything else, including items the package could in principle support
    but has no record of here, is the author's.
    """
    notes = [""] * 16
    supplied: set[int] = set()

    notes[0] = f"{x.database}, searched on the {x.platform}."
    supplied.add(1)

    # Item 2 asks which databases were searched together on one platform, as
    # Ovid searches several at once. The API searches Scopus alone, which the
    # record can state, as it states the platform for item 1. Any other
    # database a review searched is named under item 1, by the author. A plan
    # not yet run is described in the present, as the paragraph describes it.
    notes[1] = (f"Scopus {'was' if _was_run(x) else 'is'} searched on its own, not "
                "as one of several databases searched together on one platform.")
    supplied.add(2)
    notes[2] = "Any trial or study registry searched."
    notes[3] = ("Any web site, table of contents or other source searched or "
                "browsed by hand.")
    notes[4] = "Any backward or forward citation searching."
    notes[5] = "Any authors or organisations contacted for studies."
    notes[6] = "Any further method used to identify records."

    # Without a plan, the expression is the one the records carry, and nothing
    # records the field tag and year limit it was sent with, so the full
    # strategy is not here.
    if not x.expression:
        notes[7] = "The exact strategy, which this set does not record."
    elif x.partition is None:
        notes[7] = ("The search expression is recorded, but no plan records the "
                    "limits it was sent with.")
    else:
        notes[7] = ("The search expression, field tag and year limit of every "
                    "cell, as the plan sends them.")
        supplied.add(8)

    if x.partition is not None:
        # A cap and a stop are limits on what was retrieved, so each is named
        # between the year limit and the limits scopusflow never applies.
        own = ("scopusflow applies no document type, language or subject area "
               "limit of its own.")
        clause = _stop_clause(x)
        extra = [s for s in (_cap_sentence(x), clause and clause + ".") if s]
        if x.years is not None:
            notes[8] = " ".join([f"Publication years {x.years}.", *extra, own])
        elif extra:
            notes[8] = " ".join(["No year limit was applied.", *extra, own])
        else:
            notes[8] = ("No year limit was applied, and scopusflow applies no "
                        "document type, language or subject area limit of its own.")
        supplied.add(9)
    else:
        notes[8] = "Any limit applied to the search, which this set does not record."

    notes[9] = ("Any published or validated search filter used, and where it came "
                "from. scopusflow applies none of its own.")
    notes[10] = "Any earlier review or strategy this search was adapted from."
    notes[11] = "Whether the search was re-run or updated, and when."

    # PRISMA-S item 13 asks for the date of the last search. Records, not
    # cells, in the span, since a merged set mixes searches.
    if _spans_days(x):
        notes[12] = (f"Last searched on {_stamp(x.searched_until)}; the records were "
                     f"retrieved between {_stamp(x.searched_at)} and "
                     f"{_stamp(x.searched_until)}.")
        supplied.add(13)
    elif x.searched_at is not None:
        notes[12] = f"{_stamp(x.searched_at)}."
        supplied.add(13)
    elif x.n_records is None:
        notes[12] = ("The date of each search, which this plan has not been run "
                     "to produce.")
    else:
        notes[12] = "The date of each search, which this set does not carry."

    notes[13] = "Whether the strategy was peer reviewed, and by whom."

    if x.n_records is not None:
        if x.stopped_early:
            notes[14] = (f"{_count(x.n_records)} records retrieved from Scopus "
                         f"before {_stop_phrase(x)}.")
        elif x.reported_total is None:
            notes[14] = (f"{_count(x.n_records)} records retrieved from Scopus. The "
                         "API's own count of matching records is unrecorded.")
        else:
            notes[14] = (f"{_count(x.n_records)} records retrieved from Scopus, of "
                         f"{_count(x.reported_total)} the API reported as matching.")
        supplied.add(15)
    else:
        notes[14] = ("The number of records identified, which this plan has not "
                     "been run to produce.")

    if x.deduplicated and x.duplicates_removed is not None:
        notes[15] = (
            f"{_count(x.duplicates_removed)} duplicate records removed by "
            f"scopus_combine() from {_count(x.records_combined)} combined, matched "
            "on the Scopus identifier and failing that the DOI."
        )
        supplied.add(16)
    elif x.n_records is None:
        notes[15] = ("How duplicate records were removed, which this plan has not "
                     "been run to produce.")
    else:
        notes[15] = ("How duplicate records were removed, which this set does not "
                     "record.")

    items = list(range(1, 17))
    return pd.DataFrame({
        "item": items,
        "name": PRISMA_S_ITEMS,
        "source": ["record" if i in supplied else "author" for i in items],
        "note": notes,
    })


# Rendering -----------------------------------------------------------------


def _was_run(x: SearchReport) -> bool:
    return x.n_records is not None


def _cells_text(n: int) -> str:
    """A number of cells, as the record states it."""
    return f"{_count(n)} {'cell' if n == 1 else 'cells'}"


def _stop_phrase(x: SearchReport) -> str:
    """How far a stopped harvest got, for the completeness line and item 15."""
    return (f"the harvest was stopped after {_count(x.cells_run)} of "
            f"{_cells_text(x.cells_planned)}")


def _stop_clause(x: SearchReport) -> str | None:
    """The cells a stopped harvest planned and retrieved, and the years those
    covered, as one clause that item 9 and the paragraph each finish in their
    own way. ``None`` when the harvest ran every cell. The years are given only
    where the cells could be placed on the plan the harvest ran."""
    if not x.stopped_early:
        return None
    k = x.cells_run
    if x.cells_planned == 1 and k == 0:
        return "The single cell planned was not retrieved before the harvest was stopped"
    retrieved = "none was" if k == 0 else f"{_count(k)} {'was' if k == 1 else 'were'}"
    years = f" ({x.years_run})" if x.years_run is not None else ""
    return (f"Of the {_cells_text(x.cells_planned)} planned, {retrieved} retrieved "
            f"before the harvest was stopped{years}")


def _cap_counts(x: SearchReport) -> tuple[int, int]:
    """How many cells stopped at the cap, and how many fell short of the total
    the API reported for them. A capped cell with a known total counts in
    both."""
    capped = sum(_capped(x.cells, x.max_results))
    short = 0
    for n, reported in zip(x.cells["n_records"], x.cells["reported_total"], strict=True):
        n, reported = _known(n), _known(reported)
        if n is not None and reported is not None and n < reported:
            short += 1
    return capped, short


def _cap_status(x: SearchReport) -> str | None:
    """Whether the cap stopped any cell (``"bound"``) or stopped none of the
    cells that ran, every one of them counted (``"unbound"``). It cannot be
    judged (``"unknown"``) where a cell's count is unrecorded or no cell ran.
    A harvest stopped before its first cell retrieved nothing under the cap,
    and saying that the cap did not bind would describe a retrieval that never
    happened. ``None`` when no cap was set."""
    if x.max_results is None:
        return None
    if _cap_counts(x)[0] > 0:
        return "bound"
    ran = [_known(n) for cell, n in zip(x.cells["cell"], x.cells["n_records"], strict=True)
           if cell not in x.not_run]
    return "unbound" if ran and all(n is not None for n in ran) else "unknown"


def _cap_sentence(x: SearchReport) -> str | None:
    """The cap as item 9 states it, a limit on the search like the years.
    ``None`` when no cap was set."""
    status = _cap_status(x)
    if status is None:
        return None
    cap = _count(x.max_results)
    if status == "bound":
        return f"Records per cell were capped at {cap}."
    if status == "unbound":
        return f"A cap of {cap} records per cell was set and did not bind."
    return f"A cap of {cap} records per cell was set."


def _cap_paragraph(x: SearchReport) -> str | None:
    """The cap as the paragraph states it. A cap that stopped a cell is set
    beside the shortfall. It explains the shortfall in full only when every
    cell that fell short stopped at it."""
    status = _cap_status(x)
    if status != "bound":
        return _cap_sentence(x)
    cap = _count(x.max_results)
    capped, short = _cap_counts(x)
    if (x.reported_total is not None and x.n_records < x.reported_total
            and capped == short):
        return f"Records per cell were capped at {cap}, which accounts for the whole shortfall."
    return (f"Records per cell were capped at {cap}, and {_count(capped)} of "
            f"{_cells_text(len(x.cells) - len(x.not_run))} stopped at that cap.")


def _pairs(x: SearchReport) -> list[tuple[str, str]]:
    """The label/value pairs the readable record and the Markdown share, so the
    two renderings can never drift apart in substance."""
    run = _was_run(x)
    stopped = x.stopped_early

    expression = "; ".join(x.expression) if x.expression else "unrecorded"
    if x.field is not None:
        field = x.field
    else:
        field = "unrecorded" if x.partition is None else "none was applied"
    # A stopped harvest searched only the years of the cells it ran. The line
    # gives those first, beside the years the plan set.
    if x.years is not None and x.not_run:
        years = f"{x.years_run or 'none'}, of {x.years} planned"
    elif x.years is not None:
        years = x.years
    elif x.partition is not None:
        years = "no year limit was applied"
    else:
        years = "unrecorded"
    if x.partition is None:
        partition = "unrecorded"
    elif x.partition == "year":
        partition = f"one cell per year, {_count(x.n_cells)} cells"
    else:
        partition = "a single cell"
    view = x.view or "unrecorded"
    page_size = (f"{_count(x.page_size)} records per request"
                 if x.page_size is not None else "unrecorded")
    paging = x.paging or "unrecorded"
    if not run:
        searched = _NOT_RUN
    elif stopped and x.cells_run == 0:
        searched = "none, the harvest was stopped before its first cell"
    elif _spans_days(x):
        searched = f"{_stamp(x.searched_at)} to {_stamp(x.searched_until)}"
    elif x.searched_at is not None:
        searched = _stamp(x.searched_at)
    else:
        searched = "unrecorded, this set does not carry the time it was retrieved"
    software = f"scopusflow {x.version}" if x.version else "unrecorded"

    retrieved = _count(x.n_records) if run else "none, this plan has not been run"
    missing = len(x.cells) - x.cells_reported
    # The cells a stopped harvest never reached were never counted, which is
    # not the same as a count that failed to travel.
    if not run:
        reported = _NOT_RUN
    elif stopped:
        reported = (f"not counted for the {_cells_text(x.cells_planned - x.cells_run)} "
                    "not run, so no overall figure is given")
    elif x.reported_total is not None:
        reported = _count(x.reported_total)
    elif x.cells_reported > 0:
        reported = (f"unrecorded for {_count(missing)} of {_count(len(x.cells))} "
                    "cells, so no overall figure is given")
    else:
        reported = "unrecorded, the API's own count did not travel with this set"

    # A cap explains the shortfall in full only when every cell that fell short
    # stopped at it. Otherwise, the cells that did are counted, so the rest of
    # the shortfall stays visible.
    capped, short = _cap_counts(x)
    capped_cells = (f"{_count(capped)} of {_cells_text(len(x.cells))} stopped at the "
                    f"requested cap of {_count(x.max_results or 0)}")
    if not run:
        completeness = _NOT_RUN
    elif stopped:
        completeness = f"incomplete, {_stop_phrase(x)}"
    elif x.reported_total is None:
        completeness = ("unrecorded, since the number of records the API reported "
                        "as matching is not known")
        if capped:
            completeness += f", and {capped_cells}"
    elif x.n_records >= x.reported_total:
        completeness = "every record the API reported as matching was retrieved"
    else:
        completeness = (f"{_count(x.n_records)} of the {_count(x.reported_total)} "
                        "records reported as matching were retrieved")
        if capped and capped == short:
            completeness += (", a shortfall due to the requested cap of "
                             f"{_count(x.max_results)} records per cell")
        elif capped:
            completeness += f", and {capped_cells}"

    if not run:
        duplicates = _NOT_RUN
    elif x.deduplicated and x.duplicates_removed is not None:
        duplicates = (f"{_count(x.duplicates_removed)} of "
                      f"{_count(x.records_combined)} combined records")
    elif x.deduplicated is False:
        duplicates = "none, the sets were combined without de-duplication"
    else:
        duplicates = "unrecorded, no de-duplication step was recorded for this set"

    doi = (f"{_count(x.n_with_doi)} of {_count(x.n_records)}" if run else _NOT_RUN)

    return [
        ("Database", f"{x.database}, on the {x.platform}"),
        ("Search expression", expression),
        ("Field tag", field),
        ("Years", years),
        ("Partition", partition),
        ("View", view),
        ("Page size", page_size),
        ("Paging", paging),
        ("Date searched", searched),
        ("Software", software),
        ("Records retrieved", retrieved),
        ("Records reported as matching", reported),
        ("Completeness", completeness),
        ("Duplicates removed", duplicates),
        ("Records carrying a DOI", doi),
    ]


def _cell_rows(x: SearchReport):
    # A plan that sets no year limit has none, but a set without a plan only
    # fails to record one, so the two are told apart.
    unset = "no year limit" if x.partition is not None else "year limit unrecorded"
    for row in x.cells.itertuples(index=False):
        limit = unset if row.limit is None or pd.isna(row.limit) else str(row.limit)
        n = None if row.n_records is None or pd.isna(row.n_records) else int(row.n_records)
        reported = (None if row.reported_total is None or pd.isna(row.reported_total)
                    else int(row.reported_total))
        yield int(row.cell), limit, n, reported


def _cell_lines(x: SearchReport) -> list[str]:
    """One line per cell for the readable record. A cell a stopped harvest
    never reached reads "not run". One that stopped at the cap names it where
    it would read "incomplete", since the cap is why it holds fewer records."""
    lines = []
    capped = _capped(x.cells, x.max_results)
    for i, (cell, limit, n, reported) in enumerate(_cell_rows(x)):
        counted = None
        if n is not None:
            counted = (f"{_count(n)} retrieved, reported total unrecorded"
                       if reported is None else
                       f"{_count(n)} retrieved, {_count(reported)} reported")
        if cell in x.not_run:
            tail = "not run"
        elif n is None:
            tail = "retrieved records unrecorded"
        elif capped[i]:
            tail = f"{counted}, stopped at the requested cap of {_count(x.max_results)}"
        elif reported is None:
            tail = counted
        elif n >= reported:
            tail = f"{counted}, complete"
        else:
            tail = f"{counted}, incomplete"
        lines.append(f"  {_count(cell)} ({limit}): {tail}")
    return lines


def _cell_table(x: SearchReport) -> list[str]:
    rows = ["| Cell | Limit | Retrieved | Reported | Complete |", "|---|---|---|---|---|"]
    capped = _capped(x.cells, x.max_results)
    for i, (cell, limit, n, reported) in enumerate(_cell_rows(x)):
        unrun = cell in x.not_run
        if unrun:
            complete = "no"
        elif capped[i]:
            complete = f"capped at {_count(x.max_results)}"
        elif n is None or reported is None:
            complete = "unrecorded"
        else:
            complete = "yes" if n >= reported else "no"
        retrieved = "not run" if unrun else "unrecorded" if n is None else _count(n)
        counted = ("not run" if unrun else "unrecorded" if reported is None
                   else _count(reported))
        rows.append(f"| {_count(cell)} | {limit} | {retrieved} | {counted} | {complete} |")
    return rows


def _identification(x: SearchReport) -> list[tuple[str, str]]:
    """The identification counts of the PRISMA 2020 flow diagram, which asks for
    the records identified per database and the duplicates removed before
    screening.

    Identification is counted before duplicates are taken out, so where a merge
    recorded how many records went into it, that is the figure. Giving the
    surviving row count instead would put two numbers in the box that cannot
    both be right: the diagram subtracts the duplicates removed from the records
    identified to get the records screened, and 138 identified less 11 removed
    is not the 138 rows the set holds.
    """
    run = _was_run(x)
    if not run:
        identified = _NOT_RUN
    elif x.records_combined is not None:
        identified = _count(x.records_combined)
    else:
        identified = _count(x.n_records)
    if not run:
        removed = _NOT_RUN
    elif x.deduplicated and x.duplicates_removed is not None:
        removed = _count(x.duplicates_removed)
    elif x.deduplicated is False:
        removed = "none, the sets were combined without de-duplication"
    else:
        removed = "unrecorded, no de-duplication step was recorded for this set"
    return [
        ("Records identified from Scopus", identified),
        ("Duplicate records removed before screening", removed),
    ]


def _prisma_lines(x: SearchReport, source: str, bullet: str) -> list[str]:
    rows = x.prisma[x.prisma["source"] == source]
    return [f"{bullet}{row.item} {row.name}. {row.note}"
            for row in rows.itertuples(index=False)]


def _render_report(x: SearchReport) -> str:
    lines = ["Search strategy record (PRISMA-S)", ""]
    lines += [f"{label}: {value}" for label, value in _pairs(x)]
    lines += ["", "Cells"] + _cell_lines(x)
    lines += ["", "PRISMA 2020 identification"]
    lines += [f"  {label}: {value}" for label, value in _identification(x)]
    lines += ["", "PRISMA-S items this record supplies"]
    lines += _prisma_lines(x, "record", "  ")
    lines += ["", "PRISMA-S items only you can supply"]
    lines += _prisma_lines(x, "author", "  ")
    lines += ["", _REFERENCE]
    return "\n".join(lines)


def _render_markdown(x: SearchReport) -> str:
    if x.snippet is None:
        snippet = ["The plan that produced this set is not attached to it, so no "
                   "reproduction snippet can be written. Attach the plan, or pass "
                   "it as the plan argument."]
    else:
        snippet = [
            "The plan below rebuilds the search exactly as it was described. "
            "Running the harvest again contacts the API and spends quota.",
            "", "```python", x.snippet, "```",
        ]
    lines = [
        "# Search strategy record",
        "",
        "Assembled by scopusflow from the search plan and the records it "
        "produced. Every figure below is taken from those objects. Anything "
        "they do not record is marked unrecorded, and is yours to supply.",
        "",
        "## The search",
        "",
    ]
    lines += [f"- {label}: {value}" for label, value in _pairs(x)]
    lines += ["", "## Cells", ""] + _cell_table(x)
    lines += ["", "## Methods paragraph", "", _render_paragraph(x)]
    lines += ["", "## Reproducing this search", ""] + snippet
    lines += ["", "## PRISMA 2020 identification", ""]
    lines += [f"- {label}: {value}" for label, value in _identification(x)]
    lines += ["", "## PRISMA-S coverage", "", "Supplied by this record.", ""]
    lines += _prisma_lines(x, "record", "- ")
    lines += ["", "Yours to supply.", ""]
    lines += _prisma_lines(x, "author", "- ")
    lines += ["", _REFERENCE]
    return "\n".join(lines)


def _render_paragraph(x: SearchReport) -> str:
    """The methods paragraph.

    Every sentence is conditioned on the evidence, so the paragraph never
    asserts a figure the record does not hold; the suite recomputes each of its
    numerals from the object independently.
    """
    run = _was_run(x)
    stopped = x.stopped_early
    sentences = []

    # A harvest stopped before its first cell searched nothing, so the opening
    # says what was to be searched and the stop is explained below.
    if not run:
        sentences.append("The search described here has not been run.")
    elif stopped and x.cells_run == 0:
        sentences.append("The literature was to be searched in Scopus, on the Elsevier "
                         "Scopus Search API.")
    elif x.searched_at is None:
        sentences.append("The literature was searched in Scopus, on the Elsevier "
                         "Scopus Search API, on a date this record does not carry.")
    elif _spans_days(x):
        sentences.append("The literature was searched in Scopus, on the Elsevier "
                         f"Scopus Search API, between {_date(x.searched_at)} and "
                         f"{_date(x.searched_until)}.")
    else:
        sentences.append("The literature was searched in Scopus, on the Elsevier "
                         f"Scopus Search API, on {_date(x.searched_at)}.")

    expression = "; ".join(x.expression) if x.expression else None
    # Past tense only where there is a completed search to describe. A plan that
    # has not run is described in the present, or the sentence contradicts the
    # opening; the same rule governs the retrieval sentence below.
    verb = "was" if run else "is"
    if expression is None:
        sentences.append("The search expression is unrecorded in this set.")
    elif x.years is not None:
        sentences.append(f"The search expression {verb} {expression}, limited to "
                         f"publication years {x.years}.")
    elif x.partition is not None:
        sentences.append(f"The search expression {verb} {expression}, with no "
                         "year limit.")
    else:
        sentences.append(f"The search expression {verb} {expression}, and its year "
                         "limit is unrecorded.")

    known = x.view is not None and x.page_size is not None
    if x.partition is not None:
        # A record of a completed search reads in the past tense, while a plan that
        # has not run describes what it would do, or this sentence contradicts the
        # opening. "each" distributes over cells, so it belongs only to the
        # partitioned form. A stopped harvest was partitioned all the same, but
        # its cells were only to be retrieved, since some of them never were.
        plan_verb = "was" if run else "would be"
        partitioned = x.partition == "year"
        if partitioned:
            how = (f"It {plan_verb} partitioned into {_count(x.n_cells)} "
                   "cells, one per year")
        else:
            how = f"It {'was to be' if stopped else plan_verb} retrieved as a single search"
        if not partitioned:
            through = " through"
        elif stopped:
            through = ", each to be retrieved through"
        else:
            through = ", each retrieved through"
        if known and x.paging is not None:
            how += (f"{through} the {x.view} view in pages of "
                    f"{_count(x.page_size)} records under {x.paging} paging.")
        elif known:
            # A plan has no paging mode to be missing: the mode is settled by the
            # fetch, so an unrun plan is told what will decide it, where the
            # wording for a harvest would accuse it of having lost it.
            unpaged = ("a paging mode this record does not carry" if run
                       else "a paging mode chosen when the search is run")
            how += (f"{through} the {x.view} view in pages of "
                    f"{_count(x.page_size)} records, under {unpaged}.")
        else:
            how += ", and the view and page size of the retrieval are unrecorded."
        sentences.append(how)

    if run:
        # How far a stopped harvest got comes before what it retrieved, which
        # then needs no word on completeness.
        if stopped:
            sentences.append(f"{_stop_clause(x)}, so the harvest is incomplete.")
            sentences.append(f"The search retrieved {_count(x.n_records)} records.")
        elif x.reported_total is not None and x.n_records >= x.reported_total:
            sentences.append(
                f"The search retrieved {_count(x.n_records)} records, matching the "
                f"{_count(x.reported_total)} the API reported, so every reported "
                "record was retrieved.")
        elif x.reported_total is not None:
            sentences.append(
                f"The search retrieved {_count(x.n_records)} records of the "
                f"{_count(x.reported_total)} the API reported as matching, so the "
                "harvest is incomplete.")
        elif x.cells_reported > 0:
            sentences.append(
                f"The search retrieved {_count(x.n_records)} records. The API's "
                "count of matching records is missing for "
                f"{_count(len(x.cells) - x.cells_reported)} of the "
                f"{_count(len(x.cells))} cells, so no overall total is given.")
        else:
            sentences.append(
                f"The search retrieved {_count(x.n_records)} records. The API's own "
                "count of matching records was not recorded, so the harvest cannot "
                "be shown to be complete.")
        cap = _cap_paragraph(x)
        if cap is not None:
            sentences.append(cap)
        # Named outright. "Of these" would, in the branches above, end up next
        # to the cells or the matching records and so point at the wrong noun.
        sentences.append(
            f"Of the records retrieved, {_count(x.n_with_doi)} carry a DOI.")
        if x.deduplicated and x.duplicates_removed is not None:
            sentences.append(
                f"De-duplication removed {_count(x.duplicates_removed)} records "
                f"from the {_count(x.records_combined)} combined.")
        elif x.deduplicated is False:
            sentences.append("The retrievals were combined without de-duplication.")
        else:
            sentences.append("No de-duplication step was recorded for this set.")
        sentences.append(
            f"The search was run with scopusflow {x.version}." if x.version
            else "The version of scopusflow that produced this set is unrecorded.")

    sentences.append(
        "The PRISMA-S items this record cannot supply, among them peer review of "
        "the strategy, grey literature and any other database searched, remain "
        "yours to report.")
    return " ".join(sentences)
