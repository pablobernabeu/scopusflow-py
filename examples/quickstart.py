"""Quick-start tour of scopusflow's reproducible Scopus workflow.

Run this file directly (``python examples/quickstart.py``). It performs no
network calls: the live ``fetch_plan`` step is shown only as a comment, and the
analysis helpers run against the bundled example harvest, so the script is safe
to import and runs without a Scopus API key.
"""

from __future__ import annotations

from scopusflow import (
    SearchPlan,
    diff_dois,
    example_records,
    extract_dois,
    scopus_query,
    top,
    year_counts,
)


def main() -> None:
    # 1. Build a field-tagged query and a reproducible, year-partitioned plan.
    query = scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
    plan = SearchPlan(query, years=range(2015, 2025), partition="year")
    print("Query:", query)
    print("Plan cells:", [c.cell for c in plan.cells()])

    # 2. Harvest the plan. This is the only step that reaches the Scopus API, so
    #    it is left commented out; uncomment it once pybliometrics has a key.
    #
    #    from scopusflow import fetch_plan
    #    records = fetch_plan(plan, cache_dir="harvest", resume=True)

    # 3. For the offline tour, use the bundled harvest instead: 138 real
    #    articles already in the schema fetch_plan would return.
    records = example_records()
    # Store one DOI behind its resolver, as an aggregator often returns it, so
    # the cleaning below has something to strip.
    records.loc[0, "doi"] = "https://doi.org/" + records.loc[0, "doi"]

    # 4. The stable schema feeds the analysis helpers.
    print("\nTop sources:")
    print(top(records, by="source", n=5))

    # 127 DOIs from 138 records: the resolver prefix comes off, and the eleven
    # records with no DOI are dropped rather than passed on as blanks.
    dois = extract_dois(records)
    print(f"\n{len(dois)} DOIs, the first three:", dois[:3])

    # 5. Re-run later and see exactly what changed. Both sides here are cut from
    #    the same bundled harvest: the baseline stops at 2021, and the later run
    #    also loses one record, as happens when a paper is re-indexed.
    baseline = records[records["year"] <= 2021]
    later = records.drop(index=records.index[0])
    print("\nDOI diff (old vs new):")
    print(diff_dois(old=baseline, new=later)["status"].value_counts())

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
