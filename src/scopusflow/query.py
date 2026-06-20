"""Build field-tagged, boolean Scopus query strings."""

from __future__ import annotations

import re

_FIELD_RE = re.compile(r"^[A-Z-]+$")

#: The common Scopus field tags and what each one searches.
FIELD_TAGS: dict[str, str] = {
    "TITLE": "Words in the document title",
    "TITLE-ABS-KEY": "Title, abstract and keywords",
    "TITLE-ABS-KEY-AUTH": "Title, abstract, keywords and author names",
    "ABS": "Abstract text",
    "KEY": "Indexed and author keywords",
    "AUTH": "Author names",
    "AUTHKEY": "Author-supplied keywords",
    "AFFIL": "Affiliation, any part",
    "AFFILORG": "Affiliation organisation name",
    "SRCTITLE": "Source (publication) title",
    "DOI": "Digital Object Identifier",
    "ALL": "All available fields",
}


def wrap_field(query: str, field: str | None) -> str:
    """Wrap ``query`` in a field tag, e.g. ``TITLE-ABS-KEY(graphene)``."""
    if field is None:
        return query
    field = field.strip().upper()
    if not _FIELD_RE.match(field):
        raise ValueError(f"Invalid field tag {field!r}; use letters and hyphens only.")
    return f"{field}({query})"


def scopus_query(*terms: str, op: str = "AND", field: str | None = None) -> str:
    """Combine terms into one Scopus query, optionally field-wrapping each.

    Parameters
    ----------
    *terms:
        One or more non-empty search terms.
    op:
        The boolean operator joining the terms: ``"AND"``, ``"OR"`` or ``"AND NOT"``.
    field:
        An optional field tag applied to every term (see :data:`FIELD_TAGS`).
    """
    if op not in {"AND", "OR", "AND NOT"}:
        raise ValueError("op must be one of 'AND', 'OR', 'AND NOT'.")
    cleaned = [t.strip() for t in terms]
    if not cleaned or any(not t for t in cleaned):
        raise ValueError("All terms must be non-empty.")
    return f" {op} ".join(wrap_field(t, field) for t in cleaned)
