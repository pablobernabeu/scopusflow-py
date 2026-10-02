"""Where a pybliometrics search got its answer: the API, or pybliometrics' cache.

pybliometrics keeps an on-disk response cache of its own, apart from the
checkpoints scopusflow writes. It files every search under
``{dir}/{view}/md5(query)``, so nothing else that shapes the request (``subj``,
``date``, ``sort``) enters the key. Unless ``refresh`` is True, it answers from
an existing file without contacting the API and gives the number of cached rows
as the result size. scopusflow therefore sends ``refresh=True`` unless the
caller sends ``refresh``. When a caller does opt in to the cache, the helpers
here tell a cached answer from a fresh one, so that it can be dated by its file
and flagged.

Only public methods of the search object are read. Its private ``_mdate`` and
``_header`` would say the same more directly, but they are pybliometrics'
internals and may change in any release.
"""

from __future__ import annotations

import math
import warnings
from datetime import datetime, timezone

from .report import _stamp

#: How ``get_cache_file_mdate()`` renders a cache file's modification time:
#: local time, to the second.
_MDATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _Undated:
    def __repr__(self) -> str:
        return "UNDATED"


#: What :func:`cache_hit_time` returns for an answer that may have come from
#: pybliometrics' cache but whose cache time cannot be read.
UNDATED = _Undated()


def may_use_cache(refresh) -> bool:
    """Whether pybliometrics may answer from its cache under this ``refresh``.

    Only ``True`` rules the cache out. ``False`` reads any existing file, and a
    number reads one younger than that many days. pybliometrics tells the two
    apart by type, so ``1`` counts as a number of days.
    """
    return refresh is not True


def _file_time(search):
    """The earliest and latest UTC instants the cache file's time can stand
    for, ``None`` without the getter, or :data:`UNDATED` when it cannot be
    read."""
    getter = getattr(search, "get_cache_file_mdate", None)
    if not callable(getter):
        return None
    try:
        local = datetime.strptime(getter(), _MDATE_FORMAT)
        # astimezone() reads a naive datetime as local time. In the hour the
        # clocks repeat when they go back, one rendering stands for two
        # instants and fold chooses between them. Elsewhere, the two readings
        # agree.
        readings = sorted(local.replace(fold=f).astimezone(timezone.utc) for f in (0, 1))
    except Exception:  # an unexpected rendering must never pass for a fresh answer
        return UNDATED
    return readings[0], readings[-1]


def _kept_no_headers(search) -> bool | None:
    """Whether pybliometrics kept no response headers for ``search``, as it
    does only for an answer read from its cache. ``None`` when that cannot be
    told."""
    getter = getattr(search, "get_key_remaining_quota", None)
    if not callable(getter):
        return None
    try:
        return getter() is None
    except KeyError:  # the headers were kept, without the rate-limit field
        return False
    except Exception:  # a diagnostic must never sink the search it describes
        return None


def cache_hit_time(search, t0: float):
    """When pybliometrics answered ``search`` from its cache, the time the
    cache file was written, as an aware UTC datetime.

    ``t0`` is ``time.time()`` taken just before the search object was built.
    Returns ``None`` for an answer fetched from the API, and for an object
    exposing neither getter, such as a test double. Returns :data:`UNDATED`
    when the answer may have come from the cache but its time cannot be read,
    so the caller records neither a total nor a time.

    Either of two signs marks a cached answer. pybliometrics keeps no response
    headers for an answer read from disk, so its ``get_key_remaining_quota()``
    returns ``None``, where a fresh response gives the remaining quota or
    raises ``KeyError`` for a missing header. The other sign is a cache file
    written before the search began, which cannot hold this search's answer.
    The file's time has whole seconds only, so it is compared with
    ``floor(t0)``, which a fresh response can never precede. A file written
    within that same second is caught by the headers alone. In the hour the
    clocks repeat, the later reading of the time decides, so a fresh answer is
    never taken for an hour-old file. A hit is dated by the earlier reading, so
    a record never claims a fresher search than it ran.
    """
    written = _file_time(search)
    no_headers = _kept_no_headers(search)
    if written is None and no_headers is None:
        return None
    if written is UNDATED or (written is None and no_headers):
        return UNDATED
    if written is None:
        return None
    earliest, latest = written
    if no_headers or latest.timestamp() < math.floor(t0):
        return earliest
    return None


def cached_cell_warning(cell: int, written) -> str:
    """The warning for a harvest cell that pybliometrics answered from its cache."""
    if written is UNDATED:
        return (
            f"Cell {cell} may have been served from pybliometrics' own cache, whose "
            "file time could not be read. It is left undated and without a reported "
            "total. Pass refresh=True (the default) to fetch it from the API."
        )
    return (
        f"Cell {cell} was served from pybliometrics' own cache, written "
        f"{_stamp(written)}, without a request to the API, so it is dated by that "
        "file and has no reported total. Pass refresh=True (the default) to fetch "
        "it from the API."
    )


def result_size(search, t0: float, refresh, query: str, stacklevel: int) -> int:
    """``search.get_results_size()``, with a warning when pybliometrics' cache
    may have supplied it.

    A count read from the cache is the number of rows that an earlier download
    of the same query string left there. ``stacklevel`` is the one the caller
    would give a warning of its own.
    """
    n = int(search.get_results_size())
    if may_use_cache(refresh):
        written = cache_hit_time(search, t0)
        if written is UNDATED:
            warnings.warn(
                f"The count for {query!r} may be the number of records in "
                "pybliometrics' own cache for that query, whose time could not be "
                "read, and not the API's total. Pass refresh=True (the default) to "
                "ask the API.",
                stacklevel=stacklevel + 1,
            )
        elif written is not None:
            warnings.warn(
                f"The count for {query!r} is the number of records in "
                f"pybliometrics' own cache for that query, written {_stamp(written)}, "
                "not the API's total. Pass refresh=True (the default) to ask the API.",
                stacklevel=stacklevel + 1,
            )
    return n
