"""Normalise pybliometrics results into one stable record schema."""

from __future__ import annotations

import warnings

import pandas as pd

#: The stable column schema for a record table.
RECORD_COLUMNS = [
    "entry_number", "scopus_id", "doi", "title", "authors",
    "year", "date", "publication", "citations", "query",
]

#: The columns ``fields="extended"`` adds after :data:`RECORD_COLUMNS` (and
#: after ``authkeywords`` under ``COMPLETE``), in order, in either view. Under
#: ``view="COMPLETE"``, an ``abstract`` column follows them. ``open_access`` is
#: a whole number and the rest are text. The R twin's ``scopus_records(fields =
#: "extended")`` adds the same columns, and both suites hold the two to the
#: shared fixture ``extended-entry.json``.
EXTENDED_COLUMNS = [
    "doc_type", "doc_type_description", "source_type", "volume", "issue",
    "pages", "issn", "pubmed_id", "open_access",
]

#: The field of pybliometrics' ``Document`` each extended text column is read
#: from. ``open_access`` comes from ``openaccess`` and ``abstract`` from
#: ``description``, both handled apart, the first because it is a number and
#: the second because only the COMPLETE view carries it.
_EXTENDED_SOURCES = {
    "doc_type": "subtype",
    "doc_type_description": "subtypeDescription",
    "source_type": "aggregationType",
    "volume": "volume",
    "issue": "issueIdentifier",
    "pages": "pageRange",
    "issn": "issn",
    "pubmed_id": "pubmed_id",
}

#: The values ``fields`` takes.
_FIELDS = ("core", "extended")

#: What an author tally of a STANDARD-view harvest says, once per process. The
#: text is the R twin's, word for word, and both suites check it against their
#: copy of the shared fixture ``complete-authors.json``.
_FIRST_AUTHOR_WARNING = (
    "These records were retrieved under the STANDARD view, whose dc:creator "
    "field holds the first author only, so each record names one author and "
    "an author tally counts first authorships. Retrieve with view = "
    '"COMPLETE" for the author list (up to 100 authors per record).'
)

#: Set once the warning above has been given. The R twin gives it once per
#: session, through rlang's ``.frequency = "once"``.
_first_author_warned = False


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _missing(value) -> bool:
    """True when a field carries no value, however the gap is spelled.

    Truthiness will not do: ``bool(float("nan"))`` is ``True``, so a NaN
    identifier would take the "present" branch and be stringified into the
    literal ``"nan"``, which every downstream guard then accepts as a real
    value. A membership test will not do either: ``pd.NA == None`` is itself
    ``NA``, which cannot be evaluated as a boolean. The is_scalar guard keeps
    ``pd.isna`` from returning an array when the value is itself array-like
    (the same reasoning as :func:`scopusflow.diff._clean`).
    """
    return value is None or (pd.api.types.is_scalar(value) and pd.isna(value))


def _scopus_id(eid) -> str | pd._libs.missing.NAType:
    """Strip the ``2-s2.0-`` prefix from an EID, yielding ``NA`` for a missing
    one, where a plausible-looking string would be taken for an identifier."""
    if _missing(eid):
        return pd.NA
    return str(eid).split("2-s2.0-")[-1]


def _citations(cited) -> int | pd._libs.missing.NAType:
    """Coerce a citation count to ``int``, yielding ``NA`` for a missing or
    blank one, and never raises."""
    if _missing(cited) or cited == "":
        return pd.NA
    return int(cited)


def _year(date) -> int | pd._libs.missing.NAType:
    if not date:
        return pd.NA
    head = str(date)[:4]
    return int(head) if head.isdigit() else pd.NA


def _open_access(code) -> int | pd._libs.missing.NAType:
    """The open-access status code as an ``int``, or ``NA`` when it is missing
    or is not a whole number. pybliometrics hands it over as an ``int``, and a
    dict may carry the API's text, ``"0"``, ``"1"`` or ``"2"``."""
    if _missing(code) or (isinstance(code, str) and not code.strip()):
        return pd.NA
    try:
        return int(code)
    except (TypeError, ValueError):
        return pd.NA


def _check_fields(fields) -> None:
    if fields not in _FIELDS:
        raise ValueError("fields must be 'core' or 'extended'.")


def _record_columns(view: str | None, fields: str) -> list[str]:
    """The columns :func:`to_records` builds for ``view`` and ``fields``, in
    order. :data:`RECORD_COLUMNS` come first and ``authkeywords`` follows under
    COMPLETE, then :data:`EXTENDED_COLUMNS` and, under COMPLETE, ``abstract``."""
    columns = list(RECORD_COLUMNS)
    if view == "COMPLETE":
        columns.append("authkeywords")
    if fields == "extended":
        columns += EXTENDED_COLUMNS
        if view == "COMPLETE":
            columns.append("abstract")
    return columns


def _join_authors(names) -> str | None:
    """Join pybliometrics' ``author_names`` as the R twin joins its authors.

    pybliometrics writes each author of the COMPLETE view's list as
    ``"Surname, Given"``, joins them with a bare ``";"``, and writes
    ``"Surname, "`` for an author whose given name is null or empty. Each name
    is stripped, and the comma such a name ends with is dropped. Empty names are
    dropped too, and the rest are joined with ``"; "``, the string the R twin
    builds from the same entry. The result is ``None`` when nobody is named. A
    string joined this way comes back unchanged, so a checkpoint written before
    the join changed can be passed through it on resume.
    """
    if _missing(names):
        return None
    joined = []
    for name in str(names).split(";"):
        name = name.strip()
        if name.endswith(","):
            name = name[:-1].rstrip()
        if name:
            joined.append(name)
    return "; ".join(joined) or None


def _warn_first_author_only(records: pd.DataFrame) -> None:
    """Warn, once per process, that a STANDARD-view harvest names first authors.

    A frame that records no view, such as the bundled harvest or a set read back
    from CSV, cannot be judged and passes in silence.
    """
    global _first_author_warned
    if _first_author_warned or records.attrs.get("view") != "STANDARD":
        return
    _first_author_warned = True
    warnings.warn(_FIRST_AUTHOR_WARNING, stacklevel=3)


def to_records(
    results, query: str | None = None, view: str | None = None, fields: str = "core"
) -> pd.DataFrame:
    """Normalise a pybliometrics ``ScopusSearch().results`` list (named tuples)
    or a list of dicts into a tidy :data:`RECORD_COLUMNS` DataFrame.

    Whatever the query type, the columns are the same, so the downstream DOI,
    diff and analysis helpers can rely on them.

    What ``authors`` holds depends on the view. The Search API's
    ``dc:creator``, pybliometrics' ``creator``, is the first author alone under
    either view, in the indexed form Scopus uses (``"Zhang F."``). The author
    list arrives only under ``view="COMPLETE"``, and pybliometrics builds
    ``author_names`` from it as ``"Surname, Given"`` names. Those names are
    joined here with ``"; "``, as the R twin joins them, and an author whose
    given name is null or empty is written as the surname alone. A row without
    the list falls back to ``creator``. A ``STANDARD`` record therefore names
    its first author, and :func:`top` says so once when it tallies a
    ``STANDARD`` harvest by author. The API lists at most 100 authors per
    record. The R twin builds the same string from the same entry in the common
    case, and the two part company at two edges. pybliometrics builds
    ``author_names`` only when every author object carries both a ``surname``
    and a ``given-name`` key, so where one does not, this twin keeps the first
    author while the R twin lists every author. Where a surname is null or
    empty, pybliometrics writes the given name after a bare comma, and the R
    twin uses the indexed name.

    When ``view="COMPLETE"``, an ``authkeywords`` column is added: the author-
    supplied keywords the Scopus Search API returns under that view, as a
    single string in Scopus's own ``" | "``-delimited form (``None`` when the
    document has none, or when the API omits the field for a given key's
    entitlement: this was observed directly against a live, otherwise
    fully-entitled key during development, on documents that do carry author
    keywords in Scopus itself, so an all-``None`` column is more likely an
    entitlement gap worth raising with your Scopus/Elsevier account contact
    than genuinely absent data). Any other ``view``, including the default
    ``None``, reproduces :data:`RECORD_COLUMNS` exactly, so existing callers
    that never pass ``view`` see no change at all.

    ``fields`` is ``"core"`` by default, which builds the columns above exactly
    as before. ``"extended"`` also keeps fields the Search API sends with every
    record, at no extra quota, which pybliometrics already parses: the
    :data:`EXTENDED_COLUMNS` and, under ``view="COMPLETE"``, an ``abstract``
    column. Elsevier's Search views table lists every one of them under both
    views except the abstract (``dc:description``), which only ``COMPLETE``
    carries. A ``COMPLETE`` harvest therefore returns up to 25 abstracts with
    each request, while :func:`scopusflow.abstract.scopus_abstract` spends one
    request per record from the separate Abstract Retrieval quota.

    ``doc_type`` and ``doc_type_description`` hold the document-type code and
    name Scopus gives the record, such as ``"ar"`` and ``"Article"``. The code
    is the one the ``DOCTYPE()`` search field takes, and Elsevier's search tips
    list the codes with their names: ``ar`` for an article, ``re`` a review,
    ``cp`` a conference paper, ``er`` an erratum and others. A retracted item
    carries ``tb``, which that list leaves out. The Scopus Content Coverage
    Guide (Elsevier, 2023, section 3.1) defines an erratum as a report of an
    error, correction or retraction of a previously published paper, so ``er``
    covers retraction notices as well as corrections. The guide gives an
    article the type Retracted once a retraction notice for it is published.
    These codes are the labels Scopus assigns, and they do not screen a set for
    retractions, since Scopus does not label every retracted item (Ortega and
    Delgado-Quirós, 2024, Scientometrics, 129(7), 3769-3785). Check a set
    against the Retraction Watch database, which Crossref makes openly
    available, before relying on it. Errata can also be left out of the search
    itself with ``AND NOT DOCTYPE(er)``, joined by
    :func:`scopusflow.query.scopus_query`, which brackets the rest of the
    query first, since Scopus applies AND NOT last.

    ``source_type`` holds the source type, such as ``"Journal"``. ``volume``,
    ``issue``, ``pages`` and ``pubmed_id`` are text, and so is ``issn``, the
    print ISSN as Scopus writes it, without the hyphen, so its leading zeros
    survive. ``open_access`` holds the code Scopus sends in its ``openaccess``
    field, as a whole number. Elsevier's Scopus APIs Getting Started Guide
    (2023, section 17) illustrates its values with 0 for a record that is not
    open access, 1 for gold and 2 for green. The column therefore holds a
    status code, which can take values other than 0 and 1. A ``fields`` value
    other than ``"core"`` or ``"extended"`` raises ``ValueError``.
    """
    _check_fields(fields)
    add_keywords = view == "COMPLETE"
    extended = fields == "extended"
    columns = _record_columns(view, fields)
    rows = []
    for i, r in enumerate(results or [], start=1):
        date = _get(r, "coverDate")
        row = {
            "entry_number": i,
            "scopus_id": _scopus_id(_get(r, "eid")),
            "doi": _get(r, "doi"),
            "title": _get(r, "title"),
            # author_names exists only under COMPLETE, and creator is the first author.
            "authors": _join_authors(_get(r, "author_names")) or _get(r, "creator"),
            "year": _year(date),
            "date": date,
            "publication": _get(r, "publicationName"),
            "citations": _citations(_get(r, "citedby_count")),
            "query": query,
        }
        if add_keywords:
            row["authkeywords"] = _get(r, "authkeywords") or pd.NA
        if extended:
            for column, source in _EXTENDED_SOURCES.items():
                row[column] = _get(r, source)
            row["open_access"] = _open_access(_get(r, "openaccess"))
            if add_keywords:
                row["abstract"] = _get(r, "description")
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def top(records: pd.DataFrame, by: str = "source", n: int = 10) -> pd.DataFrame:
    """Tally the most frequent sources or authors in a record set.

    Author strings holding several names are split on ``";"``, so each
    contributor is counted once per record. Only a ``view="COMPLETE"`` harvest
    holds several names, since ``STANDARD`` records carry the first author alone
    (see :func:`to_records`). A tally by author of a harvest whose
    ``attrs["view"]`` is ``"STANDARD"`` therefore counts first authorships, and
    says so with a ``UserWarning``, once per process, in the R twin's words.
    """
    if by == "source":
        values = records["publication"].dropna()
    elif by == "author":
        _warn_first_author_only(records)
        values = (
            records["authors"].dropna().str.split(";").explode().str.strip()
        )
        values = values[values != ""]
    else:
        raise ValueError("by must be 'source' or 'author'.")
    counts = values.value_counts().head(n)
    return counts.rename_axis("value").reset_index(name="n")
