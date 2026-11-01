"""Pure, offline helpers behind the GUI (``scopusflow.app``).

Kept free of any GUI import so the script generation and progress parsing can be
unit-tested without NiceGUI installed.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid

from . import __version__

_CELL_RE = re.compile(r"Cell\s+(\d+)\s*/\s*(\d+):")

#: How the app refuses a second long job while one is in flight, keyed by the
#: job holding it. A harvest, a plan check and a comparison all drive the one
#: process-wide key and the single "scopusflow" logger, so two at once would
#: double the live API load and cross the two log pumps.
_BUSY_MESSAGES = {
    "fetch": "A retrieval is already running.",
    "count": "A plan check is already running.",
    "compare": "A topic comparison is already running.",
}


def app_busy_message(busy: str | None) -> str | None:
    """The refusal to show while ``busy`` names the job in flight, or ``None``
    when the app is idle and the caller may start its own."""
    if not busy:
        return None
    return _BUSY_MESSAGES.get(busy, "Another job is already running.")


def app_search_query(value) -> str:
    """The query the app sends, trimmed.

    :class:`~scopusflow.plan.SearchPlan` checks the query with ``strip()`` but
    keeps it as typed, so a query pasted with surrounding space would otherwise
    reach the API inside the field tag, and the search record, untrimmed. The
    harvest, the plan check, the comparison, the checkpoint key and the script
    all read the query through this helper, so the script panel shows the query
    that is sent. The R twin's ``app_search_query()`` trims the same
    characters."""
    return (value or "").strip()


def app_session_dir(base: str) -> str:
    """A checkpoint directory for one page scope, under the shared ``base``.

    Every open tab of the app shares the base, so a session may only ever
    remove its own subdirectory on disconnect: removing the base itself would
    delete another session's checkpoints mid-harvest. A uuid4 keys the
    subdirectory, so two sessions opening at once cannot collide."""
    return os.path.join(base, uuid.uuid4().hex)


def app_years_code(years) -> str | None:
    """Render a year sequence as a compact Python expression.

    The years are de-duplicated and sorted first. Two or more consecutive years
    become a ``range()`` whose stop is one past the last year, so 2015 to 2022
    becomes ``range(2015, 2023)``. A single year or a set with gaps becomes a
    list, such as ``[2019]`` or ``[2010, 2012, 2015]``. ``None`` or an empty
    sequence returns ``None``, and the caller then omits the argument."""
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


def app_plan_cache_name(query, years=None, field=None, view="STANDARD",
                        partition="none") -> str:
    """The checkpoint directory the generated script gives its plan.

    :func:`~scopusflow.fetch.fetch_plan` names each checkpoint by its cell's
    position, so a directory serves one plan: two plans sharing one would
    overwrite each other's cells, and each rerun would pay for them again. The
    name is ``harvest-`` and eight hexadecimal digits of a SHA-256 over
    everything that shapes the cells: the query, the field, the view, the
    partition and the years. The same choices give the same directory, so
    running the script again resumes, and any change gives a directory of its
    own."""
    ys = sorted({int(y) for y in years}) if years else []
    identity = "\n".join([query, field or "", view, partition,
                          ",".join(str(y) for y in ys)])
    return "harvest-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]


def app_comparison_cost(n_terms: int, n_years: int) -> int:
    """The count requests a topic comparison makes.

    :func:`~scopusflow.compare.compare_topics` counts the reference in every
    year as well as each term, so ``n_terms`` terms over ``n_years`` years cost
    ``(n_terms + 1) * n_years`` requests."""
    return (n_terms + 1) * n_years


def app_code_mirror(query, years=None, field=None, view="STANDARD",
                    partition="year", by="source", compare_terms=None,
                    compare_years=None, highlight=None, interval=True,
                    counts_in_legend=True, demo=False) -> str:
    """Build the runnable Python script that mirrors the GUI choices. The key is
    never emitted: the script calls ``pybliometrics.init()``, which reads the
    key from the user's pybliometrics configuration. When
    ``compare_terms`` are supplied a topic-comparison block is appended over
    ``compare_years``, or over the plan's own years when that is not given,
    reflecting the chosen ``highlight``/``interval``/``counts_in_legend``. The
    comparison's span is separate because the app compares over the last six
    years when the plan is not partitioned by year, and the script has to name
    the span that ran. The harvest's checkpoints go to a directory of the plan's
    own, named by :func:`app_plan_cache_name`.

    The script opens with the scopusflow version that wrote it, so a downloaded
    file records which release its behaviour belongs to. With ``demo`` true it
    also says plainly that the records on screen were replayed from the bundled
    corpus and that what follows is the live equivalent, as the demo comparison
    figure carries a note of its own. Without that header, a demo session's
    panel, labelled "Reproducible Python", would offer a script that reproduces
    something the user did not run."""
    q = app_search_query(query) or "your query"
    years_code = app_years_code(years)
    by_year = partition == "year" and bool(years_code)

    plan_args = [repr(q)]
    if years_code:
        plan_args.append(f"years={years_code}")
    if field:
        plan_args.append(f"field={field!r}")
    if view == "COMPLETE":
        plan_args.append('view="COMPLETE"')
    if by_year:
        plan_args.append('partition="year"')
    cache = app_plan_cache_name(
        q, years, field=field or None,
        view="COMPLETE" if view == "COMPLETE" else "STANDARD",
        partition="year" if by_year else "none",
    )

    lines = [f"# scopusflow {__version__}"]
    if demo:
        lines += [
            "# Demo mode was on, so the records shown in the app were replayed",
            "# from sf.example_records(), the bundled corpus of real published",
            "# articles. Nothing was retrieved. The script below is the live",
            "# equivalent: it harvests from Scopus and needs a configured key.",
        ]
    lines += [
        "",
        "import pybliometrics",
        "",
        "import scopusflow as sf",
        "",
        "# pybliometrics needs init() once per session. It reads your key from its",
        "# configuration file, or creates the file and asks for the key on first use.",
        "pybliometrics.init()",
        "",
        "# Describe the search as an inspectable, reproducible plan.",
        f"plan = sf.SearchPlan({_join(plan_args)})",
        "",
        "# Retrieve, caching each cell so an interrupted run resumes. The",
        "# checkpoints go to a directory of this plan's own.",
        f"records = sf.fetch_plan(plan, cache_dir={cache!r}, resume=True)",
        "",
        "# Inspect the most frequent values and the records per year. These two",
        "# lines show their result in an interactive session, and print nothing",
        "# when the script is run with python.",
        f"sf.top(records, by={by!r})",
        "sf.year_counts(records)",
        "",
        "# Save the records.",
        "records.to_csv('scopus-records.csv', index=False)",
        "",
        "# Or export for a reference manager (Zotero, EndNote) or LaTeX.",
        "with open('scopus-records.bib', 'w', encoding='utf-8') as fh:",
        "    fh.write(sf.to_bibtex(records))",
        "",
        "# Write the search up for the methods section, to the PRISMA-S standard.",
        "sf.scopus_search_report(records, file='scopus-search-record.md')",
    ]

    terms = [t.strip() for t in (compare_terms or []) if t and t.strip()]
    cmp_years_code = app_years_code(compare_years) or years_code
    if terms and cmp_years_code:
        cmp_args = [repr(q), "[" + ", ".join(repr(t) for t in terms) + "]",
                    f"years={cmp_years_code}"]
        if field:
            cmp_args.append(f"field={field!r}")
        if view == "COMPLETE":
            cmp_args.append('view="COMPLETE"')
        plot_args = ["cmp"]
        if highlight:
            plot_args.append(f"highlight={highlight!r}")
        if not interval:
            plot_args.append("interval=False")
        if not counts_in_legend:
            plot_args.append("counts_in_legend=False")
        lines += [
            "",
            "# Compare how sub-topics co-occur with the search over time, as a",
            "# share of it (one count request per term per year, plus one per",
            "# year for the reference topic). The plot shows in an interactive",
            "# session, and this block saves nothing when the script is run",
            "# with python.",
            f"cmp = sf.compare_topics({_join(cmp_args)})",
            f"sf.plot_comparison({', '.join(plot_args)})",
        ]
    return "\n".join(lines)


def app_fetch_notice(records, warned=None) -> tuple[str, str]:
    """The notification shown when a harvest ends, with its NiceGUI type.

    A harvest the Cancel button stopped records how many of its cells ran (see
    :func:`scopusflow.fetch.fetch_plan`), and the notice gives them as a
    warning, where "Retrieved N records." would present the part as the whole.
    ``warned`` holds the warnings the harvest raised, a cell short of the total
    the API reported among them. A harvest that raised one may be incomplete,
    and the notice says so and names the first.
    """
    attrs = getattr(records, "attrs", {})
    if attrs.get("stopped_early") is True:
        planned = attrs.get("cells_planned")
        return (f"Stopped after {attrs.get('cells_run')} of {planned} "
                f"cell{'' if planned == 1 else 's'}.", "warning")
    n = len(records)
    if warned:
        return (f"Retrieved {n:,} records, but the harvest may be incomplete. "
                f"{warned[0]}", "warning")
    return f"Retrieved {n:,} records.", "positive" if n else "warning"


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
