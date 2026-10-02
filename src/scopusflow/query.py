"""Build field-tagged, boolean Scopus query strings."""

from __future__ import annotations

import re
from collections.abc import Iterator

_FIELD_RE = re.compile(r"^[A-Z-]+$")

#: A top-level word that lets ``expr AND clause`` regroup. Scopus's search tips
#: process OR, then AND, then AND NOT, so a clause appended after a top-level
#: AND NOT falls inside the negation. Under the order Elsevier announced for
#: 2026 (AND NOT, AND, OR), a top-level OR keeps the clause from every operand
#: but the last. The proximity operators W/n and PRE/n are matched too, as is
#: lower case, since a redundant pair of brackets costs nothing and a missed
#: operator loses the limit for part of the query.
_GROUPING_OPERATOR = re.compile(r"^(OR|NOT|W/\d+|PRE/\d+)$", re.IGNORECASE)

#: A field tag opening a bracket, as in ``TITLE-ABS-KEY(``.
_TAG_OPEN = re.compile(r"[A-Z][A-Z-]*\(")

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


def _outside_phrases(expr: str) -> Iterator[tuple[int, str | None]]:
    """Yield ``(index, char)`` for each character of ``expr`` outside a quoted
    ``"..."`` or braced ``{...}`` phrase, and ``(index, None)`` once for each
    phrase. Brackets and operator words inside a phrase are text, never syntax.
    An unclosed phrase runs to the end of the string.
    """
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in '"{':
            close = expr.find('"' if ch == '"' else "}", i + 1)
            yield i, None
            i = len(expr) if close < 0 else close + 1
        else:
            yield i, ch
            i += 1


def _top_level_tokens(expr: str) -> list[str]:
    """The words of ``expr`` that sit outside every bracket and phrase.

    A bracket or a phrase ends a word as whitespace does, so an operator
    written against one, as in ``TITLE(a)OR TITLE(b)``, is still found.
    """
    tokens: list[str] = []
    word = ""
    depth = 0
    for _, ch in _outside_phrases(expr):
        if depth == 0 and (ch is None or ch.isspace() or ch in "()"):
            if word:
                tokens.append(word)
            word = ""
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and ch is not None and not ch.isspace():
            word += ch
    if word:
        tokens.append(word)
    return tokens


def _needs_group(expr: str) -> bool:
    """Whether appending ``AND <clause>`` to ``expr`` could change what it means."""
    return any(_GROUPING_OPERATOR.match(token) for token in _top_level_tokens(expr))


def _and_clause(expr: str, clause: str) -> str:
    """Append ``AND clause`` to ``expr``, bracketing ``expr`` only when needed.

    The year limit is written into the query string, never passed through
    pybliometrics' ``date`` argument. pybliometrics keys its download cache on
    the query string alone, so year cells sent through ``date`` would share one
    cache entry. The brackets are conditional so that a query without a
    top-level OR, AND NOT or proximity operator is sent exactly as before and
    keeps its checkpoints and its pybliometrics cache. Only the strings that
    were already regrouped change.
    """
    if _needs_group(expr):
        return f"({expr}) AND {clause}"
    return f"{expr} AND {clause}"


def _first_group_end(expr: str) -> int | None:
    """The index of the bracket closing the first opening bracket of ``expr``,
    ignoring brackets inside phrases, or ``None`` when it never closes."""
    depth = 0
    for i, ch in _outside_phrases(expr):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                return i
    return None


def _is_one_operand(term: str) -> bool:
    """Whether ``term`` already binds as a single operand: one quoted or braced
    phrase, one bracketed group or one field-tagged group."""
    last = len(term) - 1
    if term[0] in '"{':
        return term.find('"' if term[0] == '"' else "}", 1) == last
    if term[0] == "(" or _TAG_OPEN.match(term):
        return _first_group_end(term) == last
    return False


def _group_term(term: str) -> str:
    """Bracket a term of several words, so a join treats it as one operand.

    Scopus joins the words of an unquoted term with AND, so joined bare,
    ``machine learning OR deep learning`` reads as
    ``machine AND (learning OR deep) AND learning``. The R twin's
    ``scopus_group_term()`` applies the same rule, and both are held to the
    expected strings in ``tests/fixtures/query-grouping.json``.
    """
    if not any(ch.isspace() for ch in term) or _is_one_operand(term):
        return term
    return f"({term})"


def scopus_query(*terms: str, op: str = "AND", field: str | None = None) -> str:
    """Combine terms into one Scopus query, optionally field-wrapping each.

    Each term is trimmed and, given ``field``, wrapped in that tag, whose
    brackets hold the term together. Without a field tag, a term of several
    words is put in brackets before two or more terms are joined, because
    Scopus joins the words of an unquoted term with AND. Joined bare,
    ``machine learning OR deep learning`` would read as
    ``machine AND (learning OR deep) AND learning``.
    ``scopus_query("machine learning", "deep learning", op="OR")`` therefore
    gives ``(machine learning) OR (deep learning)``. A term that is already one
    operand is left as written: a quoted ``"..."`` phrase, a braced ``{...}``
    phrase, a bracketed group or a single field-tagged group such as
    ``TITLE(deep learning)``. Single words are never bracketed, so
    ``scopus_query("CRISPR", "Cas9", op="OR")`` stays ``CRISPR OR Cas9``, and a
    query composed by an earlier call keeps its meaning when it is joined again.

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
    if field is None and len(cleaned) > 1:
        cleaned = [_group_term(t) for t in cleaned]
    return f" {op} ".join(wrap_field(t, field) for t in cleaned)
