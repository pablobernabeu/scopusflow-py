"""Compare how comparison topics co-occur with a reference topic over time.

For each year and comparison term, the records matching the reference combined
with that term are expressed as a percentage of the records matching the
reference alone, revealing which sub-topics grow or shrink within a literature.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import pandas as pd

from ._pyb import require_init, result_size
from .plan import _check_years
from .query import _and_clause, _check_query, wrap_field

logger = logging.getLogger("scopusflow")

#: The stable column schema for a comparison table.
COMPARISON_COLUMNS = [
    "query", "query_type", "abridged_query", "year", "n",
    "reference_n", "comparison_percentage", "average_comparison_percentage",
]


def _safe_int(value):
    return None if value is None or pd.isna(value) else int(value)


def _comparison_block(query: str, query_type: str, abridged: str,
                      years: Sequence[int], counts: dict, ref_counts: dict) -> list[dict]:
    """Assemble the per-year rows for one query (PURE, offline). A year whose
    reference count is zero or unavailable yields ``None`` for that year's share,
    and the average rests on the years that are available."""
    rows = []
    total_n = 0
    total_ref = 0
    for year in years:
        n = counts.get(year)
        ref = ref_counts.get(year)
        if ref is None or pd.isna(ref) or ref == 0 or n is None or pd.isna(n):
            pct = None
        else:
            pct = 100.0 * n / ref
        rows.append({
            "query": query, "query_type": query_type, "abridged_query": abridged,
            "year": int(year), "n": _safe_int(n), "reference_n": _safe_int(ref),
            "comparison_percentage": pct,
        })
        # Both totals are taken over the same years. Summing the numerator over
        # years the denominator drops would inflate the average above every
        # per-year share in the same frame, and that average also orders the
        # topics in the plot.
        if n is not None and not pd.isna(n) and ref is not None and not pd.isna(ref):
            total_n += n
            total_ref += ref
    avg = None if total_ref == 0 else 100.0 * total_n / total_ref
    for row in rows:
        row["average_comparison_percentage"] = avg
    return rows


def _assemble(reference_label: str, ref_query: str, ref_counts: dict,
              comparison: list[tuple[str, str, dict]], years: Sequence[int]) -> pd.DataFrame:
    """Build and sort the comparison frame from already-counted blocks (PURE)."""
    blocks = [_comparison_block(ref_query, "reference", reference_label, years,
                                ref_counts, ref_counts)]
    for label, query, counts in comparison:
        blocks.append(_comparison_block(query, "comparison", label, years,
                                        counts, ref_counts))
    df = pd.DataFrame([r for block in blocks for r in block], columns=COMPARISON_COLUMNS)
    df["_is_ref"] = df["query_type"] != "reference"
    df = (df.sort_values(
        ["_is_ref", "average_comparison_percentage", "abridged_query", "year"],
        ascending=[True, False, True, True],
    ).drop(columns="_is_ref").reset_index(drop=True))
    return df


def compare_topics(reference_query: str, comparison_terms, years: Sequence[int],
                   field: str | None = None, view: str = "STANDARD",
                   **kwargs) -> pd.DataFrame:
    """Compare comparison topics against a reference topic over the years.

    Each comparison query is ``(reference) AND (term)``, after ``field`` has
    wrapped each side. A reference containing OR or AND NOT therefore keeps its
    meaning, and every comparison set is a subset of the reference. The year
    limit is appended to each query as :func:`scopusflow.count.scopus_count`
    appends it.

    Returns a :data:`COMPARISON_COLUMNS` frame. One count request per term per
    year, plus one per year for the reference topic, so keep the term and year
    counts modest to stay within quota.

    Every count is sent with ``refresh=True`` unless you pass ``refresh``.
    pybliometrics keys its own response cache on the query string and view
    alone, so without ``refresh=True`` a reference harvested earlier could be
    counted from the rows the harvest left there. The terms would still be
    counted by the API, and a share of the two could pass 100%.
    ``refresh=False``, or a number of days, opts in to that cache, and a count
    it answers is warned about. The key ignores keyword filters such as
    ``subj``, so fold any filter into the queries before you opt in.

    Raises :class:`scopusflow.exceptions.ScopusFlowConfigError` before any
    request when ``pybliometrics.init()`` has not been called in the session.
    """
    if not reference_query or not str(reference_query).strip():
        raise ValueError("reference_query must be a non-empty string.")
    if isinstance(comparison_terms, str):
        comparison_terms = [comparison_terms]
    terms = [str(t).strip() for t in comparison_terms]
    if not terms or any(not t for t in terms):
        raise ValueError("comparison_terms must be a non-empty list of non-empty terms.")
    if years is None or not list(years):
        raise ValueError("years must be a non-empty sequence.")
    ys = sorted(set(_check_years(years)))
    # Every query is checked offline before the first request, so a bad term
    # cannot fail the comparison after the reference counts have been paid for.
    _check_query(str(reference_query).strip(), field)
    for term in terms:
        _check_query(term, field)
    kwargs.setdefault("refresh", True)
    require_init()

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    def size(query: str, year: int) -> int:
        full = _and_clause(query, f"PUBYEAR IS {year}")
        t0 = time.time()
        search = ScopusSearch(full, view=view, download=False, **kwargs)
        # stacklevel 3 reaches compare_topics' caller from inside size() on
        # Python 3.12 and later. Earlier versions give each comprehension that
        # calls size() a frame of its own (PEP 709), so there the warning names
        # this module.
        return result_size(search, t0, kwargs["refresh"], full, stacklevel=3)

    ref_query = wrap_field(str(reference_query).strip(), field)
    # One count step per term, plus the reference; logged as "Cell k/N:" so the
    # app's progress parser can drive a bar (mirrors the R verbose output).
    total = len(terms) + 1
    logger.info("Cell 1/%d: counting reference across %d year(s)", total, len(ys))
    ref_counts = {y: size(ref_query, y) for y in ys}

    comparison = []
    for i, term in enumerate(terms):
        logger.info("Cell %d/%d: counting '%s'", i + 2, total, term)
        # Both sides are bracketed, as in scopus_intersections(). Joined bare, an
        # AND NOT reference took the term into its negation, and the comparison
        # set outgrew the reference.
        cmp_query = f"({ref_query}) AND ({wrap_field(term, field)})"
        comparison.append((term, cmp_query, {y: size(cmp_query, y) for y in ys}))

    return _assemble(str(reference_query).strip(), ref_query, ref_counts, comparison, ys)
