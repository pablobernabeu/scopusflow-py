"""Assemble a minimal, cross-tool corpus with keywords and references."""

from __future__ import annotations

import warnings

import pandas as pd

from .abstract import _is_missing_identifier, scopus_abstract


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
    defaults to "FULL", which returns a document's whole bibliography in one
    request. "REF" serves it about 40 references per request, and
    pybliometrics pages REF itself, so the list still arrives whole, at a cost
    of ``ceil(N / 40)`` requests for N references (see
    :func:`scopus_abstract`'s documentation for the entitlement each view
    needs). ``cache_dir`` and ``resume`` are passed through unchanged, and are
    worth setting for anything beyond a handful of records, since this
    performs at least one Abstract Retrieval request per record, against its
    own, smaller weekly quota, separate from Search's. What that cost came to
    is carried through from :func:`scopus_abstract`: the number of requests
    made, counting each document once, and the most recently parsed
    remaining-quota figure are attached as ``result.attrs["n_requests"]`` and
    ``result.attrs["quota"]``.

    A record whose identifier is missing (``NA``/``None``) or blank is
    dropped, with a warning naming how many.

    The `keywords` column here is `list[str]` per row, split out of
    :func:`scopus_abstract`'s joined `authkeywords` string, empty when the
    document has none or the field is unavailable. Only the "FULL" view
    carries author keywords, so under "REF" the references alone are
    requested and every `keywords` entry is empty. `references` carries
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
    # Blank text counts as missing too, since scopus_abstract() refuses both.
    keep = ~ids.map(_is_missing_identifier).astype(bool)
    n_dropped = int((~keep).sum())
    if n_dropped:
        warnings.warn(
            f"Dropped {n_dropped} record(s) with no usable {by}.",
            stacklevel=2,
        )
    if not keep.any():
        raise ValueError("records has no usable identifiers to look up.")
    records = records.loc[keep].reset_index(drop=True)

    # The REF response carries no author keywords (scopus_abstract() refuses
    # the combination), so under that view only the references are requested
    # and every record's keywords come back empty, as in the R twin.
    include = ("references", "keywords") if view == "FULL" else ("references",)
    ab = scopus_abstract(
        list(records[by]), by=by, view=view, include=include,
        cache_dir=cache_dir, resume=resume, **kwargs,
    )
    authkeywords = ab["authkeywords"] if "authkeywords" in ab else [pd.NA] * len(ab)

    def _split(kw):
        if pd.isna(kw):
            return []
        return [k.strip() for k in kw.split(";")]

    out = pd.DataFrame({
        # The identifier used to look each record up, taken from `records`
        # directly, and never read back from `ab`: scopus_abstract() only
        # echoes the input identifier verbatim in its "doi"/"scopus_id"
        # column on a failed lookup (to keep the failing row identifiable);
        # on success that column holds whatever Scopus itself returns, which
        # is usually but not guaranteedly identical to the input.
        "id": list(records[by]),
        "title": records["title"],
        "year": records["year"],
        "keywords": [_split(kw) for kw in authkeywords],
        "references": list(ab["references"]),
    })
    # A freshly constructed frame carries no attrs, so the wrapper that spends
    # the most quota would otherwise be the one reporting none of it.
    out.attrs.update(ab.attrs)
    return out
