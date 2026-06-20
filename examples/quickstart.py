"""Quick-start tour of scopusflow's reproducible Scopus workflow.

Run this file directly (``python examples/quickstart.py``). It performs no
network calls: the live ``fetch_plan`` step is shown only as a comment, and the
analysis helpers run against a small synthetic record set, so the script is
safe to import and runs without a Scopus API key.
"""

from __future__ import annotations

import pandas as pd

from scopusflow import (
    SearchPlan,
    diff_dois,
    extract_dois,
    scopus_query,
    top,
    year_counts,
)


def main() -> None:
    # 1. Build a field-tagged query and a reproducible, year-partitioned plan.
    query = scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
    plan = SearchPlan(query, years=range(2018, 2023), partition="year")
    print("Query:", query)
    print("Plan cells:", [c.cell for c in plan.cells()])

    # 2. Harvest the plan. This is the only step that reaches the Scopus API, so
    #    it is left commented out; uncomment it once pybliometrics has a key.
    #
    #    from scopusflow import fetch_plan
    #    records = fetch_plan(plan, cache_dir="harvest", resume=True)

    # 3. For the offline tour, stand in a small synthetic record set that follows
    #    the stable schema fetch_plan would return.
    records = pd.DataFrame(
        {
            "entry_number": [1, 2, 3, 4],
            "scopus_id": ["1", "2", "3", "4"],
            "doi": ["10.1/a", "10.1/b", "10.1/c", "10.1/d"],
            "title": ["Graphene I", "Graphene II", "Graphene III", "Graphene IV"],
            "authors": ["Lee J.", "Lee J.;Park S.", "Park S.", "Kim H."],
            "year": [2019, 2020, 2020, 2021],
            "date": ["2019-03-01", "2020-06-01", "2020-09-01", "2021-01-01"],
            "publication": ["Carbon", "Carbon", "Nano Letters", "Carbon"],
            "citations": [12, 8, 5, 1],
            "query": [query] * 4,
        }
    )

    # 4. The stable schema feeds the analysis helpers.
    print("\nTop sources:")
    print(top(records, by="source"))

    dois = extract_dois(records)
    print("\nDOIs:", dois)

    # 5. Re-run later and see exactly what changed. Here a synthetic "later" run
    #    drops one record and adds another.
    later = records.iloc[1:].copy()
    later.loc[later.index.max() + 1, "doi"] = "10.1/e"
    print("\nDOI diff (old vs new):")
    print(diff_dois(old=records, new=later))

    # 6. Annual publication trend from the records, then plot it if matplotlib
    #    is installed (it is an optional dependency).
    trend = year_counts(records)
    print("\nYear counts:")
    print(trend)

    try:
        from scopusflow import plot_trend

        ax = plot_trend(trend)
        ax.set_title("Graphene supercapacitor records per year")
        print("\nplot_trend returned an Axes; call plt.show() to display it.")
    except ImportError:
        print("\nmatplotlib not installed; skipping plot_trend (pip install '.[plot]').")


if __name__ == "__main__":
    main()
