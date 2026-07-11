"""Assemble a minimal, cross-tool corpus with keywords and references."""

from __future__ import annotations

import warnings

import pandas as pd

from .abstract import scopus_abstract


def corpus(
    records: pd.DataFrame,
    by: str = "doi",
    view: str = "FULL",
    cache_dir: str | None = None,
    resume: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """Enrich ``records`` (from :func:`scopusflow.fetch.fetch_plan`) with author
    keywords and structured references via Abstract Retrieval, returning a
    minimal, uniform shape close to what OpenAlex's ``works`` API already
    returns: ``id``, ``title``, ``year``, ``keywords`` (a list of strings per
    row) and ``references`` (a DataFrame of cited works per row). This is
    meant for downstream tools that want to consume Scopus output without
    writing their own parsing layer, for example for keyword co-occurrence or
    citation-network analysis. It does not replace :func:`to_bibtex`/
    :func:`to_ris`, which keep their own established interchange formats.

    ``by`` selects which column of ``records`` ("doi" or "scopus_id") to look
    identifiers up by. ``view`` is passed to :func:`scopus_abstract` and
    defaults to "FULL", which in development returned a complete, correctly
    counted reference list for every document tried, unlike "REF", which
    returned an inconsistent, sometimes-truncated subset (see
    :func:`scopus_abstract`'s documentation for the entitlement each view
    needs). ``cache_dir`` and ``resume`` are passed through unchanged, and are
    worth setting for anything beyond a handful of records, since this
    performs one Abstract Retrieval request per record, against its own,
    smaller weekly quota, separate from Search's.

    A record whose identifier is missing (``NA``/``None``) is dropped, with a
    warning naming how many.

    The `keywords` column here is `list[str]` per row, split out of
    :func:`scopus_abstract`'s joined `authkeywords` string, empty when the
    document has none or the field is unavailable. `references` carries
    pybliometrics' own native reference field set (see
    :func:`scopus_abstract`'s documentation).
    """
    required = {by, "title", "year"}
    if not required.issubset(records.columns):
        raise ValueError(
            f"records must have {sorted(required)} columns "
            "(as fetch_plan() returns)."
        )

    ids = records[by]
    keep = ids.notna()
    n_dropped = int((~keep).sum())
    if n_dropped:
        warnings.warn(
            f"Dropped {n_dropped} record(s) with no usable {by}.",
            stacklevel=2,
        )
    if not keep.any():
        raise ValueError("records has no usable identifiers to look up.")
    records = records.loc[keep].reset_index(drop=True)

    ab = scopus_abstract(
        list(records[by]), by=by, view=view, include=("references", "keywords"),
        cache_dir=cache_dir, resume=resume, **kwargs,
    )

    def _split(kw):
        if pd.isna(kw):
            return []
        return [k.strip() for k in kw.split(";")]

    return pd.DataFrame({
        # The identifier used to look each record up, taken from `records`
        # directly rather than read back from `ab`: scopus_abstract() only
        # echoes the input identifier verbatim in its "doi"/"scopus_id"
        # column on a failed lookup (to keep the failing row identifiable);
        # on success that column holds whatever Scopus itself returns, which
        # is usually but not guaranteedly identical to the input.
        "id": list(records[by]),
        "title": records["title"],
        "year": records["year"],
        "keywords": [_split(kw) for kw in ab["authkeywords"]],
        "references": list(ab["references"]),
    })
