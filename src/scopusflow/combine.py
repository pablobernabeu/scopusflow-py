"""Merge record sets into one, optionally dropping the records they share."""

from __future__ import annotations

import pandas as pd

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
    comparing the dicts, and two harvests each carry a ``cell_totals`` frame, so
    that comparison ends up evaluating one frame against another and pandas
    raises "The truth value of a DataFrame is ambiguous". Where the comparison
    does succeed, because every input happens to carry the very same objects,
    propagating them is worse than the error: ``plan``, ``total_results`` and
    ``cell_totals`` describe one retrieval, and a merge is not that retrieval,
    so the search record would go on to report the union of two harvests as
    complete against a total belonging to one of them. The R twin's
    ``scopus_combine()`` builds its result from the rows alone for the same
    reason. What the merge itself knows is recorded below.
    """
    bare = frame.copy(deep=False)
    bare.attrs = {}
    return bare


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
        over, since a set built from several harvests is none of them. The merge
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
    return out
