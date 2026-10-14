"""Assemble a minimal, cross-tool corpus with keywords and references, and
write it in theoryforge's corpus schema."""

from __future__ import annotations

import json
import numbers
import re
import string
import warnings
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ._provenance import as_datetime, as_plan
from .abstract import _is_missing_identifier, scopus_abstract
from .diff import _clean as _clean_dois
from .report import _expression

#: Values accepted by ``keywords``.
_KEYWORD_SOURCES = ("author", "index", "both")

#: The columns the corpus writer reads, as corpus() returns them.
_CORPUS_COLUMNS = ("id", "title", "year", "keywords", "references")

#: DOIs are case-insensitive over ASCII letters only (DOI Handbook, section
#: 2.4), so the writer folds no other letter.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

#: A DOI: "10.", a registrant code of digits, perhaps with dotted parts, a
#: slash and a suffix. It tells a corpus looked up by DOI from one looked up by
#: Scopus identifier.
_DOI_SHAPE = re.compile(r"10\.[0-9]+(\.[0-9]+)*/.")

#: A Scopus identifier, once a ``SCOPUS_ID:`` or EID prefix is removed.
_SCOPUS_ID = re.compile(r"[0-9]+")
_SCOPUS_ID_PREFIX = re.compile(r"^(SCOPUS_ID:|2-s2\.0-)")


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
    returns: ``id``, ``scopus_id``, ``title``, ``year``, ``keywords`` (a list
    of strings per row) and ``references`` (a DataFrame of cited works per
    row). :func:`write_corpus` writes the result in theoryforge's corpus
    schema. This is meant for downstream tools that want to consume Scopus
    output without writing their own parsing layer, for example for keyword
    co-occurrence or citation-network analysis. It does not replace
    :func:`to_bibtex`/
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
    ``result.attrs["quota"]``. Three more ``attrs`` carry what
    :func:`write_corpus` records of the corpus's provenance. ``query`` is a
    list of the field-wrapped search expression of each cell of the records'
    plan, or, for records without a plan, of the distinct values of their own
    ``query`` column. ``retrieved_at`` is when the search that found the
    records ran, as the records hold it, and ``keywords`` is the kind of
    keyword chosen. ``query`` and ``retrieved_at`` are ``None`` when
    ``records`` carries neither.

    ``scopus_id`` is the document's own Scopus identifier, as Abstract
    Retrieval gives it, or the ``scopus_id`` of ``records`` where Abstract
    Retrieval gives none, as for a failed lookup, and missing when neither
    has one.

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

    # The search behind the records, read before they are subset: the
    # field-wrapped query each cell sent, as the search record states it, and
    # when the search ran.
    expression = _expression(records, as_plan(records.attrs.get("plan")))
    retrieved_at = records.attrs.get("retrieved_at")

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

    # The document's own identifier, from Abstract Retrieval. A failed lookup
    # leaves it missing there, and the records' own identifier fills the gap
    # where they carry one, as in the R twin.
    scopus_id = [_text(v) for v in ab["scopus_id"]]
    if "scopus_id" in records.columns:
        scopus_id = [s if s is not None else _text(r)
                     for s, r in zip(scopus_id, records["scopus_id"], strict=True)]

    out = pd.DataFrame({
        # The identifier used to look each record up, taken from `records`
        # directly, and never read back from `ab`: scopus_abstract() only
        # echoes the input identifier verbatim in its "doi"/"scopus_id"
        # column on a failed lookup (to keep the failing row identifiable);
        # on success that column holds whatever Scopus itself returns, which
        # is usually but not guaranteedly identical to the input.
        "id": list(records[by]),
        "scopus_id": pd.Series([pd.NA if s is None else s for s in scopus_id], dtype=object),
        "title": records["title"],
        "year": records["year"],
        "keywords": terms,
        "references": list(ab["references"]),
    })
    # A freshly constructed frame carries no attrs, so the wrapper that spends
    # the most quota would otherwise be the one reporting none of it.
    out.attrs.update(ab.attrs)
    # The provenance write_corpus() records, as JSON-safe values: the
    # expressions as a list, the time as the records hold it.
    out.attrs["query"] = expression
    out.attrs["retrieved_at"] = retrieved_at
    out.attrs["keywords"] = keywords
    return out


def to_theoryforge_corpus(corpus: pd.DataFrame, id: str) -> dict:
    """The corpus as a document in theoryforge's corpus schema, as a dict.

    Turns a :func:`corpus` result into the literature corpus that
    theoryforge's ``read_corpus``, ``litmap`` and ``landscape`` read, following
    the corpus schema theoryforge publishes (``schema/corpus.schema.json`` in
    its repository). :func:`write_corpus` writes the same document to a JSON
    file. Neither imports theoryforge, and neither makes a request.

    theoryforge compares references as exact strings, so each cited work gets
    one key across the whole corpus, its Scopus identifier, as
    ``scopus:<id>``. Scopus gives a cited work's DOI in some bibliographies
    only, and in different cases. A key built from the DOI wherever there is
    one would therefore split one work into several nodes and lose
    the co-citation edges between them. A reference that carries only a DOI
    takes the Scopus identifier that a document or reference
    elsewhere in the corpus pairs with the same DOI, the documents' own
    identifiers counting first. A DOI that nothing pairs with is keyed as
    ``doi:<doi>``, without its resolver prefix and with its ASCII letters
    lower-cased, since DOIs are case-insensitive over ASCII (DOI Handbook,
    section 2.4). A reference with neither is dropped, and a ``UserWarning``
    says how many. Each document is keyed the same way, from its
    ``scopus_id`` or else from an ``id`` that is a DOI or a Scopus
    identifier, so a citation of a document in the corpus and the document
    itself share one key. A document with neither raises ``ValueError``.

    Keywords are trimmed, lower-cased with ``str.lower()`` and made unique,
    keeping the first of each, and empty ones are dropped, so ``"Graphene"``
    and ``"graphene "`` count as one keyword. The R twin lower-cases with
    ``tolower()``. The two agree on the Latin, Greek and Cyrillic letters in
    common use and differ on a few special cases, such as the Turkish capital
    I with a dot and a capital sigma ending a word, which Python writes as a
    final sigma. A missing year is written as ``null``,
    whether it is ``None``, ``NaN`` or ``pd.NA``, and a whole-number year of
    any dtype as a plain integer. A missing title is left out, since the
    schema admits a null year and not a null title.

    The document also carries a ``provenance`` object, which the schema
    admits beside its own fields: ``source`` (``"Scopus via scopusflow
    <version>"``), ``query``, ``retrieved_at`` (in UTC, as
    ``YYYY-MM-DDTHH:MM:SSZ``), ``keywords``, ``n_records``,
    ``n_references_dropped`` and ``n_records_without_keywords``. ``query``,
    ``retrieved_at`` and ``keywords`` come from the ``attrs`` that
    :func:`corpus` attaches, and are ``None`` (``null``) when the frame lacks
    them. ``query`` is a string, or a list of strings when the records were
    searched with several expressions. Author keywords can come back empty
    under some entitlements (see :func:`scopus_abstract`), which leaves
    theoryforge's keyword themes empty whatever the writer does, and
    ``n_records_without_keywords`` shows when that happened.

    ``id`` is a non-empty string naming the corpus, written as its top-level
    ``id``. It is required, since a :func:`corpus` result carries no name of
    its own. Returns a dict with ``id``, ``provenance``, ``records`` and
    ``schema_version`` (``"1.0"``).
    """
    if not isinstance(id, str) or not id.strip():
        raise ValueError(
            "id must be a non-empty string naming the corpus, since a corpus() "
            "result carries no name of its own."
        )
    if not isinstance(corpus, pd.DataFrame) or not set(_CORPUS_COLUMNS) <= set(corpus.columns):
        raise ValueError(
            f"corpus must be a DataFrame with {list(_CORPUS_COLUMNS)} columns "
            "(as corpus() returns)."
        )
    n = len(corpus)

    # Each document's own identifiers: its scopus_id, else an id that is a
    # Scopus identifier (a corpus looked up by scopus_id), and an id that is
    # a DOI (a corpus looked up by DOI).
    ids = [_text(v) for v in corpus["id"]]
    record_doi = [d if d is not None and _DOI_SHAPE.match(d) else None
                  for d in map(_doi, ids)]
    given = corpus["scopus_id"] if "scopus_id" in corpus.columns else [None] * n
    record_sid = [
        _sid(s) or (_sid(i) if d is None else None)
        for s, i, d in zip(given, ids, record_doi, strict=True)
    ]
    cited = [_cited(refs) for refs in corpus["references"]]

    # Every document and reference carrying both says which identifier a DOI
    # belongs to. The first pair met wins, the documents' own coming first.
    sid_of_doi: dict[str, str] = {}
    pairs = list(zip(record_sid, record_doi, strict=True))
    pairs += [pair for refs in cited for pair in refs]
    for sid, doi in pairs:
        if sid is not None and doi is not None:
            sid_of_doi.setdefault(doi, sid)

    def key(sid, doi):
        sid = sid or sid_of_doi.get(doi)
        if sid is not None:
            return f"scopus:{sid}"
        return f"doi:{doi}" if doi is not None else None

    record_key = [key(s, d) for s, d in zip(record_sid, record_doi, strict=True)]
    unkeyed = [i for i, k in enumerate(record_key) if k is None]
    if unkeyed:
        shown = ", ".join(str(i) for i in unkeyed[:10])
        raise ValueError(
            f"{len(unkeyed)} record(s) of corpus (row {shown}, counting from 0) "
            "carry neither a Scopus identifier nor a DOI to key on."
        )

    dropped = 0
    records = []
    for row, own_key, refs in zip(corpus.itertuples(index=False), record_key, cited,
                                  strict=True):
        keys = [key(s, d) for s, d in refs]
        dropped += sum(k is None for k in keys)
        record = {
            "id": own_key,
            "keywords": _keywords(row.keywords),
            "references": list(dict.fromkeys(k for k in keys if k is not None)),
        }
        if isinstance(row.title, str) and row.title.strip():
            record["title"] = row.title.strip()
        record["year"] = _year(row.year)
        records.append(record)
    if dropped:
        warnings.warn(
            f"Dropped {dropped} reference(s) with neither a Scopus identifier nor "
            "a DOI, which no key can name.",
            UserWarning,
            stacklevel=2,
        )

    # Imported here: __version__ is bound only once the package's own imports,
    # this module's among them, have returned.
    from . import __version__

    kind = corpus.attrs.get("keywords")
    provenance = {
        "keywords": kind if isinstance(kind, str) else None,
        "n_records": n,
        "n_records_without_keywords": sum(not r["keywords"] for r in records),
        "n_references_dropped": dropped,
        "query": _query(corpus.attrs.get("query")),
        "retrieved_at": _utc(corpus.attrs.get("retrieved_at")),
        "source": f"Scopus via scopusflow {__version__}",
    }
    return {"id": id, "provenance": provenance, "records": records, "schema_version": "1.0"}


def write_corpus(corpus: pd.DataFrame, path, id: str) -> dict:
    """Write the corpus to ``path`` as JSON in theoryforge's corpus schema.

    The document is :func:`to_theoryforge_corpus`'s, which describes the keys,
    the keywords and the ``provenance`` block, and it is returned too. The
    file is UTF-8, with no escaping beyond what JSON requires, sorted keys, no
    spaces between tokens and one line feed at the end, so the same corpus
    gives the same bytes from either twin. ``allow_nan=False`` stops the write
    before any file is opened should a ``NaN`` reach the document, since JSON
    has no such value. ``path`` is written exactly as given, and its parent
    directory is assumed to exist already.
    """
    doc = to_theoryforge_corpus(corpus, id)
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    Path(path).write_bytes((text + "\n").encode("utf-8"))
    return doc


def _text(value) -> str | None:
    """An identifier as stripped text, ``None`` for a missing or blank one. A
    number is written whole (85000000001, not 8.5e+10), and one that is not
    whole is no identifier, as in the R twin."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (bool, np.bool_)) or _is_missing_identifier(value):
        return None
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        return str(int(number)) if np.isfinite(number) and number.is_integer() else None
    return None


def _sid(value) -> str | None:
    """A Scopus identifier as digits, without a ``SCOPUS_ID:`` or EID prefix,
    or ``None``."""
    text = _text(value)
    if text is None:
        return None
    text = _SCOPUS_ID_PREFIX.sub("", text)
    return text if _SCOPUS_ID.fullmatch(text) else None


def _doi(value) -> str | None:
    """A DOI cleaned as :func:`extract_dois` cleans one, with its ASCII
    letters lower-cased, or ``None``."""
    text = _text(value)
    cleaned = _clean_dois([text]) if text is not None else []
    return cleaned[0].translate(_ASCII_LOWER) if cleaned else None


def _cited(refs) -> list[tuple[str | None, str | None]]:
    """One (Scopus identifier, DOI) pair per cited work, none for a document
    without a bibliography."""
    if not isinstance(refs, pd.DataFrame) or refs.empty:
        return []
    ids = refs["id"] if "id" in refs.columns else [None] * len(refs)
    dois = refs["doi"] if "doi" in refs.columns else [None] * len(refs)
    return [(_sid(i), _doi(d)) for i, d in zip(ids, dois, strict=True)]


def _keywords(value) -> list[str]:
    """Keywords trimmed, lower-cased, non-empty and unique, the first of each
    kept. A list per row, as corpus() gives it, or an array, as a frame read
    back from parquet holds it. A lone string is one keyword, as in R."""
    if isinstance(value, str):
        value = [value]
    elif not isinstance(value, (list, tuple, np.ndarray, pd.Series)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            folded = item.strip().lower()
            if folded and folded not in out:
                out.append(folded)
    return out


def _year(value) -> int | None:
    """A year as a plain int, or ``None``, written as null, for a missing one
    or one that is not a whole number. ``json`` writes neither ``pd.NA`` nor
    NumPy's integers."""
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        if pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if np.isfinite(number) and number.is_integer() else None


def _query(value):
    """The search expressions as JSON writes them: one string, a list of
    several, or ``None`` when none is recorded."""
    if isinstance(value, str):
        return value
    if not isinstance(value, (list, tuple)):
        return None
    texts = [str(v) for v in value if isinstance(v, str)]
    if not texts:
        return None
    return texts[0] if len(texts) == 1 else texts


def _utc(value) -> str | None:
    """A retrieval time in UTC, ``YYYY-MM-DDTHH:MM:SSZ``, as theoryforge's
    schema writes one, or ``None`` when the corpus records none. fetch_plan()
    records it as ISO 8601 text, and a datetime set by hand is read too."""
    try:
        stamp = as_datetime(value)
    except ValueError:
        return None
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
