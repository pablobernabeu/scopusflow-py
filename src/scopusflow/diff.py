"""Extract, clean and compare DOI sets across retrievals."""

from __future__ import annotations

import re

import pandas as pd

_RESOLVER = re.compile(r"^\s*(https?://)?(www\.)?(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_LABEL = re.compile(r"^\s*doi:\s*", re.IGNORECASE)


def _clean(dois) -> list[str]:
    out: list[str] = []
    for d in dois:
        if d is None or (isinstance(d, float) and pd.isna(d)):
            continue
        s = _RESOLVER.sub("", str(d).strip())
        s = _DOI_LABEL.sub("", s).strip()
        if s:
            out.append(s)
    return out


def _as_dois(x) -> list[str]:
    if isinstance(x, pd.DataFrame) and "doi" in x.columns:
        return x["doi"].tolist()
    return list(x)


def extract_dois(records, dedupe: bool = True) -> list[str]:
    """Pull cleaned, optionally de-duplicated DOIs from records or a list."""
    dois = _clean(_as_dois(records))
    if not dedupe:
        return dois
    seen: set[str] = set()
    result: list[str] = []
    for d in dois:
        key = d.lower()
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result


def diff_dois(old, new) -> pd.DataFrame:
    """Compare two retrievals; return a frame of (doi, status) where status is
    ``added``, ``removed`` or ``unchanged`` (compared case-insensitively)."""
    old_d, new_d = extract_dois(old), extract_dois(new)
    old_keys = {d.lower() for d in old_d}
    new_keys = {d.lower() for d in new_d}
    rows = (
        [(d, "added") for d in new_d if d.lower() not in old_keys]
        + [(d, "removed") for d in old_d if d.lower() not in new_keys]
        + [(d, "unchanged") for d in new_d if d.lower() in old_keys]
    )
    df = pd.DataFrame(rows, columns=["doi", "status"])
    return df.sort_values(["status", "doi"]).reset_index(drop=True)
