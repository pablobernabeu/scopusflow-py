"""Execute a search plan with resumable, checkpointed retrieval.

This is the workflow layer's reason to exist: it drives ``pybliometrics`` (which
handles the HTTP, cursor pagination, quota rotation and per-query caching) but
adds a project-level, resumable harvest with per-cell checkpoints and a single
normalised output frame. The exact ``ScopusSearch`` call is intentionally thin;
confirm the keyword arguments against your installed pybliometrics version.
"""

from __future__ import annotations

import logging
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .plan import SearchPlan
from .records import RECORD_COLUMNS, to_records

#: Per-cell progress is emitted on this logger; attach a handler to surface it
#: (the GUI streams it into a live terminal). A NullHandler keeps the library
#: quiet by default.
logger = logging.getLogger("scopusflow")
logger.addHandler(logging.NullHandler())

#: Checkpoint formats understood by :func:`fetch_plan`.
_FORMATS = {"parquet", "csv"}

#: The text columns a CSV checkpoint must be read back as strings. CSV carries
#: no types, so ``read_csv`` infers them, and inference promotes an all-digits
#: Scopus identifier to a float: "85012345678" comes back as 85012345678.0 and
#: is then exported as a real, wrong identifier. The bundled example CSV is read
#: with the same schema, for the same reason (see :mod:`scopusflow.data`).
_CHECKPOINT_TEXT = (
    "scopus_id", "doi", "title", "authors", "date", "publication", "query",
    "authkeywords",
)

#: The nullable-integer columns of a CSV checkpoint.
_CHECKPOINT_INTEGER = ("year", "citations")


def _cell_query(query: str, year: int | None, date: str | None) -> str:
    """Fold the year filter into the query, since it travels with the search.

    Handles an explicit ``year``, a ``"YYYY-YYYY"`` range, a single ``"YYYY"``
    date and ``None`` (no year constraint).
    """
    if year is not None:
        return f"{query} AND PUBYEAR IS {int(year)}"
    if date and "-" in date:
        lo, hi = date.split("-", 1)
        return f"{query} AND PUBYEAR AFT {int(lo) - 1} AND PUBYEAR BEF {int(hi) + 1}"
    if date:
        return f"{query} AND PUBYEAR IS {int(date)}"
    return query


def _find_checkpoint(cache: Path, cell: int) -> Path | None:
    """Return an existing checkpoint for ``cell`` of either extension, if any."""
    for suffix in (".parquet", ".csv"):
        candidate = cache / f"cell-{cell:03d}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _read_checkpoint(path: Path) -> pd.DataFrame | None:
    """Read a checkpoint back, dispatching on its extension, or ``None`` when it
    cannot be read.

    A CSV is read with the record schema imposed, never inferred, so a
    resumed cell carries the same identifiers it was written with. The columns
    are named here and never taken from the file, since a checkpoint written by an
    older version may lack ``authkeywords``; pandas ignores a dtype naming a
    column the file does not have.

    A damaged checkpoint must not be able to abort every subsequent resume:
    refetching one cell costs quota, whereas an unreadable file the caller has
    to find and delete by hand defeats the point of resuming at all.

    Raising is not the only way a checkpoint can be damaged, and on the CSV path
    it is not even the common one. An interrupted write leaves a truncated file,
    and a truncated CSV is still a well-formed CSV: pandas parses it without
    complaint. Worse, a row wider than its header does not raise either -- pandas
    reads the surplus leading field as an index, so ``a,b`` over ``1,2,3`` yields
    a tidy two-column frame. Catching exceptions alone therefore returned
    whatever the wreckage happened to parse as, and the caller merged it. So the
    frame is checked against the schema it was written with as well: every
    :data:`RECORD_COLUMNS` name must be present. ``authkeywords`` is deliberately
    not required, since a checkpoint written before that column existed simply
    predates it.
    """
    try:
        if path.suffix == ".csv":
            frame = pd.read_csv(path, dtype=dict.fromkeys(_CHECKPOINT_TEXT, "string"))
            for column in _CHECKPOINT_INTEGER:
                if column in frame.columns:
                    # to_numeric first, so a checkpoint already float-promoted by
                    # an earlier resume still reads back as a whole number.
                    frame[column] = pd.array(
                        pd.to_numeric(frame[column], errors="coerce"), dtype="Int64"
                    )
        else:
            frame = pd.read_parquet(path)
    except Exception:  # the caller warns and refetches the cell
        return None
    if not set(RECORD_COLUMNS).issubset(frame.columns):
        return None
    return frame


def _checkpoint_view(frame: pd.DataFrame) -> str | None:
    """The view a checkpoint was written under, where detectable.

    New checkpoints record it in a ``view`` column (stripped again on resume,
    so the output schema is untouched). An older checkpoint without that column
    still gives itself away in one direction: an ``authkeywords`` column only
    ever comes from ``view="COMPLETE"``. A checkpoint carrying neither is
    indistinguishable from one written before the column existed, and returns
    ``None`` so the documented old-checkpoint tolerance under ``COMPLETE``
    keeps working.
    """
    if "view" in frame.columns:
        recorded = set(frame["view"].dropna().unique())
        if len(recorded) == 1:
            return recorded.pop()
    if "authkeywords" in frame.columns:
        return "COMPLETE"
    return None


def _reported_total(search) -> int | None:
    """The API's own count of what the cell's query matches, or ``None``.

    Optional in the same way as the abstract layer's quota lookup: a
    pybliometrics version, or a test double, that does not expose the figure
    reports nothing, and never fails a harvest over a diagnostic.
    """
    getter = getattr(search, "get_results_size", None)
    if not callable(getter):
        return None
    try:
        return int(getter())
    except Exception:  # a diagnostic must never sink the retrieval it describes
        return None


def _atomic_write(write, target: Path) -> None:
    """Run ``write`` against a sibling temporary file, then rename it onto
    ``target``.

    The rename is atomic within a filesystem, so an interrupted run leaves
    either the previous checkpoint or none at all, never a half-written one that
    every later resume then has to discard. The temporary file is a sibling
    and never a system temporary, since a rename across filesystems is a copy
    and loses the atomicity; its name is not one :func:`_find_checkpoint` looks
    for, so a leftover cannot be mistaken for a checkpoint.
    """
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _write_checkpoint(frame: pd.DataFrame, cache: Path, cell: int, fmt: str) -> None:
    """Write ``frame`` for ``cell`` in ``fmt``, falling back to CSV if parquet
    has no available engine."""
    if fmt == "parquet":
        target = cache / f"cell-{cell:03d}.parquet"
        try:
            _atomic_write(frame.to_parquet, target)
            return
        except Exception:  # parquet engine optional; fall back to CSV
            pass
    _atomic_write(lambda path: frame.to_csv(path, index=False),
                  cache / f"cell-{cell:03d}.csv")


def fetch_plan(
    plan: SearchPlan,
    cache_dir: str | None = None,
    resume: bool = True,
    format: str = "parquet",
    should_stop=None,
    **kwargs,
) -> pd.DataFrame:
    """Run every cell of ``plan`` and return one normalised DataFrame.

    With ``cache_dir`` set, each cell is written to disk as it completes, so an
    interrupted or quota-limited run resumes without re-fetching finished cells.
    A cache_dir belongs to one plan: checkpoints are keyed by cell number, so
    on resume each checkpoint's own recorded query and view are compared
    against the cell's, and a checkpoint written by a different plan is warned
    about and refetched, never silently returned. Point each plan at its own
    directory. A checkpoint that cannot be read back is likewise treated as a
    miss, warned about and refetched, and the harvest carries on.
    ``format`` selects the checkpoint format ("parquet" or "csv"); parquet
    silently falls back to CSV when no parquet engine is installed. Pass a
    zero-argument ``should_stop`` callable to allow co-operative cancellation: it
    is checked before each cell and the harvest stops (returning what it has) when
    it returns ``True``. Per-cell progress is emitted on the ``"scopusflow"``
    logger.

    Each cell's row count is compared against the total the API reports for
    that cell's query, and a shortfall is warned about, since a truncated or
    failed download otherwise arrives as a merely small result. The per-cell
    accounting is attached as ``result.attrs["cell_totals"]``, a frame of
    ``cell``, ``date``, ``n_records`` and ``reported_total``, and their sum as
    ``result.attrs["total_results"]``, the attribute the R twin's
    ``scopus_fetch()`` also attaches. The sum is ``None`` unless every cell
    reported a total, since a partial sum would understate the search while
    looking like a real figure; a cell resumed from a checkpoint reports none,
    the count not being part of what a checkpoint stores.

    The harvest also carries its provenance: the originating ``plan``,
    ``retrieved_at`` (a timezone-aware UTC ``datetime``),
    ``scopusflow_version`` and ``paging``. These are what
    :func:`scopusflow.report.scopus_search_report` reads back, and they are
    omitted, never approximated, when any cell was resumed from a
    checkpoint, since a checkpoint carries no record of when it was taken and
    dating the whole from the cells that were fetched now would date it later
    than part of what it holds.

    When ``plan.view == "COMPLETE"``, the output gains an ``authkeywords``
    column (see :func:`scopusflow.records.to_records`) at no extra request cost
    beyond ``COMPLETE``'s own smaller page size, which already means more
    requests, and so more quota, for the same number of records. A plan with
    ``view="STANDARD"`` (the default) never carries this column, so existing
    code is unaffected: a checkpoint written under the other view is refetched
    like any other different-plan checkpoint. Resuming a cache written before
    this column existed is safe in the ``COMPLETE`` direction:
    ``pandas.concat`` fills the older cells' missing column with ``NA`` rather
    than erroring.
    """
    if not isinstance(plan, SearchPlan):
        raise ValueError("plan must be a SearchPlan.")
    if format not in _FORMATS:
        raise ValueError("format must be 'parquet' or 'csv'.")

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    cache = Path(cache_dir) if cache_dir else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    cells = plan.cells()
    total = len(cells)
    frames: list[pd.DataFrame] = []
    accounting: list[dict] = []
    stamps: list[datetime | None] = []
    for cell in cells:
        if should_stop is not None and should_stop():
            logger.info("Stopped before cell %d/%d.", cell.cell, total)
            break

        query = _cell_query(cell.query, cell.year, cell.date)
        if cache is not None and resume:
            existing = _find_checkpoint(cache, cell.cell)
            cached = _read_checkpoint(existing) if existing is not None else None
            if existing is not None and cached is None:
                warnings.warn(
                    f"The checkpoint {existing} could not be read back, so it "
                    "was discarded and the cell refetched. An interrupted run "
                    "can leave a checkpoint half-written.",
                    stacklevel=2,
                )
            elif cached is not None:
                # Checkpoints are keyed by cell number alone, so a cache_dir
                # reused for a different plan would otherwise hand back the
                # wrong records silently. The frames carry the query they were
                # fetched with; a mismatch means the checkpoint belongs to
                # another plan and the cell is refetched. A zero-row checkpoint
                # carries no query values to compare and is accepted as is.
                # The view is compared too, since the query alone cannot tell
                # a STANDARD plan from a COMPLETE one, and a COMPLETE-written
                # checkpoint would hand a STANDARD resume an authkeywords
                # column the documentation promises it never carries.
                cached_queries = (
                    set(cached["query"].dropna().unique())
                    if "query" in cached.columns else set()
                )
                cached_view = _checkpoint_view(cached)
                if cached_queries and cached_queries != {query}:
                    warnings.warn(
                        f"Checkpoint for cell {cell.cell} in {cache} was written "
                        f"by a different plan (query {sorted(cached_queries)!r}, "
                        f"not {query!r}); refetching this cell. Use one cache_dir "
                        "per plan.",
                        stacklevel=2,
                    )
                elif cached_view is not None and cached_view != cell.view:
                    warnings.warn(
                        f"Checkpoint for cell {cell.cell} in {cache} was written "
                        f"by a different plan (view {cached_view!r}, "
                        f"not {cell.view!r}); refetching this cell. Use one "
                        "cache_dir per plan.",
                        stacklevel=2,
                    )
                else:
                    logger.info("Cell %d/%d: loaded from cache.", cell.cell, total)
                    served = cached.drop(columns=["view"], errors="ignore")
                    frames.append(served)
                    accounting.append({"cell": cell.cell, "date": cell.date,
                                       "n_records": len(served),
                                       "reported_total": None})
                    stamps.append(None)
                    continue

        logger.info("Cell %d/%d: fetching %s", cell.cell, total, query)
        # The page size is the plan's, so the harvest pages the way the plan (and
        # the search record built from it) says it does. setdefault, so a caller
        # passing count of their own still wins.
        kwargs.setdefault("count", cell.page_size)
        search = ScopusSearch(query, view=cell.view, cursor=True, **kwargs)
        frame = to_records(search.results, query=query, view=cell.view)

        # A download that returned nothing yields a zero-row frame and never
        # an error, so without this comparison a truncated or failed cell is
        # indistinguishable from one that matched only a few records.
        cell_total = _reported_total(search)
        accounting.append({"cell": cell.cell, "date": cell.date,
                           "n_records": len(frame), "reported_total": cell_total})
        stamps.append(datetime.now(timezone.utc))
        if cell_total is not None:
            if len(frame) < cell_total:
                warnings.warn(
                    f"Cell {cell.cell} retrieved {len(frame)} record(s), but the "
                    f"Scopus API reports {cell_total} for this query, so the "
                    "harvest may be incomplete. Check the key's remaining quota, "
                    "and consider partitioning the plan by year so each cell is "
                    "smaller.",
                    stacklevel=2,
                )

        if cache is not None:
            # The view travels with the checkpoint (and only the checkpoint;
            # resume strips it again) so a resume under the other view is
            # detectable in both directions, beyond the case where an authkeywords
            # column betrays a COMPLETE origin.
            _write_checkpoint(frame.assign(view=cell.view), cache, cell.cell, format)
        frames.append(frame)

    if not frames:
        columns = [*RECORD_COLUMNS, "authkeywords"] if plan.view == "COMPLETE" else RECORD_COLUMNS
        out = pd.DataFrame(columns=columns)
    else:
        out = pd.concat(frames, ignore_index=True)
        out["entry_number"] = range(1, len(out) + 1)
        logger.info("Retrieved %d records.", len(out))

    # The plan travels with its own harvest, as it does in the R twin, so the
    # search record can be written from the records alone.
    out.attrs["plan"] = plan
    out.attrs["cell_totals"] = pd.DataFrame(
        accounting, columns=["cell", "date", "n_records", "reported_total"]
    )
    reported = [row["reported_total"] for row in accounting]
    out.attrs["total_results"] = (
        sum(reported) if accounting and all(n is not None for n in reported) else None
    )
    out.attrs["paging"] = "cursor"
    if stamps and all(s is not None for s in stamps):
        # Imported inside the function, and never at module scope: this module
        # is imported
        # while the package's own __init__ is still executing, and __version__
        # is not bound until after that import returns.
        from . import __version__

        out.attrs["retrieved_at"] = min(stamps)
        out.attrs["scopusflow_version"] = __version__
    return out
