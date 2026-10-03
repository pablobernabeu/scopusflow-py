"""The provenance a record set carries, in forms that survive pandas.

:func:`scopusflow.fetch.fetch_plan` attaches its provenance to the frame's
``attrs`` as JSON-safe values: the plan as the dict
:meth:`~scopusflow.plan.SearchPlan.to_dict` writes, the retrieval time as
ISO 8601 text in UTC and the per-cell accounting as a list of dicts. A
``SearchPlan``, a ``datetime`` and a DataFrame held there made
``DataFrame.to_parquet`` raise, because pandas 2.1 and later write ``attrs`` as
JSON. They also made ``merge``, ``groupby(...).apply`` and ``concat`` raise:
pandas compares the inputs' ``attrs``, and a comparison of two DataFrames has
no single truth value.

The guides, and anyone else, may still set the richer objects by hand, so the
readers below accept either form, and :func:`json_safe` turns either into the
JSON form when a set is written to disk.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .plan import SearchPlan

#: The columns of the per-cell accounting, in the order fetch_plan() writes them.
CELL_TOTAL_COLUMNS = ["cell", "date", "n_records", "reported_total"]


def iso_utc(stamp: datetime) -> str:
    """``stamp`` as ISO 8601 text in UTC, to the second, as the search record
    states it (``"2026-07-22T09:15:00+00:00"``)."""
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def as_datetime(value) -> datetime | None:
    """A retrieval time recorded as a ``datetime`` or as ISO 8601 text, as a
    ``datetime``. ``None`` stays ``None``."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Python 3.10's fromisoformat() does not read a trailing "Z".
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    raise ValueError(
        f"A retrieval time must be a datetime or ISO 8601 text, not {value!r}."
    )


def as_plan(value) -> SearchPlan | None:
    """A plan recorded as a :class:`SearchPlan` or as its dict, as a plan.

    Anything else is ``None``, which the search record reports as an absent
    plan, as it always has.
    """
    if isinstance(value, SearchPlan):
        return value
    if isinstance(value, Mapping):
        return SearchPlan.from_dict(value)
    return None


def cell_totals_frame(value) -> pd.DataFrame | None:
    """The per-cell accounting, recorded as a DataFrame or as a list of dicts,
    as a DataFrame. Anything else is ``None``."""
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(row, Mapping) for row in value):
        return pd.DataFrame(list(value), columns=CELL_TOTAL_COLUMNS)
    return None


def _plain(value, name: str):
    """``value`` in a form ``json.dumps`` writes as standard JSON."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, SearchPlan):
        return value.to_dict()
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, pd.DataFrame):
        return [_plain(row, name) for row in value.to_dict("records")]
    if isinstance(value, Mapping):
        return {str(k): _plain(v, name) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, name) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return value
    raise TypeError(
        f"The attribute {name!r} holds a {type(value).__name__}, which cannot be "
        "written as JSON."
    )


def json_safe(attrs: Mapping) -> dict:
    """A copy of ``attrs`` holding only values that ``json.dumps`` writes as
    standard JSON. A frame's own ``attrs`` are left as they are."""
    out = {str(name): _plain(value, str(name)) for name, value in attrs.items()}
    json.dumps(out, allow_nan=False)  # raises here, before any file is opened
    return out
