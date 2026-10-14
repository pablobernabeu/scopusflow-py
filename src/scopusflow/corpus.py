"""Assemble a minimal, cross-tool corpus with keywords and references."""

from __future__ import annotations

import warnings

import pandas as pd

from .abstract import _is_missing_identifier, scopus_abstract

#: Values accepted by ``keywords``.
_KEYWORD_SOURCES = ("author", "index", "both")


def corpus(
    records: pd.DataFrame,
    by: str = "doi",
    view: str = "FULL",
    cache_dir: str | None = None,
    resume: bool = True,
    keywords: str = "author",
    **kwargs,
) -> pd.DataFrame:
    """Enrich ``records`` (from :func:`scopusflow.fetch.fetch_plan`) with
    keywords (the author keywords by default, or the index keywords Scopus
    assigns) and structured references via Abstract Retrieval, returning a
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
    :func:`scopus_abstract`'s joined `authkeywords` and `idxterms` strings,
    empty when the document has none or the field is unavailable. Only the
    "FULL" view carries author keywords, so under "REF" the references alone
    are requested and every `keywords` entry is empty. `references` carries
    pybliometrics' own native reference field set (see
    :func:`scopus_abstract`'s documentation).

    ``keywords`` chooses which keywords fill that column: "author" (the
    default) for the author keywords, "index" for the index keywords Scopus
    assigns, or "both" for the author keywords followed by each index keyword
    not already among them. The match is on the exact text, so a term that
    differs only in case appears twice. "index" and "both" need
    ``view="FULL"``, since the "REF" response carries no keywords of either
    kind, and raise ``ValueError`` under "REF" before any request. Index
    keywords and author keywords give different co-occurrence results, and
    :func:`scopus_abstract` describes how each is chosen and the entitlement
    each depends on. Either choice costs the same request per record.
    """
    if keywords not in _KEYWORD_SOURCES:
        raise ValueError(
            f"keywords must be one of 'author', 'index' or 'both', not {keywords!r}."
        )
    # Checked here, so that the error names this function's own argument, where
    # scopus_abstract() would name the include value it was passed.
    if keywords != "author" and view != "FULL":
        raise ValueError(
            f'keywords="{keywords}" needs view="FULL", since the REF response '
            "carries no index keywords."
        )
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
    # and every record's keywords come back empty, as in the R twin. Under
    # FULL, only the kinds of keyword asked for are included, which keeps the
    # checkpoints of a default corpus named as before.
    include = ("references",)
    if view == "FULL":
        if keywords in ("author", "both"):
            include += ("keywords",)
        if keywords in ("index", "both"):
            include += ("index_terms",)
    ab = scopus_abstract(
        list(records[by]), by=by, view=view, include=include,
        cache_dir=cache_dir, resume=resume, **kwargs,
    )

    def _split(column):
        if column not in ab:
            return [[] for _ in range(len(ab))]
        return [[] if pd.isna(kw) else [k.strip() for k in kw.split(";")]
                for kw in ab[column]]

    author, index = _split("authkeywords"), _split("idxterms")
    if keywords == "author":
        terms = author
    elif keywords == "index":
        terms = index
    else:
        # dict.fromkeys() keeps the first of each repeated text, as R's
        # unique() does, so the author keywords come first and an index
        # keyword they already hold is not repeated.
        terms = [list(dict.fromkeys(a + i)) for a, i in zip(author, index, strict=True)]

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
        "keywords": terms,
        "references": list(ab["references"]),
    })
    # A freshly constructed frame carries no attrs, so the wrapper that spends
    # the most quota would otherwise be the one reporting none of it.
    out.attrs.update(ab.attrs)
    return out
