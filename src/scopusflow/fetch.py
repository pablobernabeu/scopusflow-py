"""Execute a search plan with resumable, checkpointed retrieval.

This is the workflow layer's reason to exist: it drives ``pybliometrics`` (which
handles the HTTP, cursor pagination, quota rotation and per-query caching) but
adds a project-level, resumable harvest with per-cell checkpoints and a single
normalised output frame. The exact ``ScopusSearch`` call is intentionally thin;
confirm the keyword arguments against your installed pybliometrics version.
"""

from __future__ import annotations

import logging
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


def _read_checkpoint(path: Path) -> pd.DataFrame:
    """Read a checkpoint back, dispatching on its extension."""
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def _write_checkpoint(frame: pd.DataFrame, cache: Path, cell: int, fmt: str) -> None:
    """Write ``frame`` for ``cell`` in ``fmt``, falling back to CSV if parquet
    has no available engine."""
    if fmt == "parquet":
        target = cache / f"cell-{cell:03d}.parquet"
        try:
            frame.to_parquet(target)
            return
        except Exception:  # parquet engine optional; fall back to CSV
            pass
    frame.to_csv(cache / f"cell-{cell:03d}.csv", index=False)


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
    ``format`` selects the checkpoint format ("parquet" or "csv"); parquet
    silently falls back to CSV when no parquet engine is installed. Pass a
    zero-argument ``should_stop`` callable to allow co-operative cancellation: it
    is checked before each cell and the harvest stops (returning what it has) when
    it returns ``True``. Per-cell progress is emitted on the ``"scopusflow"``
    logger.

    When ``plan.view == "COMPLETE"``, the output gains an ``authkeywords``
    column (see :func:`scopusflow.records.to_records`) at no extra request cost
    beyond ``COMPLETE``'s own smaller page size, which already means more
    requests, and so more quota, for the same number of records. A plan with
    ``view="STANDARD"`` (the default) never carries this column, so existing
    code is unaffected. Resuming a cache written before this column existed is
    safe: ``pandas.concat`` fills the older cells' missing column with
    ``NA`` rather than erroring.
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
    for cell in cells:
        if should_stop is not None and should_stop():
            logger.info("Stopped before cell %d/%d.", cell.cell, total)
            break

        if cache is not None and resume:
            existing = _find_checkpoint(cache, cell.cell)
            if existing is not None:
                logger.info("Cell %d/%d: loaded from cache.", cell.cell, total)
                frames.append(_read_checkpoint(existing))
                continue

        query = _cell_query(cell.query, cell.year, cell.date)
        logger.info("Cell %d/%d: fetching %s", cell.cell, total, query)
        search = ScopusSearch(query, view=cell.view, cursor=True, **kwargs)
        frame = to_records(search.results, query=query, view=cell.view)

        if cache is not None:
            _write_checkpoint(frame, cache, cell.cell, format)
        frames.append(frame)

    if not frames:
        columns = [*RECORD_COLUMNS, "authkeywords"] if plan.view == "COMPLETE" else RECORD_COLUMNS
        return pd.DataFrame(columns=columns)
    out = pd.concat(frames, ignore_index=True)
    out["entry_number"] = range(1, len(out) + 1)
    logger.info("Retrieved %d records.", len(out))
    return out
