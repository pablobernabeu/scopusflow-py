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
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone

import pandas as pd

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

# English month names, spelled out rather than taken from the locale: the
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


def _stamp(t: datetime) -> str:
    """An instant, always shown in UTC. A retrieval stamp is an absolute time,
    and a methods section that says when a search ran should not depend on the
    reader's machine to interpret it."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _date(t: datetime) -> str:
    utc = t.astimezone(timezone.utc)
    return f"{utc.day} {_MONTHS[utc.month - 1]} {utc.year}"


@dataclass(eq=False)
class SearchReport:
    """The fields a search record is built from, and its three renderings.

    Every attribute is either what the objects recorded or ``None``, which the
    renderings spell out as unrecorded. ``cells`` is a frame of ``cell``,
    ``limit``, ``n_records`` and ``reported_total``; ``prisma`` a frame of
    ``item``, ``name``, ``source`` (``"record"`` or ``"author"``) and ``note``.
    """

    database: str = "Scopus"
    platform: str = "Elsevier Scopus Search API"
    query: str | None = None
    field: str | None = None
    expression: list[str] | None = None
    view: str | None = None
    page_size: int | None = None
    paging: str | None = None
    partition: str | None = None
    n_cells: int | None = None
    years: str | None = None
    cells: pd.DataFrame = dataclass_field(default_factory=pd.DataFrame)
    searched_at: datetime | None = None
    version: str | None = None
    n_records: int | None = None
    n_with_doi: int | None = None
    reported_total: int | None = None
    cells_reported: int = 0
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

    Everything in the record comes from the objects handed to it. The date of
    the search is the ``retrieved_at`` attribute :func:`scopusflow.fetch.fetch_plan`
    attaches, never the current time; the number of records the API reported as
    matching is the per-cell accounting in ``cell_totals``, never an inference
    from the number of rows; and the duplicates removed are those
    :func:`scopusflow.combine.scopus_combine` recorded removing. Where an
    attribute is absent, as it is for a frame read back from CSV, for the
    bundled corpus, and for a harvest with a cell resumed from a checkpoint, the
    record says the field is unrecorded rather than filling it. This matters
    most for completeness: a harvest whose reported total is unknown is never
    described as exhaustive.

    The PRISMA-S map is decided the same way. Items the package holds evidence
    for (the database and platform, the full strategy, the limits, the date, the
    totals, and de-duplication where it was performed) are listed as supplied.
    The rest, among them peer review of the strategy, grey literature, other
    databases and citation searching, are listed as the author's to supply,
    because the package has no way to know them.

    Parameters
    ----------
    x:
        A records frame, which supplies the counts and the retrieval provenance
        and, through ``attrs["plan"]``, the plan; or a bare
        :class:`~scopusflow.plan.SearchPlan` for a search not yet run.
    plan:
        The plan describing ``x``. Supply it when a records frame does not carry
        one, for instance one read back from CSV. An explicit plan takes
        precedence over the one ``x`` carries.
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
    >>> plan = sf.SearchPlan("graphene supercapacitor", years=range(2015, 2025),
    ...                      field="TITLE-ABS-KEY", partition="year")
    >>> report = sf.scopus_search_report(plan)
    >>> report.n_records is None
    True

    The same search after a harvest. The bundled corpus stands in for one, since
    Scopus records may not be redistributed, so the attributes a live retrieval
    records are set here by hand.

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
            carried = x.attrs.get("plan")
            plan = carried if isinstance(carried, SearchPlan) else None
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
    cells = _cells(records, plan)
    reported = cells["reported_total"]
    n_reported = int(reported.notna().sum())
    total = int(reported.sum()) if len(cells) and n_reported == len(cells) else None

    combined = records.attrs.get("combined") if records is not None else None
    stamp = records.attrs.get("retrieved_at") if records is not None else None
    version = records.attrs.get("scopusflow_version") if records is not None else None
    if isinstance(version, (list, tuple)):
        version = ", ".join(str(v) for v in version)

    report = SearchReport(
        query=plan.query if plan is not None else None,
        field=plan.field if plan is not None else None,
        expression=_expression(records, plan),
        view=plan.view if plan is not None else None,
        page_size=int(plan.page_size) if plan is not None else None,
        paging=records.attrs.get("paging") if records is not None else None,
        partition=plan.partition if plan is not None else None,
        n_cells=len(plan.cells()) if plan is not None else None,
        years=_years(cells),
        cells=cells,
        searched_at=stamp,
        version=str(version) if version is not None else None,
        n_records=len(records) if records is not None else None,
        n_with_doi=int(records["doi"].notna().sum()) if records is not None else None,
        reported_total=total,
        cells_reported=n_reported,
        records_combined=_combined(combined, "n_in"),
        duplicates_removed=_combined(combined, "n_removed"),
        deduplicated=bool(combined["deduplicated"]) if combined else None,
        snippet=_snippet(plan),
    )
    report.prisma = _prisma(report)
    return report


def _cells(records, plan) -> pd.DataFrame:
    """The per-cell table.

    A plan supplies the cells and their year limits; the counts come from the
    ``cell_totals`` attribute ``fetch_plan`` records, and stay missing when the
    frame never carried one (a CSV round trip, the bundled corpus, a frame
    assembled by hand). Without a plan the whole retrieval is treated as one
    cell, so the rest of the module has a single shape to render.
    """
    counts = records.attrs.get("cell_totals") if records is not None else None
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
    """The year span actually sent, read back from the cells' date limits rather
    than from any year sequence, because the limit is what reached the API."""
    limits = [str(v) for v in cells["limit"] if v is not None and not pd.isna(v)]
    years = [int(m) for limit in limits for m in _digits(limit)]
    if not years:
        return None
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else f"{lo} to {hi}"


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


def _snippet(plan) -> str | None:
    """The runnable reproduction.

    Built from what the plan records, so that running it returns a plan equal to
    the one the report describes; the test suite asserts exactly that over a
    grid of plans. Without a plan there is nothing to reproduce.
    """
    if plan is None:
        return None
    # Imported here rather than at module scope: app_helpers reads the package
    # version at import time, and this module is imported while the package's
    # own __init__ is still executing.
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
    return (
        "import scopusflow as sf\n"
        "\n"
        f"plan = sf.SearchPlan(\n{body}\n)\n"
        "\n"
        "records = sf.fetch_plan(plan)"
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

    notes[1] = ("Whether any database besides Scopus was searched, and how the "
                "strategy was translated for it.")
    notes[2] = "Any trial or study registry searched."
    notes[3] = ("Any web site, table of contents or other source searched or "
                "browsed by hand.")
    notes[4] = "Any backward or forward citation searching."
    notes[5] = "Any authors or organisations contacted for studies."
    notes[6] = "Any further method used to identify records."

    if x.expression:
        notes[7] = ("The search expression, field tag and year limit of every "
                    "cell, as the plan sends them.")
        supplied.add(8)
    else:
        notes[7] = "The exact strategy, which this set does not record."

    if x.partition is not None:
        notes[8] = (
            "No year limit was applied, and scopusflow applies no document type, "
            "language or subject area limit of its own."
            if x.years is None else
            f"Publication years {x.years}. scopusflow applies no document type, "
            "language or subject area limit of its own."
        )
        supplied.add(9)
    else:
        notes[8] = "Any limit applied to the search, which this set does not record."

    notes[9] = ("Any published or validated search filter used, and where it came "
                "from. scopusflow applies none of its own.")
    notes[10] = "Any earlier review or strategy this search was adapted from."
    notes[11] = "Whether the search was re-run or updated, and when."

    if x.searched_at is not None:
        notes[12] = f"{_stamp(x.searched_at)}."
        supplied.add(13)
    elif x.n_records is None:
        notes[12] = ("The date of each search, which this plan has not been run "
                     "to produce.")
    else:
        notes[12] = "The date of each search, which this set does not carry."

    notes[13] = "Whether the strategy was peer reviewed, and by whom."

    if x.n_records is not None:
        notes[14] = (
            f"{_count(x.n_records)} records retrieved from Scopus. The API's own "
            "count of matching records is unrecorded."
            if x.reported_total is None else
            f"{_count(x.n_records)} records retrieved from Scopus, of "
            f"{_count(x.reported_total)} the API reported as matching."
        )
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


def _pairs(x: SearchReport) -> list[tuple[str, str]]:
    """The label/value pairs the readable record and the Markdown share, so the
    two renderings can never drift apart in substance."""
    run = _was_run(x)

    expression = "; ".join(x.expression) if x.expression else "unrecorded"
    if x.field is not None:
        field = x.field
    else:
        field = "unrecorded" if x.partition is None else "none was applied"
    if x.years is not None:
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
    elif x.searched_at is not None:
        searched = _stamp(x.searched_at)
    else:
        searched = "unrecorded, this set does not carry the time it was retrieved"
    software = f"scopusflow {x.version}" if x.version else "unrecorded"

    retrieved = _count(x.n_records) if run else "none, this plan has not been run"
    missing = len(x.cells) - x.cells_reported
    if not run:
        reported = _NOT_RUN
    elif x.reported_total is not None:
        reported = _count(x.reported_total)
    elif x.cells_reported > 0:
        reported = (f"unrecorded for {_count(missing)} of {_count(len(x.cells))} "
                    "cells, so no overall figure is given")
    else:
        reported = "unrecorded, the API's own count did not travel with this set"

    if not run:
        completeness = _NOT_RUN
    elif x.reported_total is None:
        completeness = ("unrecorded, since the number of records the API reported "
                        "as matching is not known")
    elif x.n_records >= x.reported_total:
        completeness = "every record the API reported as matching was retrieved"
    else:
        completeness = (f"{_count(x.n_records)} of the {_count(x.reported_total)} "
                        "records reported as matching were retrieved")

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
    for row in x.cells.itertuples(index=False):
        limit = "no year limit" if row.limit is None or pd.isna(row.limit) else str(row.limit)
        n = None if row.n_records is None or pd.isna(row.n_records) else int(row.n_records)
        reported = (None if row.reported_total is None or pd.isna(row.reported_total)
                    else int(row.reported_total))
        yield int(row.cell), limit, n, reported


def _cell_lines(x: SearchReport) -> list[str]:
    lines = []
    for cell, limit, n, reported in _cell_rows(x):
        if n is None:
            tail = "retrieved records unrecorded"
        elif reported is None:
            tail = f"{_count(n)} retrieved, reported total unrecorded"
        elif n >= reported:
            tail = f"{_count(n)} retrieved, {_count(reported)} reported, complete"
        else:
            tail = f"{_count(n)} retrieved, {_count(reported)} reported, incomplete"
        lines.append(f"  {_count(cell)} ({limit}): {tail}")
    return lines


def _cell_table(x: SearchReport) -> list[str]:
    rows = ["| Cell | Limit | Retrieved | Reported | Complete |", "|---|---|---|---|---|"]
    for cell, limit, n, reported in _cell_rows(x):
        complete = "unrecorded" if n is None or reported is None else (
            "yes" if n >= reported else "no")
        rows.append(
            f"| {_count(cell)} | {limit} | "
            f"{'unrecorded' if n is None else _count(n)} | "
            f"{'unrecorded' if reported is None else _count(reported)} | {complete} |"
        )
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
    sentences = []

    if not run:
        sentences.append("The search described here has not been run.")
    elif x.searched_at is None:
        sentences.append("The literature was searched in Scopus, on the Elsevier "
                         "Scopus Search API, on a date this record does not carry.")
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
        # partitioned form.
        retrieval_verb = "was" if run else "would be"
        partitioned = x.partition == "year"
        if partitioned:
            how = (f"It {retrieval_verb} partitioned into {_count(x.n_cells)} "
                   "cells, one per year")
        else:
            how = f"It {retrieval_verb} retrieved as a single search"
        through = ", each retrieved through" if partitioned else " through"
        if known and x.paging is not None:
            how += (f"{through} the {x.view} view in pages of "
                    f"{_count(x.page_size)} records under {x.paging} paging.")
        elif known:
            # A plan has no paging mode to be missing: the mode is settled by the
            # fetch, so an unrun plan is told what will decide it rather than
            # accused of having lost it.
            unpaged = ("a paging mode this record does not carry" if run
                       else "a paging mode chosen when the search is run")
            how += (f"{through} the {x.view} view in pages of "
                    f"{_count(x.page_size)} records, under {unpaged}.")
        else:
            how += ", and the view and page size of the retrieval are unrecorded."
        sentences.append(how)

    if run:
        if x.reported_total is not None and x.n_records >= x.reported_total:
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
        # Named rather than "of these", which in the branches above ends up next
        # to the cells or the matching records and so points at the wrong noun.
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
