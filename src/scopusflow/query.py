"""Build field-tagged, boolean Scopus query strings."""

from __future__ import annotations

import re
import string
import warnings
from collections.abc import Iterator
from typing import NamedTuple

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


#: The text of each problem the offline query checks report. The R twin's
#: ``scopus_query_messages`` holds the same strings, and both are held to
#: ``tests/fixtures/query-checks.json``. They name no function or argument, so
#: they read the same in either language.
_QUERY_MESSAGES: dict[str, str] = {
    "unbalanced": (
        "The query's brackets, quotation marks or braces do not balance. "
        'Every ( needs a matching ), and every " or { needs a closing " or }. '
        "Brackets inside a phrase are read as text."
    ),
    # rscopus issue #50 shows the Search API ignoring LIMIT-TO() without an
    # error: 55 records against 36 for the same limit written as SUBJAREA().
    "refinement": (
        "The query contains LIMIT-TO() or EXCLUDE(), which belong to the Scopus "
        "web interface's refinement panel. The Search API does not apply them, so "
        "the search would run unfiltered (pybliometrics documents LIMIT-TO() as "
        "affecting the display only). Write the limit as a search field instead, "
        "such as DOCTYPE(ar), LANGUAGE(english), SUBJAREA(PSYC), SRCTYPE(j) or "
        "PUBYEAR > 2015."
    ),
    # A live request for TITLE-ABS-KEY(TITLE(x)) failed with HTTP 400 (the R
    # twin's dev/design-notes.md, "Concept and intersection sizing").
    "double_field": (
        "The query already opens with a field tag, so wrapping it in another would "
        "nest one tag inside the other, which the API rejects. Choose no field tag "
        "to send the query as written."
    ),
    # A warning, since how the Search API treats INDEXTERMS() has not been
    # observed. ScopusSearch's own documentation names it, with LIMIT-TO(), as
    # the only advanced-search fields that do not work.
    "indexterms": (
        "The query uses INDEXTERMS(), which pybliometrics documents as not working "
        "through the Search API. KEY() can stand in for it, since it searches "
        "author keywords, index terms, trade names and chemical names together."
    ),
}

#: Matched against the query with its phrases blanked out and its ASCII
#: letters upper-cased, so the operator is found in any case but never inside a
#: phrase. The look-behind stands for ``\b`` at the start of a word. Both twins
#: write it out in ASCII, because Python's ``\b`` and PCRE's differ on a letter
#: such as an accented e.
_REFINEMENT = re.compile(r"(?<![A-Z0-9_])(?:LIMIT-TO|EXCLUDE)\s*\(\s*[A-Z-]+\s*,")
_INDEXTERMS = re.compile(r"(?<![A-Z0-9_])INDEXTERMS\s*\(")
_ASCII_UPPER = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)

#: A query opening with a field tag: a tag written against its bracket, as in
#: ``TITLE(x)``, or one of :data:`FIELD_TAGS` followed by white space and a
#: bracket, as the web interface writes ``TITLE-ABS-KEY ( x )``. Any
#: capitalised word could open a spaced group, as in ``HIV (prevention OR
#: treatment)``, which is a search term and a bracketed group, so the spaced
#: form is recognised only for the common tags.
_OPENS_WITH_TAG = re.compile(
    r"^\s*(?:[A-Z][A-Z-]*\(|(?:" + "|".join(map(re.escape, FIELD_TAGS)) + r")\s+\()"
)


class QuerySyntaxWarning(UserWarning):
    """Issued for a query that may not search what it appears to ask."""


class _QueryProblem(NamedTuple):
    code: str
    level: str
    message: str


def _opens_with_tag(query: str) -> bool:
    """Whether ``query`` already opens with a field tag."""
    return _OPENS_WITH_TAG.match(query) is not None


def _query_problems(query: str, field: str | None = None) -> list[_QueryProblem]:
    """The problems :func:`_check_query` acts on, in a fixed order (PURE).

    Each one reports a query that cannot do what it appears to ask, so none
    fires on legitimate input. A quoted or braced phrase is text, as in
    :func:`_outside_phrases`, so its brackets are never counted, and an
    unclosed phrase runs to the end of the string. The R twin's
    ``scopus_query_problems()`` reports the same codes in the same order.
    """
    masked: list[str] = []
    depth = 0
    balanced = True
    i = 0
    while i < len(query):
        ch = query[i]
        if ch in '"{':
            close = query.find('"' if ch == '"' else "}", i + 1)
            if close < 0:
                balanced = False
                close = len(query) - 1
            masked.append(" " * (close - i + 1))
            i = close + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                balanced = False
            else:
                depth -= 1
        masked.append(ch)
        i += 1
    # Only the ASCII letters change, as R's chartr() changes them.
    text = "".join(masked).translate(_ASCII_UPPER)
    found = {
        "unbalanced": not balanced or depth != 0,
        "refinement": _REFINEMENT.search(text) is not None,
        "double_field": field is not None and _opens_with_tag(query),
        "indexterms": _INDEXTERMS.search(text) is not None,
    }
    return [
        _QueryProblem(code, "warning" if code == "indexterms" else "error",
                      _QUERY_MESSAGES[code])
        for code, hit in found.items() if hit
    ]


def _check_query(query: str, field: str | None = None, *, stacklevel: int = 3) -> None:
    """Check a query offline, before any request.

    ``field`` is the tag the query will be wrapped in, or ``None``. The first
    error found raises ``ValueError``, and a :class:`QuerySyntaxWarning` is
    issued only for a query that raises none. ``stacklevel`` points the warning
    at the caller of the public entry point.
    """
    problems = _query_problems(query, field)
    for problem in problems:
        if problem.level == "error":
            raise ValueError(problem.message)
    for problem in problems:
        warnings.warn(problem.message, QuerySyntaxWarning, stacklevel=stacklevel)


def wrap_field(query: str, field: str | None) -> str:
    """Wrap ``query`` in a field tag, e.g. ``TITLE-ABS-KEY(graphene)``.

    A query that already opens with a field tag raises ``ValueError``, because
    the API rejects one tag nested inside another, as in
    ``TITLE-ABS-KEY(TITLE(x))``.
    """
    if field is None:
        return query
    field = field.strip().upper()
    if not _FIELD_RE.match(field):
        raise ValueError(f"Invalid field tag {field!r}; use letters and hyphens only.")
    if _opens_with_tag(query):
        raise ValueError(_QUERY_MESSAGES["double_field"])
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
