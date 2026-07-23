"""The bundled worked-example harvest.

The records are real journal articles on graphene supercapacitors, carrying
their real titles, DOIs, source titles, first authors and citation counts, so
the package can be explored and every guide run without an API key.

They are deliberately not a Scopus harvest. The Elsevier API terms do not permit
redistributing retrieved records, so no package can ship one. These come instead
from OpenAlex, whose metadata is released under CC0 and may therefore be
redistributed, and are reshaped into the schema ``fetch_plan`` returns. Running
the equivalent query against Scopus yields the same kind of frame, with the same
columns and the same handling, though not an identical set of records.

The file is the same one the R twin builds its ``example_records`` dataset from,
so the two languages document the identical corpus.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources

import pandas as pd

from .records import RECORD_COLUMNS

__all__ = ["example_records"]

# Held in _data/ rather than data/, which would collide with this module's name.
_FILE = "_data/example_records.csv"


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    with resources.as_file(resources.files("scopusflow") / _FILE) as path:
        frame = pd.read_csv(
            path,
            dtype={"scopus_id": "string", "doi": "string", "title": "string",
                   "authors": "string", "date": "string", "publication": "string",
                   "query": "string"},
        )
    frame["entry_number"] = frame["entry_number"].astype(int)
    frame["year"] = frame["year"].astype(int)
    frame["citations"] = frame["citations"].astype(int)
    return frame[list(RECORD_COLUMNS)]


def example_records() -> pd.DataFrame:
    """Return the bundled example harvest as a records frame.

    A fresh copy is returned on each call, so a caller may edit the result
    without disturbing anyone else's.

    Returns
    -------
    pandas.DataFrame
        138 records with the standard ``RECORD_COLUMNS`` schema, covering 2015
        to 2024. The harvest is complete rather than sampled, so the rows per
        year are the real publications per year for the query. ``scopus_id`` is
        empty throughout, these records not having come from Scopus; eleven
        records carry no DOI and two no source title, exactly as they arrive.

    Examples
    --------
    >>> import scopusflow as sf
    >>> records = sf.example_records()
    >>> len(records)
    138
    >>> sorted(records.columns) == sorted(sf.RECORD_COLUMNS)
    True
    """
    return _load().copy()
