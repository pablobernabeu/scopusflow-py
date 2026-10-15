"""Execute a search plan with resumable, checkpointed retrieval.

This is the workflow layer's reason to exist: it drives ``pybliometrics`` (which
handles the HTTP, cursor pagination and quota rotation) but adds a
project-level, resumable harvest with per-cell checkpoints and a single
normalised output frame. The exact ``ScopusSearch`` call is intentionally thin;
confirm the keyword arguments against your installed pybliometrics version.

The checkpoints are the only cache a harvest reads by default. pybliometrics
keeps a response cache of its own, keyed on the query string and view alone,
and answers a repeated search from it without contacting the API. Every search
is therefore sent with ``refresh=True`` unless the caller passes ``refresh``.
``refresh=False``, or a number of days, opts in to that cache. Its key ignores
keyword filters such as ``subj`` or ``date``, so a filter belongs in the query
string (see :func:`fetch_plan`).
"""

from __future__ import annotations

import json
import logging
import numbers
import os
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ._provenance import as_datetime, iso_utc
from ._pyb import UNDATED, cache_hit_time, cached_cell_warning, may_use_cache, require_init
from .plan import SearchPlan
from .query import _and_clause
from .records import (
    EXTENDED_COLUMNS,
    RECORD_COLUMNS,
    _check_fields,
    _join_authors,
    _record_columns,
    to_records,
)

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
#: is then exported as a real, wrong identifier. An ISSN such as "00368075"
#: would lose its leading zeros the same way. The bundled example CSV is read
#: with the same schema, for the same reason (see :mod:`scopusflow.data`).
_CHECKPOINT_TEXT = (
    "scopus_id", "doi", "title", "authors", "date", "publication", "query",
    "authkeywords", "doc_type", "doc_type_description", "source_type", "volume",
    "issue", "pages", "issn", "pubmed_id", "abstract",
)

#: The nullable-integer columns of a CSV checkpoint.
_CHECKPOINT_INTEGER = ("year", "citations", "open_access")


def _as_whole_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """``frame`` with its :data:`_CHECKPOINT_INTEGER` columns as ``Int64``.

    ``to_numeric`` comes first, so a column already promoted to float, by an
    earlier resume or by a reader that inferred it, still comes back as whole
    numbers.
    """
    for column in _CHECKPOINT_INTEGER:
        if column in frame.columns:
            frame[column] = pd.array(
                pd.to_numeric(frame[column], errors="coerce"), dtype="Int64"
            )
    return frame


def _read_csv_records(path) -> pd.DataFrame:
    """Read a record table from CSV with the record schema imposed.

    The text columns are named here and never inferred, and pandas ignores a
    dtype naming a column the file does not have, so a table written before
    ``authkeywords`` or the extended columns existed reads back as well.
    Checkpoints and :func:`scopusflow.io.read_records` both read CSV through
    this.
    """
    frame = pd.read_csv(path, dtype=dict.fromkeys(_CHECKPOINT_TEXT, "string"))
    return _as_whole_numbers(frame)


def _cell_query(query: str, year: int | None, date: str | None) -> str:
    """Fold the year filter into the query, since it travels with the search.

    Handles an explicit ``year``, a ``"YYYY-YYYY"`` range, a single ``"YYYY"``
    date and ``None`` (no year constraint). A query with a top-level OR, AND
    NOT or proximity operator is bracketed before the filter is appended (see
    :func:`scopusflow.query._and_clause`), so the filter applies to all of it.
    """
    if year is not None:
        return _and_clause(query, f"PUBYEAR IS {int(year)}")
    if date and "-" in date:
        lo, hi = date.split("-", 1)
        return _and_clause(
            query, f"PUBYEAR AFT {int(lo) - 1} AND PUBYEAR BEF {int(hi) + 1}"
        )
    if date:
        return _and_clause(query, f"PUBYEAR IS {int(date)}")
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

    A CSV is read with the record schema imposed, never inferred (see
    :func:`_read_csv_records`), so a resumed cell carries the same identifiers
    it was written with.

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
            frame = _read_csv_records(path)
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


def _with_joined_authors(frame: pd.DataFrame) -> pd.DataFrame:
    """``frame`` with its authors joined as :func:`to_records` now joins them.

    A COMPLETE checkpoint written before the join changed holds pybliometrics'
    bare ``";"``. Joining again is free and leaves a string already joined that
    way unchanged, so such a checkpoint is served without a refetch. The R
    twin, which used to read the first author alone, has to fetch its own
    again. A missing value stays missing, in the column's own dtype.
    """
    if "authors" not in frame.columns:
        return frame
    authors = frame["authors"]
    frame = frame.copy()
    frame["authors"] = authors.map(_join_authors, na_action="ignore").astype(authors.dtype)
    return frame


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


def _writable_cache(cache_dir) -> Path | None:
    """``cache_dir`` as a directory that checkpoints can be written to,
    created if need be, or ``None`` when no cache was asked for.

    Raises ``ValueError`` before any request when it is not a directory and
    cannot be created as one, or when no file can be created in it. A file in
    its place used to raise ``FileExistsError``, and a directory that could not
    be written spent each cell's requests before the checkpoint write failed
    and took the records with it. Creating a file is the test, as in the R
    twin. On Windows, ``os.access`` reports a directory that an ACL denies as
    writable, and ``tempfile.mkstemp`` can retry for over a minute before it
    gives up on one.
    """
    if not cache_dir:
        return None
    cache = Path(cache_dir)
    failure = None
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as error:  # judged by what the path holds, just below
        failure = error
    if not cache.is_dir():
        raise ValueError(
            "cache_dir must be a directory that can be written, and "
            f'"{cache}" is not a directory and could not be created as one. '
            "No request was made."
        ) from failure
    probe = cache / f"scopusflow-probe-{uuid.uuid4().hex}"
    try:
        with open(probe, "x"):
            pass
    except OSError as error:
        raise ValueError(
            "cache_dir must be a directory that can be written, and no file "
            f'could be created in "{cache}". No request was made.'
        ) from error
    try:
        probe.unlink()
    except OSError:  # a probe left behind is never read as a checkpoint
        pass
    return cache


def _unwritable_warning(what: str, cache: Path, held: str) -> str:
    """The warning for a checkpoint that could not be written, ``what`` naming
    the cell or identifier and ``held`` what the result keeps."""
    return (
        f"The checkpoint for {what} could not be written in {cache}, so {held} "
        "kept in the result without being saved to the cache."
    )


def _write_checkpoint(frame: pd.DataFrame, cache: Path, cell: int, fmt: str) -> Path:
    """Write ``frame`` for ``cell`` in ``fmt``, falling back to CSV if parquet
    has no available engine, and return the path written."""
    if fmt == "parquet":
        target = cache / f"cell-{cell:03d}.parquet"
        try:
            _atomic_write(frame.to_parquet, target)
            return target
        except Exception:  # parquet engine optional; fall back to CSV
            pass
    target = cache / f"cell-{cell:03d}.csv"
    _atomic_write(lambda path: frame.to_csv(path, index=False), target)
    return target


#: The layout version of a checkpoint manifest.
_MANIFEST_SCHEMA = 1

#: The paging mode of a checkpoint written without a manifest. Every version
#: of :func:`fetch_plan` before ``cursor`` existed paged by cursor, so such a
#: checkpoint is served to a cursor harvest and refetched for an offset one.
_LEGACY_PAGING = "cursor"

#: The manifest fields, all fixed by the plan, that say which search a
#: checkpoint answers. A checkpoint is served only when every one of them
#: matches the cell and its ``paging`` matches the mode the harvest asks for.
#: The mode is compared separately, since a checkpoint in the other mode was
#: written by the same plan and its warning says so.
_IDENTITY = ("query", "view", "page_size")


def _resolve_cursor(cursor, kwargs: dict) -> bool:
    """Whether a harvest pages by cursor, from ``cursor`` and any
    ``subscriber`` the caller passed, which is popped from ``kwargs``.

    ``subscriber`` is pybliometrics' documented name for the choice, and its
    ``cursor`` keyword an alias that overrides it, so :func:`fetch_plan` sends
    the result as ``subscriber`` alone. Either may be given, or both when they
    agree. Neither can then override the other unnoticed, as the
    ``cursor=True`` that fetch_plan() used to send overrode a caller's
    ``subscriber=False``. Given neither, a harvest pages by cursor, as
    fetch_plan() always has.
    """
    subscriber = kwargs.pop("subscriber", None)
    for name, value in (("cursor", cursor), ("subscriber", subscriber)):
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name} must be True or False.")
    if cursor is not None and subscriber is not None and cursor != subscriber:
        raise ValueError(
            f"cursor={cursor} and subscriber={subscriber} ask for different paging. "
            "Pass cursor alone: True pages by cursor and False by offset."
        )
    if cursor is None:
        return True if subscriber is None else subscriber
    return cursor


def _offset_refusal(cell, error: Exception) -> str:
    """The message for a cell that pybliometrics refused to page by offset.

    Its own message gives the number of matches but neither the cell nor the
    remedies a plan has, so both are added around it.
    """
    limit = cell.date if cell.date else "no year limit"
    return (
        f"Cell {cell.cell} ({limit}) cannot be retrieved under offset paging, which "
        f"stops at 5000 records per search. pybliometrics reported: {error} "
        "Partition the search so that each cell matches at most 5000 records, or "
        "pass cursor=True if the key is entitled to cursor paging."
    )


#: What :func:`_read_manifest` returns for a manifest it cannot use.
_UNREADABLE = object()


def _manifest_path(cache: Path, cell: int) -> Path:
    return cache / f"cell-{cell:03d}.json"


def _read_manifest(path: Path):
    """The manifest at ``path`` as a dict, ``None`` when there is none, or
    :data:`_UNREADABLE` when it cannot be read as a manifest this version
    writes."""
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # the caller warns and refetches the cell
        return _UNREADABLE
    if not isinstance(manifest, dict) or manifest.get("schema") != _MANIFEST_SCHEMA:
        return _UNREADABLE
    return manifest


def _manifest_mismatch(manifest: dict, identity: dict) -> str | None:
    """How ``manifest`` differs from the request ``identity`` describes, as
    text for a warning, or ``None`` when it answers that request."""
    for key in _IDENTITY:
        if manifest.get(key) != identity[key]:
            return f"{key} {manifest.get(key)!r}, not {identity[key]!r}"
    return None


def _rows_mismatch(cached: pd.DataFrame, query: str, view: str) -> str | None:
    """How a checkpoint without a manifest differs from the cell, judged by
    what its rows recorded, or ``None`` when nothing betrays a difference.

    The rows carry the query they were fetched with. The view is compared too,
    since the query alone cannot tell a STANDARD plan from a COMPLETE one, and a
    COMPLETE-written checkpoint would hand a STANDARD resume an
    ``authkeywords`` column the documentation promises it never carries. An
    empty checkpoint has no rows to judge by, so :func:`fetch_plan` refetches
    it before asking.
    """
    queries = set(cached["query"].dropna().unique()) if "query" in cached.columns else set()
    if queries and queries != {query}:
        return f"query {sorted(queries)!r}, not {query!r}"
    recorded_view = _checkpoint_view(cached)
    if recorded_view is not None and recorded_view != view:
        return f"view {recorded_view!r}, not {view!r}"
    return None


def _lacks_requested_columns(cached: pd.DataFrame, view: str, fields: str) -> bool:
    """Whether a checkpoint lacks a column the harvest asks for.

    Only ``fields="extended"`` asks for more than every checkpoint holds. A
    checkpoint is judged by its columns, which a checkpoint written by an
    earlier version, with no manifest or one that names no fields, carries as
    well as a new one.
    """
    if fields != "extended":
        return False
    wanted = [*EXTENDED_COLUMNS, *(["abstract"] if view == "COMPLETE" else [])]
    return not set(wanted).issubset(cached.columns)


def _manifest_stamp(manifest: dict) -> datetime | None:
    """The retrieval time a manifest records, or ``None`` when it records none
    that can be read as an instant."""
    try:
        stamp = as_datetime(manifest.get("retrieved_at"))
    except ValueError:
        return None
    if stamp is None or stamp.tzinfo is None:
        return None
    return stamp


def _legacy_empty_warning(cells: list[int], cache: Path) -> str:
    """The one warning a harvest gives for the manifest-less empty checkpoints
    it refetched."""
    listed = ", ".join(str(c) for c in cells)
    if len(cells) == 1:
        head = (f"1 empty checkpoint in {cache} (cell {listed}) has no manifest to "
                "say which search wrote it, so that cell was fetched again.")
    else:
        head = (f"{len(cells)} empty checkpoints in {cache} (cells {listed}) have no "
                "manifest to say which search wrote them, so those cells were "
                "fetched again.")
    return head + " Checkpoints written by earlier versions of scopusflow have none."


def fetch_plan(
    plan: SearchPlan,
    cache_dir: str | None = None,
    resume: bool = True,
    format: str = "parquet",
    should_stop=None,
    *,
    cursor: bool | None = None,
    fields: str = "core",
    **kwargs,
) -> pd.DataFrame:
    """Run every cell of ``plan`` and return one normalised DataFrame.

    With ``cache_dir`` set, each cell is written to disk as it completes, so an
    interrupted or quota-limited run resumes without re-fetching finished cells.
    A cache_dir belongs to one plan. Checkpoints are keyed by cell number, and
    each is written with a manifest beside it, ``cell-NNN.json``, recording
    the query as sent, the view, the page size and the paging mode, with the
    cell's row count, reported total, retrieval time and scopusflow version.
    On resume a checkpoint is served only when its manifest's query, view,
    page size and paging match the cell's, an empty checkpoint included. The
    query and view its rows record must match as well, and it must hold as
    many rows as the manifest records, so a checkpoint replaced while its
    manifest was left in place is not served under the old manifest. One
    written by a different plan is warned about and refetched, never silently
    returned. Point each plan at its own directory all the same, since that
    refetch spends quota. A checkpoint without a manifest, as earlier versions
    wrote them, is judged by the query and view its rows record, and an empty
    one, whose rows record nothing, is refetched at one request each, with a
    single warning for the harvest. A manifest without its checkpoint is
    ignored. A checkpoint that cannot be read back is likewise treated as a
    miss, warned about and refetched, and the harvest carries on. A
    ``cache_dir`` that is not a directory and cannot be created as one, or in
    which no file can be created, raises ``ValueError`` before any request. A
    checkpoint or manifest that cannot be written all the same, for example on
    a full disk, is warned about, and the cell's records are kept in the
    result without a checkpoint.
    ``format`` selects the checkpoint format ("parquet" or "csv"); parquet
    silently falls back to CSV when no parquet engine is installed. Pass a
    zero-argument ``should_stop`` callable to allow co-operative cancellation: it
    is checked before each cell and the harvest stops (returning what it has) when
    it returns ``True``. A harvest stopped that way records
    ``attrs["stopped_early"] = True``, with the number of cells the plan holds as
    ``attrs["cells_planned"]`` and the number that ran as ``attrs["cells_run"]``.
    Its ``total_results`` is ``None``, since the cells it never reached were
    never counted. :func:`scopusflow.report.scopus_search_report` then says how
    many cells ran, which years they covered and that the harvest is incomplete.
    A harvest that ran every cell carries none of the three. Per-cell progress is
    emitted on the ``"scopusflow"`` logger.

    ``cursor`` chooses how each cell is paged. Left unset, or ``True``, it
    pages by cursor, which retrieves a cell of any size and is the paging
    fetch_plan() has always used. ``False`` pages by offset, the route
    pybliometrics documents for keys without a Scopus subscription. Offset
    paging cannot retrieve a cell that matches more than 5000 records.
    pybliometrics refuses such a cell after one request, and the
    ``ScopusQueryError`` it raises is raised again naming the cell, so the
    search has to be partitioned more finely. pybliometrics' own
    ``subscriber`` keyword is taken as the same choice, and passing both with
    different values raises ``ValueError`` before any request. The manifest
    records the mode, so a checkpoint fetched under one mode is warned about
    and refetched when the other is asked for. A checkpoint without a manifest
    counts as paged by cursor, since every earlier version paged that way.
    ``attrs["paging"]`` is ``"cursor"`` or ``"offset"`` accordingly. The R
    twin's ``scopus_fetch_plan()`` pages by offset unless given
    ``cursor = TRUE``, the paging its plans have always used.

    ``fields`` is ``"core"`` by default. ``"extended"`` also keeps the document
    type, source type, volume, issue, pages, ISSN, PubMed identifier and
    open-access status the Search API sends with every record, and the abstract
    under a ``COMPLETE`` plan (see :func:`scopusflow.records.to_records`). They
    arrive in the responses each cell already pays for, so they cost no extra
    quota. Like ``cursor``, it is an argument of the harvest, since it changes
    how the records are read while the search returns the same records. Each
    manifest records the fields its checkpoint was fetched with. A checkpoint
    that lacks a column an extended harvest asks for is warned about and
    refetched, one written by an earlier version included. An extended
    checkpoint serves a core harvest with the extended columns dropped. Any
    value other than ``"core"`` or ``"extended"`` raises ``ValueError`` before
    any request.

    Each cell's row count is compared against the total the API reports for
    that cell's query, and a shortfall is warned about, since a truncated or
    failed download otherwise arrives as a merely small result. The per-cell
    accounting is attached as ``result.attrs["cell_totals"]``, a list of dicts
    with the keys ``cell``, ``date``, ``n_records`` and ``reported_total``
    (``pandas.DataFrame(result.attrs["cell_totals"])`` tabulates it), and their sum as
    ``result.attrs["total_results"]``, the attribute the R twin's
    ``scopus_fetch()`` also attaches. The sum is ``None`` unless every cell
    reported a total, since a partial sum would understate the search while
    looking like a real figure. A cell resumed from a checkpoint reports the
    total its manifest recorded, and one resumed from a checkpoint without a
    manifest reports none.

    Every cell is fetched with ``refresh=True`` unless you pass ``refresh``
    yourself, so a run spends quota on each cell it does not resume from a
    checkpoint. pybliometrics would otherwise answer from its own response
    cache, keyed on the query string and view alone. A re-run into a fresh
    ``cache_dir`` would then receive the earlier pull, dated now, with the
    cached row count standing in for the API's total. ``refresh=False``, or a
    number of days, opts in to that cache, and a cell it serves is dated by its
    cache file, reports no total and is warned about. The cache key ignores
    keyword arguments such as ``subj`` or ``date``, so a filtered search would
    be served the unfiltered one's records. Fold any filter into the query
    before you opt in.

    The harvest also carries its provenance: the originating ``plan``, as the
    dict :meth:`SearchPlan.to_dict` writes (:meth:`SearchPlan.from_dict`
    rebuilds the plan), ``retrieved_at`` and ``retrieved_until``, as ISO 8601
    text in UTC to the second (``"2026-07-22T09:15:00+00:00"``),
    ``scopusflow_version`` and ``paging``. These are what
    :func:`scopusflow.report.scopus_search_report` reads back. They are
    combined over the cells as the R twin combines them. ``retrieved_at`` is
    the earliest cell's time, since a set is only as fresh as its oldest cell.
    ``retrieved_until`` is the latest, the last search, which the record of a
    harvest resumed over several days gives for PRISMA-S item 13. The version
    is a sorted list when cells resumed from an earlier release's checkpoints
    make more than one. A resumed cell contributes the time and version its
    manifest recorded. Each attribute is omitted, never approximated, when any
    cell cannot supply it, as a cell resumed from a checkpoint without a
    manifest cannot, since dating the whole from the cells that can be dated
    would date it later than part of what it holds.

    Every attribute is a value ``json.dumps`` writes, so the harvest can be
    saved with ``DataFrame.to_parquet`` and passed through ``merge``,
    ``groupby(...).apply`` and ``concat``. :func:`scopusflow.io.write_records`
    saves it with its provenance whatever the pandas version.

    ``attrs["view"]`` records the plan's view, which decides what ``authors``
    holds: the first author under ``STANDARD`` and the author list under
    ``COMPLETE`` (see :func:`scopusflow.records.to_records`), and
    :func:`scopusflow.records.top` reads it back. A cell resumed from a
    checkpoint written before the authors were joined with ``"; "`` has them
    joined as it is served, so it costs no request.

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

    Raises :class:`scopusflow.exceptions.ScopusFlowConfigError` before any
    request when ``pybliometrics.init()`` has not been called in the session.
    A cell served from its checkpoint sends no request, so a harvest resumed
    wholly from checkpoints runs without ``init()``.
    """
    if not isinstance(plan, SearchPlan):
        raise ValueError("plan must be a SearchPlan.")
    if format not in _FORMATS:
        raise ValueError("format must be 'parquet' or 'csv'.")
    cursor = _resolve_cursor(cursor, kwargs)
    paging = "cursor" if cursor else "offset"
    _check_fields(fields)

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    # Only offset paging meets pybliometrics' size refusal, so only then is its
    # error caught and given the cell. The import is guarded, since a
    # pybliometrics without this module, or a stand-in such as the offline
    # tests install, should still run a harvest, its errors passing unchanged.
    # An empty tuple in an except clause catches nothing.
    refusals: tuple[type[BaseException], ...] = ()
    if not cursor:
        try:
            from pybliometrics.exception import ScopusQueryError
        except ImportError:
            pass
        else:
            refusals = (ScopusQueryError,)

    cache = _writable_cache(cache_dir)

    # setdefault, so a caller who passes refresh, opting in to pybliometrics'
    # cache, still wins. Only then can an answer come from that cache, so only
    # then is each answer checked.
    kwargs.setdefault("refresh", True)
    check_cache = may_use_cache(kwargs["refresh"])

    # Imported inside the function, and never at module scope: this module is
    # imported while the package's own __init__ is still executing, and
    # __version__ is not bound until after that import returns.
    from . import __version__

    cells = plan.cells()
    total = len(cells)
    frames: list[pd.DataFrame] = []
    accounting: list[dict] = []
    stamps: list[datetime | None] = []
    versions: list[str | None] = []
    legacy_empty: list[int] = []
    stopped = False
    for cell in cells:
        if should_stop is not None and should_stop():
            logger.info("Stopped before cell %d/%d.", cell.cell, total)
            stopped = True
            break

        query = _cell_query(cell.query, cell.year, cell.date)
        # What the cell's request is made of, as its manifest records it. The
        # page size is the one that will be sent, which a caller's own count
        # overrides (see below). A count given as a NumPy integer is stored as
        # a plain one, which json.dumps can write.
        page_size = kwargs.get("count", cell.page_size)
        if isinstance(page_size, numbers.Integral) and not isinstance(page_size, bool):
            page_size = int(page_size)
        identity = {"query": query, "view": cell.view, "page_size": page_size,
                    "paging": paging, "fields": fields}
        if cache is not None and resume:
            existing = _find_checkpoint(cache, cell.cell)
            cached = _read_checkpoint(existing) if existing is not None else None
            manifest = (_read_manifest(_manifest_path(cache, cell.cell))
                        if cached is not None else None)
            if existing is not None and cached is None:
                warnings.warn(
                    f"The checkpoint {existing} could not be read back, so it "
                    "was discarded and the cell refetched. An interrupted run "
                    "can leave a checkpoint half-written.",
                    stacklevel=2,
                )
            elif manifest is _UNREADABLE:
                warnings.warn(
                    f"The manifest beside the checkpoint {existing} could not be "
                    "read back, so the cell was refetched.",
                    stacklevel=2,
                )
            elif cached is not None and manifest is None and len(cached) == 0:
                # Without a manifest an empty checkpoint has nothing to say
                # which search wrote it, since its rows carry no query, so it
                # would be served to any plan pointed at this directory. It
                # costs one request, and the harvest warns once for all such
                # cells after the loop.
                legacy_empty.append(cell.cell)
            elif cached is not None:
                # Checkpoints are keyed by cell number alone, so a cache_dir
                # reused for a different plan would otherwise hand back the
                # wrong records silently. The rows record the query and view
                # they were fetched with, and the manifest the whole request,
                # so both are compared, as the R twin compares both. A
                # checkpoint without a manifest, written before manifests
                # existed or by a run stopped between the two writes, is judged
                # by its rows alone. The row count ties a manifest to its own
                # checkpoint: an earlier version replacing the checkpoint
                # leaves the manifest in place, and an empty replacement has no
                # rows to betray it. A checkpoint without a manifest was paged
                # by cursor, the only mode earlier versions used.
                mismatch = _rows_mismatch(cached, query, cell.view)
                if mismatch is None and manifest is not None:
                    mismatch = _manifest_mismatch(manifest, identity)
                recorded = _LEGACY_PAGING if manifest is None else manifest.get("paging")
                # Every version that writes manifests records the mode in
                # them, so a manifest naming none is treated as another plan's.
                if mismatch is None and not isinstance(recorded, str):
                    mismatch = f"paging {recorded!r}, not {paging!r}"
                if mismatch is not None:
                    warnings.warn(
                        f"Checkpoint for cell {cell.cell} in {cache} was written "
                        f"by a different plan ({mismatch}); refetching this cell. "
                        "Use one cache_dir per plan.",
                        stacklevel=2,
                    )
                elif recorded != paging:
                    # This plan wrote the checkpoint under the other mode,
                    # which a harvest switching modes meets in every cell, so
                    # the warning names both modes and gives no advice about
                    # cache directories.
                    if manifest is not None:
                        text = (f"The checkpoint {existing} was fetched under "
                                f"{recorded} paging, not the {paging} paging asked "
                                "for, so it was discarded and the cell refetched.")
                    else:
                        text = (f"The checkpoint {existing} has no manifest, so it "
                                f"counts as fetched under {recorded} paging, the "
                                "only mode earlier versions used, and the cell was "
                                f"refetched under the {paging} paging asked for.")
                    warnings.warn(text, stacklevel=2)
                elif manifest is not None and manifest.get("n_records") != len(cached):
                    warnings.warn(
                        f"The checkpoint {existing} holds {len(cached)} record(s), "
                        f"but the manifest beside it records "
                        f"{manifest.get('n_records')!r}, so the two were not "
                        "written together and the cell was refetched.",
                        stacklevel=2,
                    )
                elif _lacks_requested_columns(cached, cell.view, fields):
                    # This plan wrote the checkpoint with the core fields, so
                    # the warning gives no advice about cache directories.
                    warnings.warn(
                        f"The checkpoint {existing} was fetched with the core "
                        "fields, not the extended fields asked for, so it was "
                        "discarded and the cell refetched.",
                        stacklevel=2,
                    )
                else:
                    logger.info("Cell %d/%d: loaded from cache.", cell.cell, total)
                    dropped = ["view"]
                    if fields == "core":
                        # Served from an extended checkpoint, a core harvest
                        # holds what a core fetch returns.
                        dropped += [*EXTENDED_COLUMNS, "abstract"]
                    served = _with_joined_authors(
                        cached.drop(columns=dropped, errors="ignore")
                    )
                    frames.append(served)
                    # A manifest restores the cell's total, time and version. A
                    # checkpoint without one has no record of them, and they
                    # are left out, never guessed.
                    provenance = manifest or {}
                    reported = provenance.get("reported_total")
                    version = provenance.get("scopusflow_version")
                    accounting.append({
                        "cell": cell.cell, "date": cell.date,
                        "n_records": len(served),
                        "reported_total": (reported if isinstance(reported, int)
                                           and not isinstance(reported, bool) else None),
                    })
                    stamps.append(_manifest_stamp(provenance))
                    versions.append(version if isinstance(version, str) else None)
                    continue

        logger.info("Cell %d/%d: fetching %s", cell.cell, total, query)
        # The page size is the plan's, so the harvest pages the way the plan (and
        # the search record built from it) says it does. setdefault, so a caller
        # passing count of their own still wins.
        kwargs.setdefault("count", cell.page_size)
        # Checked before each request, so a harvest resumed wholly from
        # checkpoints, which sends none, still runs in a fresh session that
        # has not called init().
        require_init()
        t0 = time.time()
        try:
            search = ScopusSearch(query, view=cell.view, subscriber=cursor, **kwargs)
        except refusals as error:
            raise type(error)(_offset_refusal(cell, error)) from error
        frame = to_records(search.results, query=query, view=cell.view, fields=fields)

        cached_at = cache_hit_time(search, t0) if check_cache else None
        if cached_at is None:
            # A download that returned nothing yields a zero-row frame and never
            # an error, so without this comparison a truncated or failed cell is
            # indistinguishable from one that matched only a few records.
            cell_total = _reported_total(search)
            stamp = datetime.now(timezone.utc)
        else:
            # A cached answer gives its own row count as the total, so any
            # shortfall would vanish, and its rows date from when the cache
            # file was written.
            warnings.warn(cached_cell_warning(cell.cell, cached_at), stacklevel=2)
            cell_total = None
            stamp = None if cached_at is UNDATED else cached_at
        accounting.append({"cell": cell.cell, "date": cell.date,
                           "n_records": len(frame), "reported_total": cell_total})
        stamps.append(stamp)
        versions.append(__version__)
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
            # The order keeps a checkpoint from ever being paired with a
            # manifest that describes another. The old manifest goes first, so
            # a run stopped before the new one is written leaves a checkpoint
            # without a manifest, which resume treats as written by an earlier
            # version. The new checkpoint replaces any of the other format,
            # which would otherwise be found beside the new manifest. A write
            # that fails, on a full disk or where a directory has taken a
            # checkpoint's name, is warned about, and the records the cell
            # paid for are kept in the result. The error used to lose them.
            manifest_path = _manifest_path(cache, cell.cell)
            written = None
            try:
                manifest_path.unlink(missing_ok=True)
                # The view also travels in a column of the checkpoint (stripped
                # again on resume), so an earlier version reading it can still
                # tell the views apart.
                written = _write_checkpoint(frame.assign(view=cell.view), cache,
                                            cell.cell, format)
                for suffix in (".parquet", ".csv"):
                    sibling = written.with_suffix(suffix)
                    if sibling != written:
                        sibling.unlink(missing_ok=True)
                written_manifest = {
                    "schema": _MANIFEST_SCHEMA,
                    **identity,
                    "n_records": len(frame),
                    "reported_total": cell_total,
                    "retrieved_at": None if stamp is None else iso_utc(stamp),
                    "scopusflow_version": __version__,
                }
                _atomic_write(
                    lambda path, m=written_manifest: path.write_text(
                        json.dumps(m, indent=2) + "\n", encoding="utf-8"
                    ),
                    manifest_path,
                )
            except OSError:
                # A checkpoint whose manifest could not follow it is removed
                # as well, so the warning holds and resume never meets it.
                if written is not None:
                    try:
                        written.unlink(missing_ok=True)
                    except OSError:
                        pass
                warnings.warn(
                    _unwritable_warning(f"cell {cell.cell}", cache, "its records are"),
                    stacklevel=2,
                )
        frames.append(frame)

    if legacy_empty:
        warnings.warn(_legacy_empty_warning(legacy_empty, cache), stacklevel=2)

    if not frames:
        out = pd.DataFrame(columns=_record_columns(plan.view, fields))
    else:
        out = pd.concat(frames, ignore_index=True)
        out["entry_number"] = range(1, len(out) + 1)
        logger.info("Retrieved %d records.", len(out))

    # The plan travels with its own harvest, as it does in the R twin, so the
    # search record can be written from the records alone. Every attribute is
    # held in a form json.dumps writes: pandas 2.1 and later write attrs as JSON
    # when a frame is saved to parquet, and pandas compares the inputs' attrs in
    # merge, groupby-apply and concat, where a DataFrame held there raised.
    out.attrs["plan"] = plan.to_dict()
    out.attrs["cell_totals"] = accounting
    reported = [row["reported_total"] for row in accounting]
    out.attrs["total_results"] = (
        sum(reported) if accounting and all(n is not None for n in reported) else None
    )
    if stopped:
        # A stopped harvest says so, and how far it got. It claims no total
        # even when every cell that ran reported one, since that sum would
        # stand for the whole search while leaving out the cells never reached.
        out.attrs["total_results"] = None
        out.attrs["stopped_early"] = True
        out.attrs["cells_planned"] = total
        out.attrs["cells_run"] = len(accounting)
    # True of every cell: a checkpoint is served only to a harvest in its own
    # paging mode, and one without a manifest only to a cursor harvest.
    out.attrs["paging"] = paging
    # The view decides whether authors are first authors or author lists, so
    # top() can say what a tally by author counts, as the R twin does.
    out.attrs["view"] = plan.view
    # Combined as the R twin combines its cells. The earliest time is kept,
    # since a set is only as fresh as its oldest cell, and so is the latest,
    # the last search, which PRISMA-S item 13 asks for. Every version that
    # built a cell is listed, since a cache written by an earlier release means
    # more than one did. Each is claimed only when every cell supplies it:
    # dating the set from the cells that can be dated would date it later than
    # part of what it holds.
    if stamps and all(s is not None for s in stamps):
        out.attrs["retrieved_at"] = iso_utc(min(stamps))
        out.attrs["retrieved_until"] = iso_utc(max(stamps))
    if versions and all(v is not None for v in versions):
        distinct = sorted(set(versions))
        out.attrs["scopusflow_version"] = distinct[0] if len(distinct) == 1 else distinct
    return out
