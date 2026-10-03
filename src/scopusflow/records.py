"""Normalise pybliometrics results into one stable record schema."""

from __future__ import annotations

import warnings

import pandas as pd

#: The stable column schema for a record table.
RECORD_COLUMNS = [
    "entry_number", "scopus_id", "doi", "title", "authors",
    "year", "date", "publication", "citations", "query",
]

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


def to_records(results, query: str | None = None, view: str | None = None) -> pd.DataFrame:
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
    """
    add_keywords = view == "COMPLETE"
    columns = [*RECORD_COLUMNS, "authkeywords"] if add_keywords else RECORD_COLUMNS
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
