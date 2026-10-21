"""Extract, clean and compare DOI sets and record sets across retrievals."""

from __future__ import annotations

import re

import pandas as pd

_RESOLVER = re.compile(r"^\s*(https?://)?(www\.)?(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_LABEL = re.compile(r"^\s*doi:\s*", re.IGNORECASE)

#: The statuses of :func:`diff_dois`, in the order its rows are sorted.
_DOI_STATUSES = ("added", "removed", "unchanged")

#: The statuses of :func:`diff_records`, in the order its rows are sorted.
_RECORD_STATUSES = ("added", "removed", "conflict", "unchanged")

#: The columns of :func:`diff_records`, in order.
_RECORD_DIFF_COLUMNS = ["status", "scopus_id", "doi", "title", "year",
                        "citations_old", "citations_new"]


def _missing(value) -> bool:
    """Whether a cell holds no value, however pandas spells the gap."""
    return value is None or (pd.api.types.is_scalar(value) and pd.isna(value))


def _clean_one(d) -> str | None:
    """One DOI without its whitespace and resolver prefix, or ``None`` when it
    is missing or empty once cleaned. ``scopus_combine`` keys each record on it,
    so it keeps one value per record where :func:`_clean` drops the gaps."""
    # A record with no DOI has none whichever way the gap is spelled. A
    # nullable string column yields pd.NA, where an ordinary one would give a
    # float NaN, and str(pd.NA) is the literal "<NA>", which would otherwise be
    # carried through as though it were a DOI. The is_scalar guard keeps
    # pd.isna from returning an array when an element is itself array-like.
    if _missing(d):
        return None
    s = _RESOLVER.sub("", str(d).strip())
    s = _DOI_LABEL.sub("", s).strip()
    return s or None


def _clean(dois) -> list[str]:
    return [s for s in map(_clean_one, dois) if s is not None]


def _as_dois(x) -> list[str]:
    if isinstance(x, pd.DataFrame) and "doi" in x.columns:
        return x["doi"].tolist()
    return list(x)


def extract_dois(records, dedupe: bool = True) -> list[str]:
    """Pull cleaned, optionally de-duplicated DOIs from records or a list.

    ``records`` is a record frame, whose ``doi`` column is read, or any
    iterable of DOIs. Each DOI is stripped of surrounding whitespace, of a
    resolver prefix such as ``https://doi.org/`` or ``http://dx.doi.org/`` and
    of a leading ``doi:`` label, and a missing or empty one is dropped. With
    ``dedupe`` (the default), a DOI that repeats an earlier one, ignoring case,
    is dropped, so the first spelling is kept. Returns a list of strings, in
    the order and the case the DOIs came in.
    """
    dois = _clean(_as_dois(records))
    if not dedupe:
        return dois
    seen: set[str] = set()
    result: list[str] = []
    for d in dois:
        key = d.lower()
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result


def diff_dois(old, new) -> pd.DataFrame:
    """Compare the DOIs of two retrievals.

    A record without a DOI cannot be compared this way, and Scopus gives no
    DOI to a share of what it indexes, more of it in the arts and humanities
    and among books and proceedings (Gorraiz et al., 2016). Such records are
    left out of the rows and counted in ``attrs``.
    [`diff_records`][scopusflow.diff.diff_records] compares the records
    themselves, matching on the Scopus identifier.

    Parameters
    ----------
    old, new:
        Record frames or lists of DOIs, the earlier (``old``) and the later
        (``new``) retrieval.

    Returns
    -------
    pandas.DataFrame
        A ``doi`` column and a ``status`` column, where the status is
        ``added`` (in ``new`` only), ``removed`` (in ``old`` only) or
        ``unchanged`` (in both), compared without resolver prefixes and
        ignoring case. Rows are sorted by status then DOI, comparing code
        points, which the R twin's ``scopus_diff_dois()`` matches. The ints
        ``attrs["n_old_without_doi"]`` and ``attrs["n_new_without_doi"]``
        count the records (or list entries) on each side that had no DOI and
        so were not compared.

    References
    ----------
    Gorraiz, J., Melero-Fuentes, D., Gumpenberger, C., & Valderrama-Zurián,
    J.-C. (2016). Availability of digital object identifiers (DOIs) in Web of
    Science and Scopus. *Journal of Informetrics*, *10*(1), 98–109.
    https://doi.org/10.1016/j.joi.2015.11.008
    """
    old_raw, new_raw = _as_dois(old), _as_dois(new)
    old_d, new_d = extract_dois(old_raw), extract_dois(new_raw)
    old_keys = {d.lower() for d in old_d}
    new_keys = {d.lower() for d in new_d}
    rows = (
        [(d, "added") for d in new_d if d.lower() not in old_keys]
        + [(d, "removed") for d in old_d if d.lower() not in new_keys]
        + [(d, "unchanged") for d in new_d if d.lower() in old_keys]
    )
    # Sorted here, comparing code points, so that the order cannot depend on
    # how a pandas version or its Arrow backend sorts text.
    rows.sort(key=lambda row: (_DOI_STATUSES.index(row[1]), row[0]))
    df = pd.DataFrame(rows, columns=["doi", "status"])
    df.attrs["n_old_without_doi"] = sum(_clean_one(d) is None for d in old_raw)
    df.attrs["n_new_without_doi"] = sum(_clean_one(d) is None for d in new_raw)
    return df


def _diff_frame(x, name: str) -> list[dict]:
    """The fields :func:`diff_records` reads, one dict per record, with
    ``None`` for a missing value and for a column the frame lacks."""
    if not isinstance(x, pd.DataFrame):
        raise ValueError(f"{name} must be a record frame.")
    if "scopus_id" not in x.columns and "doi" not in x.columns:
        raise ValueError(f"{name} must have a scopus_id or a doi column.")
    fields = ("scopus_id", "doi", "title", "year", "citations")
    columns = {f: x[f].tolist() if f in x.columns else [None] * len(x) for f in fields}
    return [
        {f: None if _missing(columns[f][i]) else columns[f][i] for f in fields}
        for i in range(len(x))
    ]


def _given(value) -> bool:
    """Whether a field gives a value: not missing, and not blank text."""
    return value is not None and not (isinstance(value, str) and not value.strip())


def _byte_order(value) -> tuple:
    """A sort key that puts a missing value last and compares text by code
    point, which is how the R twin's radix order compares UTF-8 bytes."""
    return (value is None, "" if value is None else str(value))


def diff_records(old, new) -> pd.DataFrame:
    """Compare two retrievals record by record.

    Identifies which records were added, removed or unchanged between an
    earlier and a later retrieval, and gives each record's citation count in
    both. [`diff_dois`][scopusflow.diff.diff_dois] compares DOIs alone, and
    this function compares the records themselves, matched as
    ``scopus_combine(dedupe=True)`` matches them. A record without a DOI is
    therefore still tracked by its Scopus identifier, and two records under one
    DOI are not taken for one.

    Two records are one record when they share a Scopus identifier, or when
    they share a DOI and one of them lacks an identifier. DOIs are compared as
    [`extract_dois`][scopusflow.diff.extract_dois] compares them, without
    resolver prefixes and ignoring case. Records with different identifiers are
    never matched, even under one DOI, since Scopus gives one DOI to distinct
    papers as well as holding duplicate records of one paper
    ([`scopus_combine`][scopusflow.combine.scopus_combine] gives the sources).

    A record found in one retrieval only is a ``conflict`` where the other
    retrieval gives its DOI to a different record. It may have been re-indexed
    under a new identifier, or it may be a distinct paper sharing the DOI.
    Only the two records themselves can tell, so it is counted neither as
    added nor as removed. A record without an identifier whose DOI two
    identified records carry is in the same position. A record with neither an
    identifier nor a DOI cannot be matched at all, and is left out of the rows
    and counted.

    ``scopus_id`` is the identifier the record was matched on, missing for a
    record matched on its DOI alone. ``doi`` is the DOI without its resolver
    prefix, in the case the record gives it. ``doi``, ``title`` and ``year``
    come from the later retrieval where it holds the record and gives a value,
    and from the earlier one otherwise, while ``citations_old`` and
    ``citations_new`` come from each retrieval in turn. Where one retrieval
    holds a record more than once, the first value it gives is used.

    Parameters
    ----------
    old, new:
        Record frames with a ``scopus_id`` or a ``doi`` column, the earlier
        (``old``) and the later (``new``) retrieval. The ``title``, ``year``
        and ``citations`` columns are read where present.

    Returns
    -------
    pandas.DataFrame
        One row per record, with the columns ``status``, ``scopus_id``,
        ``doi``, ``title``, ``year``, ``citations_old`` and
        ``citations_new``. The status is ``added`` (in ``new`` only),
        ``removed`` (in ``old`` only), ``conflict`` or ``unchanged`` (in
        both). Rows are sorted in that order of status, then by DOI,
        identifier and title, comparing code points, which the R twin's
        ``scopus_diff_records()`` matches. The ints
        ``attrs["n_old_without_id_or_doi"]`` and
        ``attrs["n_new_without_id_or_doi"]`` count the records on each side
        that carried neither key and so were not compared.

    Raises
    ------
    ValueError
        When ``old`` or ``new`` is not a frame, or has neither a ``scopus_id``
        nor a ``doi`` column.

    Examples
    --------
    >>> import pandas as pd
    >>> import scopusflow as sf
    >>> old = pd.DataFrame({"scopus_id": ["85000000001", "85000000002"],
    ...                     "doi": ["10.5555/a", "10.5555/c"]})
    >>> new = pd.DataFrame({"scopus_id": ["85000000001", "85000000033"],
    ...                     "doi": ["10.5555/a", "10.5555/c"]})
    >>> list(sf.diff_records(old, new)["status"])
    ['conflict', 'conflict', 'unchanged']
    """
    # Imported here because combine imports this module for _clean_one.
    from .combine import _record_groups

    old_rows, new_rows = _diff_frame(old, "old"), _diff_frame(new, "new")
    rows = old_rows + new_rows
    later = [False] * len(old_rows) + [True] * len(new_rows)

    # The default de-duplication rule, applied across the two retrievals, so
    # the diff and a merge of the same two sets agree on which records are one.
    keys, _ = _record_groups(
        pd.DataFrame({"scopus_id": [r["scopus_id"] for r in rows],
                      "doi": [r["doi"] for r in rows]}, dtype=object),
        "id_or_shared_doi",
    )
    dois = [_clean_one(r["doi"]) for r in rows]
    doi_keys = [None if d is None else d.lower() for d in dois]
    keyed = [not key.startswith("row:") for key in keys]

    groups: dict[str, dict] = {}
    for i, key in enumerate(keys):
        if not keyed[i]:
            continue
        group = groups.setdefault(key, {"old": [], "new": []})
        group["new" if later[i] else "old"].append(i)

    old_dois = {k for k, side in zip(doi_keys, later, strict=True) if k and not side}
    new_dois = {k for k, side in zip(doi_keys, later, strict=True) if k and side}
    titles = [r["title"] for r in rows]
    years = [r["year"] for r in rows]
    citations = [r["citations"] for r in rows]

    def first(values, indices):
        """The first value the rows at ``indices`` give, or ``None``."""
        return next((values[i] for i in indices if _given(values[i])), None)

    def latest(values, group):
        """The later retrieval's value where it gives one, the earlier one's
        if not."""
        given = first(values, group["new"])
        return given if given is not None else first(values, group["old"])

    out = []
    for key, group in groups.items():
        if group["old"] and group["new"]:
            status = "unchanged"
        else:
            # A record in one retrieval only whose DOI the other retrieval
            # gives to a record of its own. That record is a different one, or
            # the two would share a key and the first would be in both.
            other = new_dois if group["old"] else old_dois
            indices = group["old"] or group["new"]
            clash = any(doi_keys[i] in other for i in indices if doi_keys[i])
            status = "conflict" if clash else ("removed" if group["old"] else "added")
        out.append({
            "status": status,
            # The identifier the record was matched on, which its key carries.
            "scopus_id": key[3:] if key.startswith("id:") else None,
            "doi": latest(dois, group),
            "title": latest(titles, group),
            "year": latest(years, group),
            "citations_old": first(citations, group["old"]),
            "citations_new": first(citations, group["new"]),
        })

    out.sort(key=lambda r: (_RECORD_STATUSES.index(r["status"]), _byte_order(r["doi"]),
                            _byte_order(r["scopus_id"]), _byte_order(r["title"])))
    frame = pd.DataFrame({
        "status": [r["status"] for r in out],
        "scopus_id": pd.array([r["scopus_id"] for r in out], dtype="string"),
        "doi": pd.array([r["doi"] for r in out], dtype="string"),
        "title": pd.array([r["title"] for r in out], dtype="string"),
        "year": pd.array([r["year"] for r in out], dtype="Int64"),
        "citations_old": pd.array([r["citations_old"] for r in out], dtype="Int64"),
        "citations_new": pd.array([r["citations_new"] for r in out], dtype="Int64"),
    }, columns=_RECORD_DIFF_COLUMNS)
    frame.attrs["n_old_without_id_or_doi"] = sum(
        not k and not side for k, side in zip(keyed, later, strict=True))
    frame.attrs["n_new_without_id_or_doi"] = sum(
        not k and side for k, side in zip(keyed, later, strict=True))
    return frame
