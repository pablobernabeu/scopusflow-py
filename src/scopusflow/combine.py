"""Merge record sets into one, optionally dropping the records they share."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ._provenance import as_datetime
from .diff import _clean_one
from .records import RECORD_COLUMNS

__all__ = ["scopus_combine"]

#: The de-duplication rules, by the name ``dedupe`` takes. ``True`` is the first.
_RULES = ("id_or_shared_doi", "id_or_doi", "id_then_doi")


def _instant(value) -> datetime:
    """A recorded time, ISO 8601 text or a ``datetime``, as an instant in UTC,
    so that times recorded in different forms compare. A naive ``datetime`` is
    read as local time, as the search record reads it."""
    return as_datetime(value).astimezone(timezone.utc)


def _rule(dedupe) -> str | None:
    """The rule ``dedupe`` names, or ``None`` for none. ``True`` is the default
    rule."""
    if isinstance(dedupe, (bool, np.bool_)):
        return _RULES[0] if dedupe else None
    if isinstance(dedupe, str) and dedupe in _RULES:
        return dedupe
    raise ValueError(
        "dedupe must be True, False, 'id_or_shared_doi', 'id_or_doi' or 'id_then_doi'."
    )


def _legacy_key(frame: pd.DataFrame) -> pd.Series:
    """The 0.4.0 key, unchanged, so that ``dedupe="id_then_doi"`` reproduces an
    earlier set exactly: the Scopus identifier, failing that the DOI lower-cased
    but not otherwise cleaned, failing that the row."""
    ids = frame["scopus_id"].astype("string")
    dois = frame["doi"].astype("string").str.lower()
    key = pd.Series("row:" + frame.index.astype(str), index=frame.index, dtype="string")
    key = key.mask(dois.notna(), "doi:" + dois)
    return key.mask(ids.notna(), "id:" + ids)


def _identifier(value) -> str | None:
    """A record's Scopus identifier as text, or ``None`` when it has none. A
    blank identifier is none, as a spreadsheet's CSV leaves the field empty."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return str(value).strip() or None


def _record_groups(frame: pd.DataFrame, rule: str) -> tuple[list[str], int]:
    """One group key per record under ``rule``, and the number of DOIs that
    records with two or more different identifiers carry.

    Records with the same key are one record, and the first of them is kept.
    DOIs are compared as :func:`scopusflow.diff.extract_dois` compares them,
    without resolver prefixes and ignoring case. They are folded with Python's
    own ``str.lower``, never a pandas string method, which may run as an Arrow
    kernel with Unicode's simple case mapping. The R twin's
    ``scopus_dedupe_groups()`` computes the same keys, so both twins keep the
    same rows.
    """
    ids = [_identifier(v) for v in frame["scopus_id"]]
    dois = [None if (d := _clean_one(v)) is None else d.lower() for v in frame["doi"]]
    owners: dict[str, list[str]] = {}
    for ident, doi in zip(ids, dois, strict=True):
        if ident is not None and doi is not None:
            carriers = owners.setdefault(doi, [])
            if ident not in carriers:
                carriers.append(ident)
    conflicts = sum(len(carriers) > 1 for carriers in owners.values())

    if rule == "id_then_doi":
        return list(_legacy_key(frame)), conflicts

    if rule == "id_or_shared_doi":
        keys = []
        for row, (ident, doi) in enumerate(zip(ids, dois, strict=True)):
            if ident is not None:
                keys.append(f"id:{ident}")
            elif doi is not None and len(owners.get(doi, ())) == 1:
                # The one identifier that carries this DOI. Where two or more
                # carry it, the record cannot be assigned to either and stays
                # under the DOI's own key.
                keys.append(f"id:{owners[doi][0]}")
            elif doi is not None:
                keys.append(f"doi:{doi}")
            else:
                keys.append(f"row:{row}")
        return keys, conflicts

    # "id_or_doi": connected components over both keys, each labelled by its
    # first record, since a union always hangs the later root on the earlier.
    parent = list(range(len(ids)))

    def root(row: int) -> int:
        while parent[row] != row:
            parent[row] = parent[parent[row]]
            row = parent[row]
        return row

    for values in (ids, dois):
        first: dict[str, int] = {}
        for row, value in enumerate(values):
            if value is None:
                continue
            if value in first:
                a, b = root(first[value]), root(row)
                parent[max(a, b)] = min(a, b)
            else:
                first[value] = row
    return [f"set:{root(row)}" for row in range(len(ids))], conflicts


def _without_attrs(frame: pd.DataFrame) -> pd.DataFrame:
    """A shallow view of ``frame`` carrying none of its ``attrs``.

    ``concat`` decides whether to hand the inputs' attrs to the result by
    comparing the dicts. When a harvest carried its ``cell_totals`` as a frame,
    that comparison evaluated one frame against another and pandas raised "The
    truth value of a DataFrame is ambiguous". Where the comparison succeeds,
    because every input carries equal values, propagating them would be wrong
    all the same: ``plan``, ``total_results`` and ``cell_totals`` describe one
    retrieval, and a merge is not that retrieval,
    so the search record would go on to report the union of two harvests as
    complete against a total belonging to one of them. The R twin's
    ``scopus_combine()`` starts from the rows alone for the same reason. What
    survives a merge, and what the merge itself knows, is added back below.
    """
    bare = frame.copy(deep=False)
    bare.attrs = {}
    return bare


def _bind_provenance(out: pd.DataFrame, frames: list[pd.DataFrame]) -> None:
    """Carry onto the merge what survives it, as R's ``scopus_bind_provenance()`` does.

    A merged set is only as fresh as its oldest part, so ``retrieved_at`` is
    its oldest input's time. ``retrieved_until`` is the newest input's, the
    last search, which PRISMA-S item 13 asks for, so a baseline merged with
    its update is dated from one to the other. An input written before
    ``retrieved_until`` existed counts by its ``retrieved_at``. The merge is
    also the work of every version that built one of its inputs, so their
    versions are all kept, sorted, in one list. The times are claimed only
    when every input carries one, and the versions only when every input
    carries one. Dating the merge by the inputs that carry a time could place
    it later than part of what it holds, which a provenance field must never
    do. The paging mode and the view are claimed
    only when every input records the same one, for the same reason. A
    STANDARD part merged with a COMPLETE one holds neither first authors alone
    nor author lists alone.
    """
    stamps = [f.attrs.get("retrieved_at") for f in frames]
    if all(stamp is not None for stamp in stamps):
        # A harvest records its time as ISO 8601 text and a set dated by hand
        # may carry a datetime, so each is compared as the instant it names,
        # and the earliest and latest are kept in the forms their inputs gave.
        out.attrs["retrieved_at"] = min(stamps, key=_instant)
        latest = [f.attrs.get("retrieved_until") or f.attrs.get("retrieved_at")
                  for f in frames]
        out.attrs["retrieved_until"] = max(latest, key=_instant)
    versions = [f.attrs.get("scopusflow_version") for f in frames]
    if all(version is not None for version in versions):
        seen: set[str] = set()
        for version in versions:
            # A set merged before carries a list of versions already.
            seen.update([version] if isinstance(version, str) else version)
        out.attrs["scopusflow_version"] = sorted(seen)
    for name in ("paging", "view"):
        values = {f.attrs.get(name) for f in frames}
        if len(values) == 1 and None not in values:
            out.attrs[name] = values.pop()


def scopus_combine(*sets, dedupe: bool | str = False) -> pd.DataFrame:
    """Bind several record frames into one, renumbering ``entry_number``.

    This is the safe way to merge separate harvests: a plain ``concat`` leaves
    duplicate entry numbers, and nothing then records how many records went in.

    De-duplication compares DOIs as :func:`scopusflow.diff.extract_dois` does,
    without resolver prefixes such as ``https://doi.org/`` or ``doi:`` and
    ignoring case. It keeps the first record of each group, in the order the
    sets were given, and a record with neither an identifier nor a DOI cannot
    be matched and is kept.

    Under the default rule, records with the same Scopus identifier are one
    record, and a record without an identifier joins the identified record
    that carries its DOI. Records with different identifiers are never merged,
    even when they share a DOI. Scopus holds duplicate records of one paper
    (Valderrama-Zurián et al., 2015), but it also gives one DOI to distinct
    papers (Franceschini et al., 2015), and a review loses a wrongly removed
    record for good where a surviving duplicate is caught at screening. Such
    DOIs are counted in ``doi_conflicts``, which the search record reports, so
    that they can be checked by hand. A record without an identifier whose DOI
    two identified records carry is kept once, apart from both. Records without
    an identifier that share a DOI no identified record carries are one record.

    ``"id_or_doi"`` merges every record linked to another by a shared
    identifier or a shared DOI, directly or through a chain of such links. It
    suits a set whose shared DOIs have been checked and found to be
    duplicates. ``"id_then_doi"`` keys each record on its identifier, failing
    that on its DOI lower-cased but not otherwise cleaned, and so reproduces a
    set de-duplicated by scopusflow 0.4.0 or earlier.

    Parameters
    ----------
    *sets:
        Two or more record frames, or a single list of them.
    dedupe:
        Whether, and by which rule, to keep once the records that are one
        record. ``False``, the default, keeps every row. ``True``, also spelled
        ``"id_or_shared_doi"``, treats records as one when they share a Scopus
        identifier, or when they share a DOI and one of them lacks an
        identifier. ``"id_or_doi"`` also merges records with different
        identifiers that share a DOI, and ``"id_then_doi"`` applies the rule of
        scopusflow 0.4.0 and earlier.

    Returns
    -------
    pandas.DataFrame
        The merged records. Attributes describing a single retrieval, among
        them ``plan``, ``total_results`` and ``cell_totals``, are not carried
        over, since a set built from several harvests is none of them. Five
        survive a merge, each only when every input carries it.
        ``retrieved_at`` is the earliest of the inputs' times,
        ``retrieved_until`` the latest (an input without one counting by its
        ``retrieved_at``) and ``scopusflow_version`` a sorted list of every
        contributing version, while ``paging`` and ``view`` are kept only where
        the inputs agree on them. The search record of a merged set is then
        dated from its first retrieval to its last, as the R twin's is. The
        merge itself is recorded in ``attrs["combined"]``, a dict of ``n_in``
        (records supplied), ``n_out`` (records kept), ``n_removed``,
        ``deduplicated``, ``rule`` (the rule applied, ``None`` when none was)
        and ``doi_conflicts`` (how many DOIs records with different
        identifiers share, ``None`` when no rule was applied). That count
        exists only at the moment of the merge, and PRISMA-S asks for it (item
        16), so :func:`scopusflow.report.scopus_search_report` reads it back
        from there and states how many duplicates were removed and how.

    Raises
    ------
    ValueError
        When ``dedupe`` is neither a bool nor the name of a rule, or an input
        is not a record frame.

    References
    ----------
    Franceschini, F., Maisano, D., & Mastrogiacomo, L. (2015). Errors in DOI
    indexing by bibliometric databases. *Scientometrics*, *102*(3), 2181–2186.
    https://doi.org/10.1007/s11192-014-1503-4

    Valderrama-Zurián, J.-C., Aguilar-Moya, R., Melero-Fuentes, D., &
    Aleixandre-Benavent, R. (2015). A systematic analysis of duplicate records
    in Scopus. *Journal of Informetrics*, *9*(3), 570–576.
    https://doi.org/10.1016/j.joi.2015.05.002

    Examples
    --------
    >>> import scopusflow as sf
    >>> baseline = sf.example_records()
    >>> later = sf.example_records()
    >>> merged = sf.scopus_combine(baseline, later, dedupe=True)
    >>> merged.attrs["combined"]["n_in"]
    276
    >>> len(merged)
    149
    """
    rule = _rule(dedupe)
    frames = list(sets)
    if len(frames) == 1 and isinstance(frames[0], (list, tuple)):
        frames = list(frames[0])
    if not frames or not all(isinstance(f, pd.DataFrame) for f in frames):
        raise ValueError("All inputs to scopus_combine() must be record frames.")

    out = pd.concat([_without_attrs(f) for f in frames], ignore_index=True)
    n_in = len(out)
    conflicts = None
    if rule is not None:
        keys, conflicts = _record_groups(out, rule)
        out = out[~pd.Series(keys, dtype=object).duplicated().to_numpy()].reset_index(
            drop=True)
    if len(out):
        out["entry_number"] = range(1, len(out) + 1)
    else:
        out = out.reindex(columns=list(out.columns) or list(RECORD_COLUMNS))
    # The rule is recorded beside the counts, since the search record has to
    # say how records were matched, and a set merged by 0.4.0 records none.
    out.attrs["combined"] = {
        "n_in": n_in,
        "n_out": len(out),
        "n_removed": n_in - len(out),
        "deduplicated": rule is not None,
        "rule": rule,
        "doi_conflicts": conflicts,
    }
    _bind_provenance(out, frames)
    return out
