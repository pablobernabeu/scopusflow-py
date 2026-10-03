"""Merge record sets into one, optionally dropping the records they share."""

from __future__ import annotations

import pandas as pd

from ._provenance import as_datetime
from .records import RECORD_COLUMNS

__all__ = ["scopus_combine"]


def _key(frame: pd.DataFrame) -> pd.Series:
    """The de-duplication key: the Scopus identifier, failing that the DOI.

    A record carrying neither cannot be matched to its own copy, so it is given
    a key of its own and survives in both. Case is ignored on the DOI, DOIs
    being case-insensitive, which is how ``extract_dois`` compares them too.
    """
    ids = frame["scopus_id"].astype("string")
    dois = frame["doi"].astype("string").str.lower()
    key = pd.Series("row:" + frame.index.astype(str), index=frame.index, dtype="string")
    key = key.mask(dois.notna(), "doi:" + dois)
    return key.mask(ids.notna(), "id:" + ids)


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

    A merged set is only as fresh as its oldest part, so it is dated by its
    oldest input. It is also the work of every version that built one of its
    inputs, so their versions are all kept, sorted, in one list. Neither is
    claimed when an input lacks it. Dating the merge by the inputs that carry a
    time could place it later than part of what it holds, which a provenance
    field must never do. The paging mode and the view are claimed only when
    every input records the same one, for the same reason. A STANDARD part
    merged with a COMPLETE one holds neither first authors alone nor author
    lists alone.
    """
    stamps = [f.attrs.get("retrieved_at") for f in frames]
    if all(stamp is not None for stamp in stamps):
        # A harvest records its time as ISO 8601 text and a set dated by hand
        # may carry a datetime, so each is compared as the instant it names,
        # and the earliest is kept in the form its input gave it.
        out.attrs["retrieved_at"] = min(stamps, key=as_datetime)
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


def scopus_combine(*sets, dedupe: bool = False) -> pd.DataFrame:
    """Bind several record frames into one, renumbering ``entry_number``.

    This is the safe way to merge separate harvests: a plain ``concat`` leaves
    duplicate entry numbers, and nothing then records how many records went in.

    Parameters
    ----------
    *sets:
        Two or more record frames, or a single list of them.
    dedupe:
        When ``True``, records sharing a Scopus identifier, or failing that a
        DOI (compared case-insensitively), are kept once.

    Returns
    -------
    pandas.DataFrame
        The merged records. Attributes describing a single retrieval, among
        them ``plan``, ``total_results`` and ``cell_totals``, are not carried
        over, since a set built from several harvests is none of them. Four
        survive a merge, each only when every input carries it.
        ``retrieved_at`` is the earliest of the inputs' times and
        ``scopusflow_version`` a sorted list of every contributing version,
        while ``paging`` and ``view`` are kept only where the inputs agree on
        them. The search record of a merged set is then dated, as the R twin's
        is. The merge
        itself is recorded in ``attrs["combined"]``, a dict of ``n_in`` (records
        supplied), ``n_out`` (records kept), ``n_removed`` and
        ``deduplicated``. That count exists only at the moment
        of the merge, and PRISMA-S asks for it (item 16), so
        :func:`scopusflow.report.scopus_search_report` reads it back from there
        so the item is answered.

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
    frames = list(sets)
    if len(frames) == 1 and isinstance(frames[0], (list, tuple)):
        frames = list(frames[0])
    if not frames or not all(isinstance(f, pd.DataFrame) for f in frames):
        raise ValueError("All inputs to scopus_combine() must be record frames.")

    out = pd.concat([_without_attrs(f) for f in frames], ignore_index=True)
    n_in = len(out)
    if dedupe:
        out = out[~_key(out).duplicated()].reset_index(drop=True)
    if len(out):
        out["entry_number"] = range(1, len(out) + 1)
    else:
        out = out.reindex(columns=list(out.columns) or list(RECORD_COLUMNS))
    out.attrs["combined"] = {
        "n_in": n_in,
        "n_out": len(out),
        "n_removed": n_in - len(out),
        "deduplicated": bool(dedupe),
    }
    _bind_provenance(out, frames)
    return out
