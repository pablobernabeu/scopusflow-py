"""Batch abstract retrieval, resilient per id."""

from __future__ import annotations

import logging
import numbers
import pickle
import time
import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from ._pyb import UNDATED, _kept_no_headers, cache_hit_time, may_use_cache, require_init
from .exceptions import ScopusFlowForbiddenError
from .fetch import _atomic_write
from .records import _citations, _scopus_id

#: Per-identifier progress is emitted on this logger; see fetch.py.
logger = logging.getLogger("scopusflow")

#: The stable column schema for retrieved abstracts.
ABSTRACT_COLUMNS = [
    "scopus_id", "doi", "title", "abstract",
    "publication", "date", "year", "citations",
]

#: Map the user-facing ``by`` argument to a pybliometrics ``id_type``.
_ID_TYPES = {"doi": "doi", "eid": "eid", "scopus_id": "scopus_id"}

#: Values accepted by ``include``.
_KNOWN_INCLUDE = {"references", "keywords"}

#: Abstract Retrieval views that carry a bibliography.
_VIEWS_WITH_REFERENCES = {"FULL", "REF"}

#: The prefix Scopus' own ``dc:identifier`` puts before a Scopus ID.
_SCOPUS_ID_PREFIX = "SCOPUS_ID:"

#: How many offending positions an error message lists before summarising.
_POSITIONS_SHOWN = 10


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _is_whole_number(value) -> bool:
    # bool is an Integral too, but True is no identifier.
    return isinstance(value, numbers.Integral) and not isinstance(value, (bool, np.bool_))


def _is_missing_identifier(value) -> bool:
    """Whether ``value`` stands for no identifier: ``None``, a pandas or NumPy
    missing value, or a string with nothing but whitespace."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):  # a container, which is no identifier either
        return False


def _positions(positions: list[int]) -> str:
    shown = ", ".join(str(p) for p in positions[:_POSITIONS_SHOWN])
    more = len(positions) - _POSITIONS_SHOWN
    word = "position" if len(positions) == 1 else "positions"
    return f"{word} {shown}" + (f" and {more} more" if more > 0 else "")


def _clean_ids(ids, by: str) -> list[str]:
    """Check ``ids`` before any request and return them as clean strings.

    Mirrors the R twin's checks (``scopus_abstract()`` in R/abstract.R). A
    missing identifier would otherwise reach pybliometrics, which requests
    ``None`` as the DOI "None", and with ``cache_dir`` it stopped the batch
    part-way on every resume. Whitespace is trimmed, the ``SCOPUS_ID:`` prefix
    is dropped when ``by="scopus_id"``, and whole numbers, the form a numeric
    column of Scopus IDs takes, are written as text.
    """
    if isinstance(ids, str) or _is_whole_number(ids):
        ids = [ids]
    elif isinstance(ids, (bytes, bytearray, memoryview)):
        # A bytes object is a Sequence of whole numbers, so it would otherwise
        # pass as one identifier per byte, each sent as its own request.
        raise TypeError(
            f"ids must be text, not {type(ids).__name__}. Decode it first."
        )
    elif isinstance(ids, (pd.Series, pd.Index, np.ndarray, Sequence)):
        ids = list(ids)
    else:
        raise TypeError(
            "ids must be one identifier, or a list, tuple or pandas Series of "
            f"identifiers, not {type(ids).__name__}."
        )

    clean, missing, wrong = [], [], []
    for position, value in enumerate(ids):
        if isinstance(value, str):
            text = value.strip()
        elif _is_whole_number(value):
            text = str(int(value))
        elif _is_missing_identifier(value):
            missing.append(position)
            continue
        else:
            wrong.append(position)
            continue
        if by == "scopus_id" and text.startswith(_SCOPUS_ID_PREFIX):
            text = text[len(_SCOPUS_ID_PREFIX):].strip()
        if not text:
            missing.append(position)
            continue
        clean.append(text)

    if wrong:
        raise TypeError(
            f"ids holds a value that is neither text nor a whole number at "
            f"{_positions(wrong)} (counting from 0). A float is refused even "
            "when it is whole, so convert a column of Scopus IDs read as floats "
            "to text or to integers first."
        )
    if missing:
        raise ValueError(
            f"ids holds a missing or blank identifier at {_positions(missing)} "
            "(counting from 0). Drop those records before calling "
            "scopus_abstract(), or call corpus(), which drops records without an "
            "identifier and says how many it dropped."
        )
    return clean


def _references_frame(refs) -> pd.DataFrame:
    """Normalise pybliometrics' own ``Reference`` namedtuples into a DataFrame,
    one row per cited work, keeping pybliometrics' full native field set."""
    from pybliometrics.scopus import Reference

    if not refs:
        return pd.DataFrame(columns=list(Reference._fields))
    return pd.DataFrame([r._asdict() for r in refs])


def _keywords(obj, ident: str | None) -> str | object:
    """The author keywords joined with "; ", or ``NA``.

    pybliometrics 4.4.1 raises ``KeyError: '$'`` when Scopus sends an
    author-keyword entry that holds only its attribute (pybliometrics issue
    436). The keywords are then left ``NA`` with a warning, so the title,
    abstract and references already retrieved for the document are kept.
    """
    try:
        kw = _get(obj, "authkeywords")
        return "; ".join(kw) if kw else pd.NA
    except (KeyError, TypeError, AttributeError) as exc:
        name = ident or _get(obj, "doi") or _get(obj, "eid") or "a document"
        warnings.warn(
            f"The author keywords of {name!r} could not be read "
            f"({type(exc).__name__}: {exc}), so they are left NA and the rest of "
            "the record is kept.",
            stacklevel=4,
        )
        return pd.NA


def _abstract_row(obj, include: tuple[str, ...] = (), ident: str | None = None) -> dict:
    """Normalise a single ``AbstractRetrieval``-like object (or dict) into the
    stable :data:`ABSTRACT_COLUMNS` mapping; offline, no network. When
    "references" is included, a mismatch between the number of references
    returned and the document's own reported ``refcount`` is warned about,
    since the list may be an incomplete page of the bibliography. ``ident``,
    the identifier the document was requested by, names it in warnings."""
    date = _get(obj, "coverDate")
    head = str(date)[:4] if date else ""
    year = int(head) if head.isdigit() else pd.NA
    row = {
        # Shared with to_records() so a missing identifier or citation count is
        # spelled the same way on both retrieval paths.
        "scopus_id": _scopus_id(_get(obj, "eid")),
        "doi": _get(obj, "doi"),
        "title": _get(obj, "title"),
        "abstract": _get(obj, "description"),
        "publication": _get(obj, "publicationName"),
        "date": date,
        "year": year,
        "citations": _citations(_get(obj, "citedby_count")),
    }
    if "keywords" in include:
        row["authkeywords"] = _keywords(obj, ident)
    if "references" in include:
        refs = _references_frame(_get(obj, "references"))
        row["references"] = refs
        refcount = _get(obj, "refcount")
        try:
            expected = int(refcount) if refcount not in (None, "") else None
        except (TypeError, ValueError):
            expected = None
        if expected is not None and len(refs) != expected:
            ident = _get(obj, "doi") or _get(obj, "eid") or "this document"
            warnings.warn(
                f"{len(refs)} reference(s) returned for {ident}, which reports "
                f"refcount={expected}; the list may be an incomplete page "
                "rather than the whole bibliography.",
                stacklevel=2,
            )
    return row


def _served_from_cache(ab, t0: float, refresh) -> bool:
    """Whether pybliometrics answered this retrieval from its own cache, so
    that no request was sent.

    Read with the helpers the searches use (see ``_pyb``). A cache file that
    predates the call, or a response with no headers kept, marks a cached
    answer. When the file's time cannot be read, the missing headers alone
    decide. An object exposing neither getter, such as a test double, counts
    as fetched.
    """
    if not may_use_cache(refresh):
        return False
    written = cache_hit_time(ab, t0)
    if written is UNDATED:
        return bool(_kept_no_headers(ab))
    return written is not None


def _safe_filename(ident: str) -> str:
    """A filesystem-safe cache key: non-alphanumerics become "_", keeping the
    result human-decipherable (unlike a hash), since collisions between
    distinct real identifiers are effectively impossible."""
    return "".join(c if c.isalnum() else "_" for c in ident)


def _abstract_cache_name(view: str, include: tuple[str, ...], ident: str) -> str:
    """The per-identifier checkpoint filename. Both ``view`` and ``include``
    are part of the key, since both change what a row carries: a resumed run
    with a different ``include`` must refetch, since the cached row would be
    a leaner one."""
    incl = "-".join(sorted(include)) if include else "plain"
    return f"id-{view}-{incl}-{_safe_filename(ident)}.pkl"


def _find_abstract_checkpoint(
    cache: Path, view: str, include: tuple[str, ...], ident: str
) -> Path | None:
    candidate = cache / _abstract_cache_name(view, include, ident)
    return candidate if candidate.exists() else None


def _write_abstract_checkpoint(
    row: dict, cache: Path, view: str, include: tuple[str, ...], ident: str
) -> None:
    # Pickled, where fetch_plan()'s per-cell checkpoints use parquet or CSV: a row
    # here can carry a nested DataFrame in its "references" entry, which
    # parquet and csv cannot hold in a single cell but pickle handles
    # directly, the same way the R package's per-identifier cache relies on
    # RDS to hold an R list-column.
    #
    # Written through the same atomic route as the per-cell checkpoints, and
    # for the same reason: an interrupted run must leave either the previous
    # checkpoint or none at all, never a half-written one that every later
    # resume of this identifier then fails on.
    _atomic_write(
        lambda path: path.write_bytes(pickle.dumps(row)),
        cache / _abstract_cache_name(view, include, ident),
    )


def _read_abstract_checkpoint(path: Path) -> dict | None:
    """Unpickle a per-identifier checkpoint, or return ``None`` if it is damaged.

    Mirrors ``scopus_read_checkpoint()`` in the R twin: a checkpoint that cannot
    be read back is a cache miss and never a fatal error, so an interrupted
    run costs one retrieval and does not block every later resume.
    """
    try:
        with open(path, "rb") as handle:
            return pickle.load(handle)
    except Exception:
        return None


def scopus_abstract(
    ids,
    by: str = "doi",
    view: str = "META_ABS",
    include: tuple[str, ...] = (),
    cache_dir: str | None = None,
    resume: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """Retrieve abstracts for one or many ids, resilient per id.

    ``ids`` is one identifier, or a list, tuple or pandas Series of them.
    They are checked before any request, as in the R twin. A missing or blank
    identifier raises ``ValueError`` naming its position, counting from 0.
    :func:`scopusflow.corpus.corpus` drops such records itself. Surrounding
    whitespace is trimmed, the ``SCOPUS_ID:`` prefix is dropped when
    ``by="scopus_id"``, and whole numbers are sent as text. Any other value,
    a float or bytes among them, raises ``TypeError``.

    ``by`` selects the lookup type ("doi", "eid" or "scopus_id"). Any id that
    fails is warned about and yields an all-NA row that still records the id.
    ``view`` defaults to "META_ABS" (pybliometrics' own default), which
    carries the abstract text; the lighter "META" omits it and leaves the
    ``abstract`` column empty. ``include``, when unused, leaves the column
    set exactly as before.

    ``include`` names extra fields to retrieve in the same request:
    "references" and/or "keywords". "references" needs Abstract Retrieval's
    "FULL" or "REF" view, and "keywords" needs the "FULL" view, since the
    other views carry no author keywords. Any other combination raises
    ``ValueError`` before a request. Both views are an entitlement separate
    from ordinary abstract access and from Scopus Search access. Per
    Elsevier's own documentation, some fields (notably author keywords) may
    need to be requested from your Scopus/Elsevier account contact even when
    the view itself is otherwise accessible. "FULL" returns the whole bibliography in
    one request. "REF" serves it about 40 references per request, and
    pybliometrics pages REF itself, following the view's ``startref``
    parameter until the list is complete, so a document with N references
    costs ``ceil(N / 40)`` requests under "REF". "FULL" is therefore the
    cheaper view when your entitlement allows it. A mismatch between the
    number of references returned and the document's own reported reference
    count (``refcount``) is warned about, since the list may then be
    incomplete.

    When "keywords" is included, an ``authkeywords`` column is added: the
    document's author-supplied keywords, joined with "; ", or ``NA`` when the
    document has none, or when the API omits the field for a given key's
    entitlement. In this package's own development testing, against a live,
    otherwise fully-entitled key, this field did not populate for documents
    that do carry author keywords in Scopus itself, so an all-``NA`` column
    is more likely an entitlement gap worth raising with your Scopus/Elsevier
    account contact than genuinely absent data. A keyword entry that
    pybliometrics cannot parse (its 4.4.1 release raises ``KeyError`` on an
    entry without text) leaves that document's keywords ``NA`` with a
    warning, and the rest of its row is kept.

    When "references" is included, a ``references`` column is added: one
    DataFrame per document (one row per cited work), using pybliometrics' own
    native field set (``position``, ``id``, ``doi``, ``title``, ``authors``,
    ``authors_auid``, ``authors_affiliationid``, ``sourcetitle``,
    ``publicationyear``, ``coverDate``, ``volume``, ``issue``, ``first``,
    ``last``, ``citedbycount``, ``type``, ``text``, ``fulltext``). A document
    with no resolvable references yields a zero-row DataFrame, so
    the column can always be unnested.

    ``cache_dir`` and ``resume`` checkpoint per identifier, the way
    :func:`scopusflow.fetch.fetch_plan` checkpoints per cell, pickled rather
    than written as parquet/csv, since a row here can carry a nested
    DataFrame. Only a successful retrieval is checkpointed: a failed
    identifier still yields its warned-about NA row in the returned frame,
    but is retried on the next resumed run, never read back as data.
    Worth setting whenever ``include`` is used: Abstract Retrieval
    draws on its own weekly quota, smaller than and separate from Search's,
    and every identifier costs its own request, so re-running an interrupted
    batch without a cache re-spends quota already spent. Relying on
    pybliometrics' own on-disk response cache (its ``refresh`` parameter,
    keyed by identifier and view under its configured cache directory) is
    enough to avoid repeat network calls for the *same* identifier across
    script runs; this checkpoint is for batch-level progress and resumability
    across *many* identifiers, a separate concern.

    The number of Abstract Retrieval requests made, and the most recently
    parsed remaining-quota figure (from pybliometrics'
    ``get_key_remaining_quota()``), are attached as ``result.attrs["n_requests"]``
    and ``result.attrs["quota"]``, since this is a materially more expensive
    operation than a search call. ``n_requests`` counts each document once,
    however many REF pages pybliometrics requested for it, so it is a count
    of documents fetched. A failed retrieval counts once, since the API has
    usually answered it with an error. A row read from a ``cache_dir``
    checkpoint sent no request and is not counted. Nor is a row pybliometrics
    answered from its own cache, recognised by a cache file older than the
    call or by a response with no headers kept. Such a row's ``citations``
    and other fields date from when that cache file was written. Pass
    ``refresh=True`` to fetch every identifier from the API.

    A 403 (an entitlement gate, most often on the requested view or field)
    raises :class:`scopusflow.exceptions.ScopusFlowForbiddenError` and stops
    the batch immediately, naming the view and identifier, where a generic
    failure would leave the caller guessing. Repeating the identical failure
    for every remaining identifier would serve nobody: entitlement is a
    property of the account, so a retry cannot succeed.

    Raises :class:`scopusflow.exceptions.ScopusFlowConfigError` before any
    request when ``pybliometrics.init()`` has not been called in the session.
    An identifier served from its checkpoint sends no request, so a batch
    resumed wholly from checkpoints runs without ``init()``.
    """
    if by not in _ID_TYPES:
        raise ValueError("by must be one of 'doi', 'eid', 'scopus_id'.")
    include = tuple(include) if include else ()
    if not set(include) <= _KNOWN_INCLUDE:
        raise ValueError("include must be made up of 'references' and/or 'keywords'.")
    if "references" in include and view not in _VIEWS_WITH_REFERENCES:
        raise ValueError('include="references" needs view="FULL" or view="REF".')
    # The REF response carries no author keywords and META/META_ABS none
    # either, so accepting them would only give a silently all-NA column.
    if "keywords" in include and view != "FULL":
        raise ValueError('include="keywords" needs view="FULL".')
    id_type = _ID_TYPES[by]
    id_column = "doi" if by == "doi" else "scopus_id"

    ids = _clean_ids(ids, by)

    columns = list(ABSTRACT_COLUMNS)
    if "keywords" in include:
        columns = [*columns, "authkeywords"]
    if "references" in include:
        columns = [*columns, "references"]

    cache = Path(cache_dir) if cache_dir else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    # Resolve the dependency once: a missing pybliometrics is a setup error and
    # must be raised in its own right, where masquerading as every id failing
    # to retrieve would hide the account-level cause.
    from pybliometrics.scopus import AbstractRetrieval  # lazy; needs a key
    try:
        # A separate, defensive import: pybliometrics.exception is an internal
        # module, outside pybliometrics.scopus's own public surface, so a
        # minimal test double or an unexpected future reorganisation should
        # degrade to generic exception handling below, which stops it breaking
        # every call to this function.
        from pybliometrics.exception import Scopus403Error
    except ImportError:
        class Scopus403Error(Exception):  # never actually raised; see above
            pass

    n_requests = 0
    quota = None
    rows = []
    for i, ident in enumerate(ids, start=1):
        checkpoint = (
            _find_abstract_checkpoint(cache, view, include, ident)
            if cache is not None else None
        )
        if checkpoint is not None and resume:
            cached = _read_abstract_checkpoint(checkpoint)
            if cached is None:
                warnings.warn(
                    f"The checkpoint {checkpoint} could not be read back, so it "
                    "was discarded and the identifier retrieved again. An "
                    "interrupted run can leave a checkpoint half-written.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                logger.info("%d/%d: %s loaded from cache.", i, len(ids), ident)
                rows.append(cached)
                continue

        logger.info("Retrieving %d/%d: %s", i, len(ids), ident)
        # Checked before the first request, outside the per-identifier handler
        # below: an uninitialised pybliometrics would fail every identifier in
        # turn, each failure warned about as if that identifier alone were at
        # fault. An identifier served from its checkpoint sends no request, so
        # a batch resumed wholly from checkpoints needs no init().
        require_init()
        # Each identifier adds to n_requests exactly once, and only when a
        # request went out. A step that fails after the response arrived used
        # to add a second count for the same request. A failed construction
        # counts as one: the API has usually answered it with an error.
        ab = None
        t0 = time.time()
        try:
            ab = AbstractRetrieval(ident, id_type=id_type, view=view, **kwargs)
            if _served_from_cache(ab, t0, kwargs.get("refresh", False)):
                logger.info("%d/%d: %s read from pybliometrics' cache.", i, len(ids), ident)
            else:
                n_requests += 1
            # Optional: an object without these methods (a plain dict, or a
            # minimal stand-in) simply reports no quota, and does not fail
            # the whole retrieval over a metadata nicety. Both lookups are
            # guarded, since an object carrying only the first would otherwise
            # fail here after a successful retrieval and record an NA row.
            get_quota = getattr(ab, "get_key_remaining_quota", None)
            get_reset = getattr(ab, "get_key_reset_time", None)
            remaining = get_quota() if callable(get_quota) else None
            if remaining is not None:
                reset = get_reset() if callable(get_reset) else None
                quota = {"remaining": remaining, "reset": reset}
            row = _abstract_row(ab, include=include, ident=ident)
        except Scopus403Error as exc:
            n_requests += 1
            remaining_ids = len(ids) - i
            # The FULL/REF alternative is only sensible advice when the failed
            # view was one of the two reference-carrying views; a 403 on a
            # plain META/META_ABS retrieval is an ordinary entitlement gap.
            alternative = (
                ' or, if you have not already, try the other of "FULL"/"REF"'
                if view in _VIEWS_WITH_REFERENCES else ""
            )
            raise ScopusFlowForbiddenError(
                f'Abstract Retrieval refused view="{view}" (HTTP 403) for {ident!r}. '
                "This usually means your Scopus API key's entitlement does not cover "
                "the requested view or field; contact your Scopus/Elsevier account "
                f"holder or institutional administrator to request access{alternative}. "
                "Stopping rather "
                f"than repeating the same failure for the remaining {remaining_ids} "
                "identifier(s) (this entitlement is an account-level property, not a "
                "per-document one, so it will not succeed on retry)."
            ) from exc
        except Exception:  # one bad id must not sink the batch
            if ab is None:  # a response that arrived was counted above
                n_requests += 1
            warnings.warn(
                f"Could not retrieve abstract for {ident!r}; recording NA row.",
                stacklevel=2,
            )
            row = {col: pd.NA for col in columns}
            row[id_column] = ident
            if "references" in include:
                row["references"] = _references_frame(None)
            # Never checkpointed: many failures are transient (a timeout, a
            # quota 429, a 5xx), and a persisted NA row would be read back as
            # data on every later resume. The identifier is retried instead,
            # at the cost of one request.
            rows.append(row)
            continue

        if cache is not None:
            _write_abstract_checkpoint(row, cache, view, include, ident)
        rows.append(row)

    out = pd.DataFrame(rows, columns=columns)
    out.attrs["n_requests"] = n_requests
    out.attrs["quota"] = quota
    return out
