"""Pure, offline helpers behind the GUI (``scopusflow.app``).

Kept free of any GUI import so the script generation and progress parsing can be
unit-tested without NiceGUI installed.
"""

from __future__ import annotations

import re

_CELL_RE = re.compile(r"Cell\s+(\d+)\s*/\s*(\d+):")


def app_years_code(years) -> str | None:
    """Render a year sequence as a compact Python expression: a contiguous run
    becomes ``range(2015, 2023)`` (inclusive of the last year), anything else a
    list. ``None``/empty returns ``None`` (omit the argument)."""
    ys = sorted({int(y) for y in years}) if years else []
    if not ys:
        return None
    if len(ys) >= 2 and ys == list(range(ys[0], ys[-1] + 1)):
        return f"range({ys[0]}, {ys[-1] + 1})"
    if len(ys) == 1:
        return f"[{ys[0]}]"
    return "[" + ", ".join(str(y) for y in ys) + "]"


def _join(args: list[str]) -> str:
    one = ", ".join(args)
    if len(one) <= 60 and len(args) <= 2:
        return one
    return "\n    " + ",\n    ".join(args) + ",\n"


def app_code_mirror(query, years=None, field=None, view="STANDARD",
                    partition="year", by="source") -> str:
    """Build the runnable Python script that mirrors the GUI choices. The key is
    never emitted: the script notes it comes from the pybliometrics config."""
    q = query.strip() if query and query.strip() else "your query"
    years_code = app_years_code(years)

    plan_args = [repr(q)]
    if years_code:
        plan_args.append(f"years={years_code}")
    if field:
        plan_args.append(f"field={field!r}")
    if view == "COMPLETE":
        plan_args.append('view="COMPLETE"')
    if partition == "year" and years_code:
        plan_args.append('partition="year"')

    lines = [
        "import scopusflow as sf",
        "",
        "# Describe the search as an inspectable, reproducible plan.",
        f"plan = sf.SearchPlan({_join(plan_args)})",
        "",
        "# Retrieve, caching each cell so an interrupted run resumes. Configure",
        "# your Scopus key with pybliometrics first: pybliometrics.init(keys=[...]).",
        "records = sf.fetch_plan(plan, cache_dir='harvest', resume=True)",
        "",
        "# Inspect the most frequent values and the records per year.",
        f"sf.top(records, by={by!r})",
        "sf.year_counts(records)",
        "",
        "# Save the records.",
        "records.to_csv('scopus-records.csv', index=False)",
        "",
        "# Or export for a reference manager (Zotero, EndNote) or LaTeX.",
        "with open('scopus-records.bib', 'w', encoding='utf-8') as fh:",
        "    fh.write(sf.to_bibtex(records))",
    ]
    return "\n".join(lines)


def app_parse_progress(lines):
    """Read the most recent ``Cell k/N:`` marker from log lines and return
    ``{"done": k, "total": N}`` for the progress bar, or ``None``. The trailing
    colon anchors the match and a ``done > total`` marker is rejected, so a
    ``k/N`` pattern echoed from the query is unlikely to be mistaken for it."""
    matches = [m for line in lines for m in (_CELL_RE.search(line),) if m]
    if not matches:
        return None
    done, total = int(matches[-1].group(1)), int(matches[-1].group(2))
    if done > total:
        return None
    return {"done": done, "total": total}
