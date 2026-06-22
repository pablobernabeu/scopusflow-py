"""Export a record set to the reference-manager interchange formats RIS and
BibTeX, so a Scopus search carries straight into Zotero, EndNote, Mendeley or a
LaTeX bibliography. Pure and offline; mirrors the R package's as_ris/as_bibtex.
"""

from __future__ import annotations

import re

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


def _bibtex_entry(row, key: str) -> str:
    fields: list[tuple[str, str]] = []
    auth = _authors(row.get("authors"))
    if auth:
        fields.append(("author", " and ".join(_bibtex_escape(a) for a in auth)))
    if _present(row.get("title")):
        fields.append(("title", _bibtex_escape(row.get("title"))))
    if _present(row.get("publication")):
        fields.append(("journal", _bibtex_escape(row.get("publication"))))
    if _present(row.get("year")):
        fields.append(("year", _year(row.get("year"))))
    if _present(row.get("doi")):
        fields.append(("doi", _bibtex_escape(row.get("doi"))))
    if _present(row.get("scopus_id")):
        fields.append(("note", _bibtex_escape("Scopus ID: " + str(row.get("scopus_id")))))

    body = "\n".join(f"  {name} = {{{value}}}," for name, value in fields)
    return f"@article{{{key},\n{body}\n}}"


def _ris_entry(row) -> str:
    lines = ["TY  - JOUR"]
    if _present(row.get("title")):
        lines.append(f"TI  - {_clean(row.get('title'))}")
    for author in _authors(row.get("authors")):
        lines.append(f"AU  - {_clean(author)}")
    if _present(row.get("year")):
        lines.append(f"PY  - {_year(row.get('year'))}")
    if _present(row.get("publication")):
        lines.append(f"JO  - {_clean(row.get('publication'))}")
    if _present(row.get("doi")):
        lines.append(f"DO  - {_clean(row.get('doi'))}")
    if _present(row.get("scopus_id")):
        lines.append(f"N1  - Scopus ID: {_clean(row.get('scopus_id'))}")
    lines.append("ER  - ")
    return "\n".join(lines)


def to_bibtex(records: pd.DataFrame) -> str:
    """Render records as a BibTeX string, one ``@article`` entry per row, with
    citation keys made unique within the export."""
    if not isinstance(records, pd.DataFrame):
        raise ValueError("records must be a pandas DataFrame.")
    rows = [row for _, row in records.iterrows()]
    keys = _disambiguate(
        [_bibtex_key(r.get("authors"), r.get("year"), r.get("scopus_id")) for r in rows]
    )
    return "\n\n".join(_bibtex_entry(r, k) for r, k in zip(rows, keys))


def to_ris(records: pd.DataFrame) -> str:
    """Render records as an RIS string, one ``JOUR`` record per row."""
    if not isinstance(records, pd.DataFrame):
        raise ValueError("records must be a pandas DataFrame.")
    return "\n\n".join(_ris_entry(row) for _, row in records.iterrows())
