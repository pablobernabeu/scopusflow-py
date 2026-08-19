"""scopusflow: a reproducible workflow layer over pybliometrics.

pybliometrics provides the retrieval primitives for the Scopus API; scopusflow
adds the workflow on top: reproducible search plans, a single stable record
schema, resumable checkpointed harvesting, DOI change-tracking, and a
PRISMA-S record of the search for a methods section.
"""

from __future__ import annotations

from .abstract import ABSTRACT_COLUMNS, scopus_abstract
from .combine import scopus_combine
from .compare import COMPARISON_COLUMNS, compare_topics
from .corpus import corpus
from .count import scopus_count
from .data import example_records
from .diff import diff_dois, extract_dois
from .exceptions import ScopusFlowForbiddenError
from .export import to_bibtex, to_ris
from .fetch import fetch_plan
from .intersections import scopus_intersections
from .plan import PlanCell, SearchPlan
from .plots import (
    plot_comparison,
    plot_scopus_intersections,
    plot_top,
    plot_trend,
)
from .query import FIELD_TAGS, scopus_query, wrap_field
from .records import RECORD_COLUMNS, to_records, top
from .report import PRISMA_S_ITEMS, SearchReport, scopus_search_report
from .trend import TREND_COLUMNS, scopus_trend, year_counts

__version__ = "0.3.0"

# The four schema constants are exported alongside the functions that return
# them: each documents itself as a stable column set, which is a promise only
# worth making from the package's own surface. The API page states that every
# name it lists is importable from `scopusflow`, and COMPARISON_COLUMNS was not.
__all__ = [
    "SearchPlan",
    "PlanCell",
    "scopus_query",
    "wrap_field",
    "FIELD_TAGS",
    "to_records",
    "top",
    "RECORD_COLUMNS",
    "example_records",
    "fetch_plan",
    "scopus_combine",
    "scopus_search_report",
    "SearchReport",
    "PRISMA_S_ITEMS",
    "extract_dois",
    "diff_dois",
    "year_counts",
    "scopus_trend",
    "TREND_COLUMNS",
    "scopus_count",
    "scopus_intersections",
    "compare_topics",
    "COMPARISON_COLUMNS",
    "scopus_abstract",
    "ABSTRACT_COLUMNS",
    "ScopusFlowForbiddenError",
    "corpus",
    "to_bibtex",
    "to_ris",
    "plot_trend",
    "plot_top",
    "plot_comparison",
    "plot_scopus_intersections",
    "__version__",
]
