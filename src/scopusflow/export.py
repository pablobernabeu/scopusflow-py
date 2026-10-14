"""Export a record set to the reference-manager interchange formats RIS and
BibTeX, so a Scopus search carries straight into Zotero, EndNote, Mendeley or a
LaTeX bibliography. Both exporters are pure and offline.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

#: Single-pass BibTeX escape map. Applied character by character so the braces
#: introduced by the backslash replacement are not themselves re-escaped.
_BIBTEX_MAP = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _present(value) -> bool:
    """True when a field carries a usable value (not None/NaN/<NA>/blank)."""
    if value is None:
        return False
    try:
        if pd.isna(value):  # covers float nan, pd.NA and NaT uniformly
            return False
    except (TypeError, ValueError):
        pass  # array-like input is not a missing scalar
    return str(value).strip() != ""


def _clean(value) -> str:
    """Fold internal whitespace (incl. embedded newlines) to single spaces."""
    return re.sub(r"\s+", " ", str(value)).strip()


def _authors(value) -> list[str]:
    """Split the ';'-joined authors of one record into a clean list."""
    if not _present(value):
        return []
    return [a.strip() for a in str(value).split(";") if a.strip()]


#: The name rule below, written over a name's shape: each upper-case letter
#: becomes ``U``, each lower-case letter ``l``, and full stops, hyphens and
#: spaces stay as they are. ``re`` has no ``\p{Lu}``, so matching the shape is
#: how this twin applies the R twin's Perl pattern
#: ``^(.+?) +(\p{Lu}\p{Ll}?\.(?:[- ]?\p{Lu}\p{Ll}?\.)*)$`` with the same
#: Unicode classes and the same backtracking.
_INITIALS_SHAPE = re.compile(r"^(.+?) +(Ul?\.(?:[- ]?Ul?\.)*)$")


def _shape(name: str) -> str:
    def one(ch: str) -> str:
        category = unicodedata.category(ch)
        if category == "Lu":
            return "U"
        if category == "Ll":
            return "l"
        return ch if ch in ".- " else "x"

    return "".join(one(ch) for ch in name)


def _name(name: str) -> str:
    """Put a comma before the initials of a comma-free ``Surname I.`` name.

    Under STANDARD, the default view, the authors column holds dc:creator,
    which gives a name as ``Surname I.`` with no comma. BibTeX reads a comma-free
    name as given name first (Patashnik, 1988), so ``Zhang F.`` became family
    name ``F.``, and RIS readers keep it as a single field. An initial is one
    upper-case letter, optionally followed by one lower-case letter (``Yu.``,
    ``Ch.``), then a full stop, and initials may be joined by a hyphen or a
    space. Names with a comma (the COMPLETE view's ``Surname, Given``) and names
    given first are left alone. Both twins are held to
    ``tests/fixtures/author-names.json``. The name is already cleaned, so its
    only whitespace is single spaces.
    """
    if "," in name:
        return name
    match = _INITIALS_SHAPE.match(_shape(name))
    if match is None:
        return name
    return f"{name[:match.end(1)]}, {name[match.start(2):]}"


def _bibtex_name(name: str) -> str:
    """The BibTeX form of a name: :func:`_name`, with run-together initials
    after the comma spaced (``J.R.`` to ``J. R.``), since BibTeX reads ``J.R.``
    as one given name. A hyphen is kept (``J.-P.``)."""
    head, comma, given = _name(name).partition(",")
    if not comma:
        return head
    spaced = []
    for i, ch in enumerate(given):
        spaced.append(ch)
        if ch == "." and i + 1 < len(given) and unicodedata.category(given[i + 1]) == "Lu":
            spaced.append(" ")
    return head + comma + "".join(spaced)


#: A title word split into an opening bracket, the word and closing punctuation.
#: Neither end includes a backslash or a brace, so an escape such as ``\&`` is
#: never split.
_TITLE_WORD = re.compile(r"^([(\[]*)(.*?)([.,:;!?)\]]*)$")


def _bibtex_protect(title: str) -> str:
    """Brace each word of an escaped title that has an upper-case letter after
    its first character (``{CRISPR-Cas9}``, ``{DNA}``, ``{mRNA}:``). BibTeX
    styles lower-case unbraced title letters, so plain.bst printed ``dna``. A
    word capitalised only at its start (``Bayesian``) is left to the style. A
    word that opens with an escape (``\\#MeToo``) is braced twice, because BibTeX
    takes a brace group opening with a backslash for a special character and
    changes the case of the letters inside it (``{\\#metoo}``)."""
    words = []
    for word in title.split(" "):
        lead, core, trail = _TITLE_WORD.match(word).groups()
        if any(unicodedata.category(ch) == "Lu" for ch in core[1:]):
            if core.startswith("\\"):
                core = f"{{{core}}}"
            word = f"{lead}{{{core}}}{trail}"
        words.append(word)
    return " ".join(words)


def _year(value) -> str:
    """Render a (possibly float) year as a bare integer string."""
    return str(int(float(value))) if _present(value) else ""


def _bibtex_escape(value) -> str:
    if not _present(value):
        return ""
    return "".join(_BIBTEX_MAP.get(ch, ch) for ch in _clean(value))


def _bibtex_key(authors, year, scopus_id) -> str:
    auth = _authors(authors)
    surname = re.sub(r"[^A-Za-z0-9]", "", re.split(r"[ ,]", auth[0])[0]).lower() if auth else ""
    if surname:
        return surname + _year(year)
    if _present(scopus_id):
        cleaned = re.sub(r"[^A-Za-z0-9]", "", str(scopus_id))
        if cleaned:
            return "scopus" + cleaned
    return "scopusrecord"


def _disambiguate(keys: list[str]) -> list[str]:
    """Make BibTeX keys unique within an export (biber rejects duplicates)."""
    counts: dict[str, int] = {}
    out: list[str] = []
    for key in keys:
        n = counts.get(key, 0)
        counts[key] = n + 1
        if n == 0:
            out.append(key)
        elif n <= 26:
            out.append(key + chr(ord("a") + n - 1))
        else:
            out.append(f"{key}{n}")
    return out


#: The RIS and BibTeX types of the Scopus codes that are not journal content: a
#: conference paper (cp), a conference review (cr), a book chapter (ch) and a
#: book (bk). Every other code, and a record with none, is a journal article.
#: Zotero's RIS import reads CPAPER and CONF as a conference paper, so both map
#: to ``@inproceedings``, where a conference review is an item in the
#: proceedings. The R twin maps the same codes.
_RIS_TYPES = {"cp": "CPAPER", "cr": "CONF", "ch": "CHAP", "bk": "BOOK"}
_BIBTEX_TYPES = {
    "cp": "inproceedings", "cr": "inproceedings", "ch": "incollection", "bk": "book",
}


def _doc_type(row) -> str | None:
    """The record's Scopus document-type code, lower-cased, or ``None``. Only a
    set retrieved with ``fields="extended"`` carries it."""
    code = row.get("doc_type")
    return _clean(code).lower() if _present(code) else None


def _book_series(row) -> bool:
    """Whether a book's source title names a series. Scopus gives a book in a
    book series that series as its source, and a book outside a series itself,
    which would repeat the title. Zotero reads a book's T2 as its series, and
    BibTeX's ``@book`` has a ``series`` field, so only the first is written."""
    source_type = row.get("source_type")
    return _present(source_type) and _clean(source_type).lower() == "book series"


def _keywords(value) -> list[str]:
    """The author keywords of one record. The Search API's COMPLETE view joins
    them with ``" | "``, and :func:`scopusflow.abstract.scopus_abstract` joins
    its own with ``"; "``. The split is at either, so one rule serves keywords
    from both endpoints."""
    if not _present(value):
        return []
    parts = (part.strip() for part in re.split(r"[|;]", _clean(value)))
    return [part for part in parts if part]


def _page_range(value) -> list[str]:
    """A Scopus page range (``101-117``) as its first and last page, or a page
    that is no range (``e0123456``) on its own. The list is empty when there
    are no pages."""
    if not _present(value):
        return []
    pages = _clean(value)
    match = re.fullmatch(r"([^-]+)-([^-]+)", pages)
    if match:
        ends = [match.group(1).strip(), match.group(2).strip()]
        if all(ends):
            return ends
    return [pages]


def _bibtex_entry(row, key: str) -> str:
    fields: list[tuple[str, str]] = []

    def add(name, value):
        if _present(value):
            fields.append((name, _bibtex_escape(value)))

    entry_type = _BIBTEX_TYPES.get(_doc_type(row), "article")
    auth = _authors(row.get("authors"))
    if auth:
        names = (_bibtex_escape(_bibtex_name(_clean(a))) for a in auth)
        fields.append(("author", " and ".join(names)))
    if _present(row.get("title")):
        fields.append(("title", _bibtex_protect(_bibtex_escape(row.get("title")))))
    # The source goes in the field each entry type reads: the proceedings or the
    # book a paper or chapter appears in, a book's series, or a journal.
    publication = row.get("publication")
    if entry_type in ("inproceedings", "incollection"):
        if _present(publication):
            fields.append(("booktitle", _bibtex_protect(_bibtex_escape(publication))))
    elif entry_type == "book":
        if _book_series(row):
            add("series", publication)
    else:
        add("journal", publication)
    if _present(row.get("year")):
        fields.append(("year", _year(row.get("year"))))
    add("volume", row.get("volume"))
    add("number", row.get("issue"))
    pages = _page_range(row.get("pages"))
    if pages:
        add("pages", "--".join(pages))
    add("issn", row.get("issn"))
    add("doi", row.get("doi"))
    add("abstract", row.get("abstract"))
    keywords = _keywords(row.get("authkeywords"))
    if keywords:
        fields.append(("keywords", ", ".join(_bibtex_escape(k) for k in keywords)))
    if _present(row.get("scopus_id")):
        fields.append(("note", _bibtex_escape("Scopus ID: " + str(row.get("scopus_id")))))

    body = "\n".join(f"  {name} = {{{value}}}," for name, value in fields)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def _ris_entry(row) -> str:
    ris_type = _RIS_TYPES.get(_doc_type(row), "JOUR")
    lines = [f"TY  - {ris_type}"]

    def add(tag, value):
        if _present(value):
            lines.append(f"{tag}  - {_clean(value)}")

    if _present(row.get("title")):
        lines.append(f"TI  - {_clean(row.get('title'))}")
    for author in _authors(row.get("authors")):
        lines.append(f"AU  - {_name(_clean(author))}")
    if _present(row.get("year")):
        lines.append(f"PY  - {_year(row.get('year'))}")
    # T2 is the tag Scopus's own RIS export uses for the source title, and the
    # one reference managers read as the publication title. Zotero reads JO,
    # which this function wrote before, as the journal abbreviation.
    if ris_type != "BOOK" or _book_series(row):
        add("T2", row.get("publication"))
    add("VL", row.get("volume"))
    add("IS", row.get("issue"))
    pages = _page_range(row.get("pages"))
    if pages:
        add("SP", pages[0])
    if len(pages) > 1:
        add("EP", pages[1])
    add("SN", row.get("issn"))
    if _present(row.get("doi")):
        lines.append(f"DO  - {_clean(row.get('doi'))}")
    add("AB", row.get("abstract"))
    for keyword in _keywords(row.get("authkeywords")):
        lines.append(f"KW  - {keyword}")
    add("M3", row.get("doc_type_description"))
    scopus_id = _clean(row.get("scopus_id")) if _present(row.get("scopus_id")) else None
    if scopus_id:
        lines.append(f"AN  - 2-s2.0-{scopus_id}")
    lines.append("DB  - Scopus")
    if scopus_id:
        lines.append(f"N1  - Scopus ID: {scopus_id}")
    lines.append("ER  - ")
    return "\n".join(lines)


def to_bibtex(records: pd.DataFrame) -> str:
    """Render records as a BibTeX string, one entry per row, with citation keys
    made unique within the export.

    A set retrieved with ``fields="extended"`` (see
    :func:`scopusflow.records.to_records`) carries each record's Scopus
    document type, and the entry is typed by it. A conference paper (``cp``)
    or conference review (``cr``) becomes an ``@inproceedings``, a book chapter
    (``ch``) an ``@incollection`` and a book (``bk``) a ``@book``. Every other
    record, and every record of a set retrieved with the core fields, is an
    ``@article``. The source title of a conference paper or chapter goes under
    ``booktitle``, braced as the title is, and a journal article's under
    ``journal``. A book in a book series gives the series under ``series``, and
    a book outside a series, whose source title Scopus gives as the book's own,
    names no source. The entries also carry ``volume``, ``number``, ``pages``
    (``101--117``), ``issn`` and, under ``view="COMPLETE"``, ``abstract`` and
    ``keywords``, joined by commas. A value the record lacks is left out, never
    filled in.

    Names are written family name first, with a comma. A STANDARD-view name
    such as ``Zhang F.``, which BibTeX would read as given name ``Zhang`` and
    family name ``F.``, is written ``Zhang, F.``, and run-together initials are
    spaced (``Kitchin, J. R.``), since BibTeX takes ``J.R.`` for one given name.
    Names that already carry a comma, as under COMPLETE, and names given first
    are written as they stand. The ``authors`` column and the citation keys are
    unchanged. In the title, every word with a capital after its first letter
    is braced (``{DNA}``, ``{CRISPR-Cas9}``), so bibliography styles cannot
    lower-case it."""
    if not isinstance(records, pd.DataFrame):
        raise ValueError("records must be a pandas DataFrame.")
    rows = [row for _, row in records.iterrows()]
    keys = _disambiguate(
        [_bibtex_key(r.get("authors"), r.get("year"), r.get("scopus_id")) for r in rows]
    )
    return "\n\n".join(_bibtex_entry(r, k) for r, k in zip(rows, keys, strict=True))


def to_ris(records: pd.DataFrame) -> str:
    """Render records as an RIS string, one record per row.

    A name ending in initials is written with a comma (``Zhang, F.``), as for
    :func:`to_bibtex`, but run-together initials keep Scopus's spelling. The
    source title goes under ``T2``, the tag Scopus's own RIS export uses and
    reference managers read as the publication title. Each record names the
    database (``DB  - Scopus``) and, when it has an identifier, gives the EID as
    the accession number (``AN  - 2-s2.0-<scopus_id>``).

    Each record is a ``JOUR``, unless a set retrieved with ``fields="extended"``
    gives its Scopus document type. A conference paper is then a ``CPAPER``, a
    conference review a ``CONF``, a book chapter a ``CHAP`` and a book a
    ``BOOK``. A book outside a series has no ``T2``, since Zotero reads a
    book's ``T2`` as its series, and a book in a book series gives the series
    there. The record also carries ``VL``, ``IS``, ``SP`` and ``EP`` from the
    page range, ``SN``, the document type as ``M3`` and, under
    ``view="COMPLETE"``, ``AB`` and one ``KW`` line per author keyword.
    Keywords are split at the ``" | "`` the Search API joins them with and at
    the ``"; "`` :func:`scopusflow.abstract.scopus_abstract` joins its own
    with. A value the record lacks is left out, never filled in."""
    if not isinstance(records, pd.DataFrame):
        raise ValueError("records must be a pandas DataFrame.")
    return "\n\n".join(_ris_entry(row) for _, row in records.iterrows())
