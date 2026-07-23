"""Size a set of concepts and their intersections.

Counts how many records match each of a named set of concepts, and each
requested intersection of those concepts, giving a size-of-field snapshot that
shows where a study or a niche sits within a wider literature. Like
:func:`scopusflow.count.scopus_count`, it retrieves totals only, never records,
so a whole landscape costs one request per row of the result. This is the twin
of the R package's ``scopus_intersections()``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from .count import scopus_count
from .query import wrap_field

logger = logging.getLogger("scopusflow")

#: A value already reading as a field-tagged expression, e.g. ``TITLE(x)``.
_TAGGED_RE = re.compile(r"^[A-Z][A-Z-]*\(")


def wrap_concept(term: str, field: str | None) -> str:
    """Wrap a bare term in ``field``, but pass a complete field-tagged
    expression through untouched.

    Wrapping an already-tagged value a second time (for example
    ``TITLE-ABS-KEY(TITLE(x))``) is malformed and the API rejects it, so a value
    that already opens with a field tag such as ``TITLE(virtual reality)`` is
    used exactly as given.
    """
    term = term.strip()
    if _TAGGED_RE.match(term):
        return term
    return wrap_field(term, field)


def _intersection_rows(
    concepts: Mapping[str, str],
    intersections: Sequence[Sequence[str]] | None,
    abbrev: Mapping[str, str] | None,
    sep: str,
    field: str | None,
) -> pd.DataFrame:
    """Assemble every row's label, query, type, size and members (PURE, offline).

    Kept separate from the counting so the query-building logic is testable
    without an API key, and so a label collision is caught before any request.
    """
    if not isinstance(concepts, Mapping) or len(concepts) == 0:
        raise ValueError(
            "concepts must be a non-empty mapping of label -> term or query."
        )
    labels = list(concepts)
    for label, term in concepts.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Every concept label must be a non-empty string.")
        if not isinstance(term, str) or not term.strip():
            raise ValueError(
                f"Concept {label!r} must map to a non-empty term or query."
            )

    if not isinstance(sep, str) or not sep:
        raise ValueError("sep must be a non-empty string.")

    if abbrev is not None:
        if not isinstance(abbrev, Mapping) or len(abbrev) == 0:
            raise ValueError(
                "abbrev must be a non-empty mapping of concept label -> short label."
            )
        unknown = [k for k in abbrev if k not in labels]
        if unknown:
            raise ValueError(
                "abbrev keys not among the concept labels: " + ", ".join(unknown) + "."
            )

    combos: list[list[str]] = []
    if intersections is not None:
        groups: list[Any] = list(intersections)
        # A single intersection may be given as a flat sequence of labels.
        if groups and all(isinstance(m, str) for m in groups):
            groups = [groups]
        for combo in groups:
            members = [str(m) for m in combo]
            if len(members) < 2 or len(set(members)) != len(members):
                raise ValueError(
                    "Each intersection must name two or more distinct concept labels."
                )
            unknown = [m for m in members if m not in labels]
            if unknown:
                raise ValueError(
                    "Intersection members not among the concept labels: "
                    + ", ".join(unknown) + "."
                )
            combos.append(members)

    queries = {label: wrap_concept(term, field) for label, term in concepts.items()}

    def short(label: str) -> str:
        return abbrev[label] if abbrev is not None and label in abbrev else label

    rows: list[dict] = [
        {
            "label": label,
            "query": queries[label],
            "type": "concept",
            "size": 1,
            "members": label,
        }
        for label in labels
    ]
    for combo in combos:
        rows.append(
            {
                "label": sep.join(short(m) for m in combo),
                "query": " AND ".join(f"({queries[m]})" for m in combo),
                "type": "intersection",
                "size": len(combo),
                "members": "; ".join(combo),
            }
        )

    out = pd.DataFrame(rows, columns=["label", "query", "type", "size", "members"])
    if out["label"].duplicated().any():
        raise ValueError(
            "The concept and intersection labels must be distinct; adjust abbrev or sep."
        )
    return out


def scopus_intersections(
    concepts: Mapping[str, str],
    intersections: Sequence[Sequence[str]] | None = None,
    abbrev: Mapping[str, str] | None = None,
    sep: str = " × ",
    years: Sequence[int] | None = None,
    field: str | None = None,
    view: str = "STANDARD",
    verbose: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """Count each concept and each requested intersection of concepts.

    Parameters
    ----------
    concepts:
        A mapping whose keys are display labels and whose values are search terms
        (wrapped in ``field`` when one is given) or complete field-tagged query
        expressions such as ``"TITLE(virtual reality)"`` (used as-is). The labels
        must be unique.
    intersections:
        An optional sequence of sequences, each naming two or more distinct
        concept labels whose intersection should be counted, for example
        ``[["A", "B"], ["A", "B", "C"]]``. A single flat sequence of labels is
        taken as one intersection.
    abbrev:
        An optional mapping of short labels, keyed by concept label and used only
        when composing intersection labels, so those rows stay readable while the
        concept rows keep their full names.
    sep:
        The separator joining member labels in an intersection label; defaults to
        a multiplication sign between spaces.
    years:
        An optional inclusive year range applied to every count.
    field:
        An optional Scopus field tag wrapped around each concept value that is not
        already a complete field-tagged expression (see
        :data:`scopusflow.query.FIELD_TAGS`).
    view:
        The Scopus search view, ``"STANDARD"`` or ``"COMPLETE"``.
    verbose:
        When ``True``, progress is reported on the ``scopusflow`` logger.

    Returns
    -------
    pandas.DataFrame
        One row per concept and per intersection, with columns ``label``,
        ``query``, ``n`` (the count, as a nullable integer), ``type``
        (``"concept"`` or ``"intersection"``), ``size`` (the number of member
        concepts) and ``members`` (the member labels, joined by ``"; "``). The
        ``years`` restriction, when given, is stored in ``df.attrs["years"]``.

    Notes
    -----
    This performs one count request per concept and per intersection, so it needs
    a valid API key and internet access, exactly as
    :func:`scopusflow.count.scopus_count` does.
    """
    out = _intersection_rows(concepts, intersections, abbrev, sep, field)

    ys = sorted({int(y) for y in years}) if years else None
    if verbose:
        n_inter = int((out["type"] == "intersection").sum())
        logger.info(
            "Counting %d queries (%d intersection%s).",
            len(out), n_inter, "" if n_inter == 1 else "s",
        )

    counts: list[int] = []
    for label, query in zip(out["label"], out["query"], strict=True):
        if verbose:
            logger.info("Counting %s", label)
        counts.append(scopus_count(query, years=ys, view=view, **kwargs))
    out["n"] = pd.array(counts, dtype="Int64")

    out = out[["label", "query", "n", "type", "size", "members"]]
    out.attrs["years"] = ys
    return out
