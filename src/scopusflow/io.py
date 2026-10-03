"""Save a record set to disk and read it back.

These are the twins of the R package's ``write_scopus_records()`` and
``read_scopus_records()``. The file extension selects the format. Parquet keeps
the provenance a harvest carries in its ``attrs``, so a baseline saved this way
still writes its own search record when it is read back. CSV is portable plain
text and keeps the columns only. Both formats are read back with the record
schema imposed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from ._provenance import json_safe
from .fetch import _CHECKPOINT_TEXT, _as_whole_numbers, _read_csv_records

__all__ = ["write_records", "read_records"]

#: The parquet schema-metadata key the provenance block is stored under.
_METADATA_KEY = b"scopusflow"

#: The key pandas 2.1 and later store ``attrs`` under, read when a file was
#: written by ``DataFrame.to_parquet`` and carries no block of scopusflow's own.
_PANDAS_ATTRS_KEY = b"PANDAS_ATTRS"

#: The layout version of the provenance block.
_SCHEMA = 1

_FORMATS = {".parquet": "parquet", ".csv": "csv"}


def _format(path) -> str:
    """The format ``path`` names by its extension, after checking the path."""
    if isinstance(path, bytes) or not isinstance(path, (str, os.PathLike)):
        raise ValueError("path must be a single non-empty file path.")
    if not str(path).strip():
        raise ValueError("path must be a single non-empty file path.")
    suffix = Path(path).suffix.lower()
    if suffix not in _FORMATS:
        raise ValueError(
            f"Unsupported file extension '{suffix}'. Use '.parquet' or '.csv'."
        )
    return _FORMATS[suffix]


def _pyarrow():
    """pyarrow and its parquet module, or an ImportError that says how to get
    them. pyarrow is optional, since CSV needs nothing beyond pandas."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError(
            "Reading and writing parquet needs pyarrow. Install it with "
            "pip install 'scopusflow[parquet]', or use a .csv path, which keeps "
            "the columns but not the provenance."
        ) from exc
    return pa, pq


def write_records(records: pd.DataFrame, path) -> pd.DataFrame:
    """Save a record set, choosing the format from the file extension.

    A ``.parquet`` file keeps the provenance in ``records.attrs``: the plan,
    the retrieval time, the per-cell totals, the paging mode, the software
    version and any merge record, all of which
    :func:`scopusflow.report.scopus_search_report` reads back. They are stored
    as a JSON block under the ``scopusflow`` key of the file's schema
    metadata, so they survive whatever the pandas version. pandas 1.5 to 2.0
    drop ``attrs`` when writing parquet, and later versions keep them under a
    key of their own. Attributes set by hand as a ``SearchPlan``, a
    ``datetime`` or a DataFrame are written in the JSON forms
    :func:`scopusflow.fetch.fetch_plan` uses, and the frame passed in is left
    as it was. Parquet needs pyarrow, which the ``parquet`` extra installs.

    A ``.csv`` file is portable plain text, written with LF line endings on
    every platform, and holds the columns only. Save a baseline you will
    compare against later as parquet, so that it keeps the record of how it
    was retrieved.

    Parameters
    ----------
    records:
        A record frame, such as :func:`scopusflow.fetch.fetch_plan` returns.
    path:
        The file to write, ending in ``.parquet`` or ``.csv``. It is written
        at exactly this path, and its directory must already exist.

    Returns
    -------
    pandas.DataFrame
        ``records``, unchanged.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> import scopusflow as sf
    >>> path = pathlib.Path(tempfile.mkdtemp()) / "baseline.csv"
    >>> _ = sf.write_records(sf.example_records(), path)
    >>> len(sf.read_records(path))
    138
    """
    if not isinstance(records, pd.DataFrame):
        raise ValueError("records must be a record frame.")
    fmt = _format(path)
    if fmt == "csv":
        records.to_csv(path, index=False, lineterminator="\n")
        return records
    pa, pq = _pyarrow()
    safe = json_safe(records.attrs)
    block = json.dumps({"schema": _SCHEMA, "attrs": safe}, allow_nan=False)
    # Recent pyarrow copies attrs into its own pandas metadata, and warns and
    # drops them when they are not JSON. A shallow copy carrying the safe form
    # gives it something it can write and leaves the caller's frame alone.
    shallow = records.copy(deep=False)
    shallow.attrs = safe
    table = pa.Table.from_pandas(shallow, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[_METADATA_KEY] = block.encode("utf-8")
    pq.write_table(table.replace_schema_metadata(metadata), path)
    return records


def _stored_attrs(metadata, restored: dict, path) -> dict:
    """The provenance a parquet file holds, or ``{}``.

    scopusflow's own block comes first. A file written elsewhere may carry the
    ``attrs`` recent pyarrow restores by itself (``restored``) or those pandas
    stores under its own key, and those are returned as they are.
    """
    metadata = metadata or {}
    raw = metadata.get(_METADATA_KEY)
    if raw is None:
        if restored:
            return dict(restored)
        pandas_attrs = metadata.get(_PANDAS_ATTRS_KEY)
        return dict(json.loads(pandas_attrs)) if pandas_attrs else {}
    stored = json.loads(raw)
    schema = stored.get("schema")
    if schema != _SCHEMA:
        raise ValueError(
            f"{path} records its provenance under schema {schema!r}, and this "
            f"version of scopusflow reads schema {_SCHEMA} only."
        )
    return dict(stored.get("attrs") or {})


def read_records(path) -> pd.DataFrame:
    """Read a record set saved by :func:`write_records`.

    Both formats come back with the record schema imposed: the text columns,
    ``scopus_id`` among them, as strings, and ``year`` and ``citations`` as
    nullable integers. A CSV left to pandas' own inference reads an all-digit
    identifier as a number, or as a float once one identifier is missing, and
    a de-duplicating :func:`scopusflow.combine.scopus_combine` then matches
    none of its records against a fresh harvest.

    A parquet file comes back with the provenance it was saved with in
    ``attrs``, so its search record reads as the original's did. A parquet
    file written by ``DataFrame.to_parquet`` under pandas 2.1 or later
    returns the ``attrs`` pandas stored. A CSV file carries none.

    Parameters
    ----------
    path:
        The file to read, ending in ``.parquet`` or ``.csv``.

    Returns
    -------
    pandas.DataFrame
        The records, with any provenance in ``attrs``.
    """
    fmt = _format(path)
    if fmt == "parquet":
        _, pq = _pyarrow()
    if not Path(path).exists():
        raise FileNotFoundError(f"File not found: {path}")
    if fmt == "csv":
        frame = _read_csv_records(path)
        attrs: dict = {}
    else:
        table = pq.read_table(path)
        frame = table.to_pandas()
        attrs = _stored_attrs(table.schema.metadata, frame.attrs, path)
        for column in _CHECKPOINT_TEXT:
            if column in frame.columns:
                frame[column] = frame[column].astype("string")
        frame = _as_whole_numbers(frame)
    frame.attrs = attrs
    return frame
