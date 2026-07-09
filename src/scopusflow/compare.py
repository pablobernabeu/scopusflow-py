"""Compare how comparison topics co-occur with a reference topic over time.

For each year and comparison term, the records matching the reference combined
with that term are expressed as a percentage of the records matching the
reference alone, revealing which sub-topics grow or shrink within a literature.
Mirrors the R package's scopus_compare_topics.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import pandas as pd

from .query import wrap_field

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
        if n is not None and not pd.isna(n):
            total_n += n
        if ref is not None and not pd.isna(ref):
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
                   field: Optional[str] = None, view: str = "STANDARD",
                   **kwargs) -> pd.DataFrame:
    """Compare comparison topics against a reference topic over the years.

    Returns a :data:`COMPARISON_COLUMNS` frame. One count request per term per
    year, plus one per year for the reference topic, so keep the term and year
    counts modest to stay within quota.
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
    ys = []
    for y in years:
        yi = int(y)
        if float(y) != yi or not (1700 <= yi <= 2200):
            raise ValueError("years must be whole numbers between 1700 and 2200.")
        ys.append(yi)
    ys = sorted(set(ys))

    from pybliometrics.scopus import ScopusSearch  # imported lazily; needs a key

    def size(query: str, year: int) -> int:
        full = f"{query} AND PUBYEAR IS {year}"
        return int(ScopusSearch(full, view=view, download=False, **kwargs).get_results_size())

    ref_query = wrap_field(str(reference_query).strip(), field)
    # One count step per term, plus the reference; logged as "Cell k/N:" so the
    # app's progress parser can drive a bar (mirrors the R verbose output).
    total = len(terms) + 1
    logger.info("Cell 1/%d: counting reference across %d year(s)", total, len(ys))
    ref_counts = {y: size(ref_query, y) for y in ys}

    comparison = []
    for i, term in enumerate(terms):
        logger.info("Cell %d/%d: counting '%s'", i + 2, total, term)
        cmp_query = f"{ref_query} AND {wrap_field(term, field)}"
        comparison.append((term, cmp_query, {y: size(cmp_query, y) for y in ys}))

    return _assemble(str(reference_query).strip(), ref_query, ref_counts, comparison, ys)
