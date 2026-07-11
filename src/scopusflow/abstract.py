"""Batch abstract retrieval, resilient per id."""

from __future__ import annotations

import logging
import pickle
import warnings
from pathlib import Path

import pandas as pd

from .exceptions import ScopusFlowForbiddenError

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


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _references_frame(refs) -> pd.DataFrame:
    """Normalise pybliometrics' own ``Reference`` namedtuples into a DataFrame,
    one row per cited work, keeping pybliometrics' full native field set."""
    from pybliometrics.scopus import Reference

    if not refs:
        return pd.DataFrame(columns=list(Reference._fields))
    return pd.DataFrame([r._asdict() for r in refs])


def _abstract_row(obj, include: tuple[str, ...] = ()) -> dict:
    """Normalise a single ``AbstractRetrieval``-like object (or dict) into the
    stable :data:`ABSTRACT_COLUMNS` mapping; offline, no network. When
    "references" is included, a mismatch between the number of references
    returned and the document's own reported ``refcount`` is warned about,
    since the list may be an incomplete page rather than the whole
    bibliography."""
    eid = _get(obj, "eid")
    scopus_id = str(eid).split("2-s2.0-")[-1] if eid else pd.NA
    date = _get(obj, "coverDate")
    head = str(date)[:4] if date else ""
    year = int(head) if head.isdigit() else pd.NA
    cited = _get(obj, "citedby_count")
    citations = int(cited) if cited not in (None, "") else pd.NA
    row = {
        "scopus_id": scopus_id,
        "doi": _get(obj, "doi"),
        "title": _get(obj, "title"),
        "abstract": _get(obj, "description"),
        "publication": _get(obj, "publicationName"),
        "date": date,
        "year": year,
        "citations": citations,
    }
    if "keywords" in include:
        kw = _get(obj, "authkeywords")
        row["authkeywords"] = "; ".join(kw) if kw else pd.NA
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


def _safe_filename(ident: str) -> str:
    """A filesystem-safe cache key: non-alphanumerics become "_", keeping the
    result human-decipherable (unlike a hash), since collisions between
    distinct real identifiers are effectively impossible."""
    return "".join(c if c.isalnum() else "_" for c in ident)


def _abstract_cache_name(view: str, include: tuple[str, ...], ident: str) -> str:
    """The per-identifier checkpoint filename. Both ``view`` and ``include``
    are part of the key, since both change what a row carries: a resumed run
    with a different ``include`` must refetch rather than silently reuse a
    leaner cached row."""
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
    # Pickled, not parquet/csv like fetch_plan()'s per-cell checkpoints: a row
    # here can carry a nested DataFrame in its "references" entry, which
    # parquet and csv cannot hold in a single cell but pickle handles
    # directly, the same way the R package's per-identifier cache relies on
    # RDS to hold an R list-column.
    with open(cache / _abstract_cache_name(view, include, ident), "wb") as f:
        pickle.dump(row, f)


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

    ``by`` selects the lookup type ("doi", "eid" or "scopus_id"). Any id that
    fails is warned about and yields an all-NA row that still records the id.
    ``view`` defaults to "META_ABS" (pybliometrics' own default), which
    carries the abstract text; the lighter "META" omits it and leaves the
    ``abstract`` column empty. ``include``, when unused, leaves the column
    set exactly as before.

    ``include`` names extra fields to retrieve in the same request:
    "references" and/or "keywords". Both require Abstract Retrieval's "FULL"
    or "REF" view (see ``view``), an entitlement separate from ordinary
    abstract access and from Scopus Search access, and that, per Elsevier's
    own documentation, some fields (notably author keywords) may need to be
    requested from your Scopus/Elsevier account contact even when the view
    itself is otherwise accessible. In development, against a live key with
    full Abstract Retrieval access, "FULL" returned a complete, correctly
    counted reference list for every document tried, while "REF" returned the
    identical, complete list in one case but a truncated (paginated) subset in
    another on an otherwise identical request made moments apart; "FULL" is
    recommended when your entitlement allows it, and a mismatch between the
    number of references returned and the document's own reported reference
    count (``refcount``) is warned about, since the list may be an incomplete
    page rather than the whole bibliography.

    When "keywords" is included, an ``authkeywords`` column is added: the
    document's author-supplied keywords, joined with "; ", or ``NA`` when the
    document has none, or when the API omits the field for a given key's
    entitlement. In this package's own development testing, against a live,
    otherwise fully-entitled key, this field did not populate for documents
    that do carry author keywords in Scopus itself, so an all-``NA`` column
    is more likely an entitlement gap worth raising with your Scopus/Elsevier
    account contact than genuinely absent data.

    When "references" is included, a ``references`` column is added: one
    DataFrame per document (one row per cited work), using pybliometrics' own
    native field set (``position``, ``id``, ``doi``, ``title``, ``authors``,
    ``authors_auid``, ``authors_affiliationid``, ``sourcetitle``,
    ``publicationyear``, ``coverDate``, ``volume``, ``issue``, ``first``,
    ``last``, ``citedbycount``, ``type``, ``text``, ``fulltext``). A document
    with no resolvable references yields a zero-row DataFrame, not ``NA``, so
    the column can always be unnested.

    ``cache_dir`` and ``resume`` checkpoint per identifier, the way
    :func:`scopusflow.fetch.fetch_plan` checkpoints per cell, pickled rather
    than written as parquet/csv, since a row here can carry a nested
    DataFrame. Worth setting whenever ``include`` is used: Abstract Retrieval
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
    operation than a search call.

    A 403 (an entitlement gate, most often on the requested view or field)
    raises :class:`scopusflow.exceptions.ScopusFlowForbiddenError` and stops
    the batch immediately, naming the view and identifier, rather than
    repeating the identical failure for every remaining identifier:
    entitlement is an account-level property, not a per-document one, so it
    will not succeed on retry.
    """
    if by not in _ID_TYPES:
        raise ValueError("by must be one of 'doi', 'eid', 'scopus_id'.")
    include = tuple(include) if include else ()
    if not set(include) <= _KNOWN_INCLUDE:
        raise ValueError("include must be made up of 'references' and/or 'keywords'.")
    if "references" in include and view not in _VIEWS_WITH_REFERENCES:
        raise ValueError('include="references" needs view="FULL" or view="REF".')
    id_type = _ID_TYPES[by]
    id_column = "doi" if by == "doi" else "scopus_id"

    if isinstance(ids, str):
        ids = [ids]

    columns = list(ABSTRACT_COLUMNS)
    if "keywords" in include:
        columns = [*columns, "authkeywords"]
    if "references" in include:
        columns = [*columns, "references"]

    cache = Path(cache_dir) if cache_dir else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    # Resolve the dependency once: a missing pybliometrics is a setup error and
    # must surface clearly, not masquerade as every id failing to retrieve.
    from pybliometrics.scopus import AbstractRetrieval  # lazy; needs a key
    try:
        # A separate, defensive import: pybliometrics.exception is an internal
        # module, not part of pybliometrics.scopus's own public surface, so a
        # minimal test double or an unexpected future reorganisation should
        # degrade to generic exception handling below rather than breaking
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
            logger.info("%d/%d: %s loaded from cache.", i, len(ids), ident)
            with open(checkpoint, "rb") as f:
                rows.append(pickle.load(f))
            continue

        logger.info("Retrieving %d/%d: %s", i, len(ids), ident)
        try:
            ab = AbstractRetrieval(ident, id_type=id_type, view=view, **kwargs)
            n_requests += 1
            # Optional: an object without these methods (a plain dict, or a
            # minimal stand-in) simply reports no quota, rather than failing
            # the whole retrieval over a metadata nicety.
            get_quota = getattr(ab, "get_key_remaining_quota", None)
            remaining = get_quota() if callable(get_quota) else None
            if remaining is not None:
                quota = {"remaining": remaining, "reset": ab.get_key_reset_time()}
            row = _abstract_row(ab, include=include)
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
            n_requests += 1
            warnings.warn(
                f"Could not retrieve abstract for {ident!r}; recording NA row.",
                stacklevel=2,
            )
            row = {col: pd.NA for col in columns}
            row[id_column] = ident
            if "references" in include:
                row["references"] = _references_frame(None)

        if cache is not None:
            _write_abstract_checkpoint(row, cache, view, include, ident)
        rows.append(row)

    out = pd.DataFrame(rows, columns=columns)
    out.attrs["n_requests"] = n_requests
    out.attrs["quota"] = quota
    return out
