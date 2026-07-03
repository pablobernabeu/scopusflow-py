"""scopusflow: a reproducible workflow layer over pybliometrics.

pybliometrics provides the retrieval primitives for the Scopus API; scopusflow
adds the workflow on top: reproducible search plans, a single stable record
schema, resumable checkpointed harvesting, and DOI change-tracking.
"""

from __future__ import annotations

from .abstract import scopus_abstract
from .compare import compare_topics
from .corpus import corpus
from .count import scopus_count
from .diff import diff_dois, extract_dois
from .exceptions import ScopusFlowForbiddenError
from .export import to_bibtex, to_ris
from .fetch import fetch_plan
from .plan import PlanCell, SearchPlan
from .plots import plot_comparison, plot_top, plot_trend
from .query import FIELD_TAGS, scopus_query, wrap_field
from .records import RECORD_COLUMNS, to_records, top
from .trend import scopus_trend, year_counts

__version__ = "0.1.1"

__all__ = [
    "SearchPlan",
    "PlanCell",
    "scopus_query",
    "wrap_field",
    "FIELD_TAGS",
    "to_records",
    "top",
    "RECORD_COLUMNS",
    "fetch_plan",
    "extract_dois",
    "diff_dois",
    "year_counts",
    "scopus_trend",
    "scopus_count",
    "compare_topics",
    "scopus_abstract",
    "ScopusFlowForbiddenError",
    "corpus",
    "to_bibtex",
    "to_ris",
    "plot_trend",
    "plot_top",
    "plot_comparison",
    "__version__",
]
