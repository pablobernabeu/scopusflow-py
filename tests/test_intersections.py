"""Offline tests for the concept-intersection layer (no API key, no pybliometrics).

The query-building and validation logic lives in the pure ``_intersection_rows``
helper, so it is exercised here without any network call; the counting itself
(one ``scopus_count`` per row) is a thin wrapper over pybliometrics and is not
retested.
"""

import pandas as pd
import pytest

from scopusflow.intersections import (
    _intersection_rows,
    scopus_intersections,
    wrap_concept,
)


def test_wrap_concept_wraps_bare_terms_but_passes_expressions_through():
    assert wrap_concept("graphene", "TITLE-ABS-KEY") == "TITLE-ABS-KEY(graphene)"
    # A value that already opens with a field tag is used exactly as given.
    expr = "TITLE(virtual reality) OR TITLE(VR)"
    assert wrap_concept(expr, "TITLE-ABS-KEY") == expr
    # With no field, a bare term is returned unchanged.
    assert wrap_concept("graphene", None) == "graphene"


def test_rows_cover_each_concept_and_intersection():
    rows = _intersection_rows(
        concepts={"A": "alpha", "B": "beta"},
        intersections=[["A", "B"]],
        abbrev=None,
        sep=" × ",
        field="TITLE-ABS-KEY",
    )
    assert list(rows["label"]) == ["A", "B", "A × B"]
    assert list(rows["type"]) == ["concept", "concept", "intersection"]
    assert list(rows["size"]) == [1, 1, 2]
    # The intersection query wraps each member and joins with AND.
    assert rows.loc[2, "query"] == (
        "(TITLE-ABS-KEY(alpha)) AND (TITLE-ABS-KEY(beta))"
    )
    assert rows.loc[2, "members"] == "A; B"


def test_a_complete_expression_concept_is_not_rewrapped():
    rows = _intersection_rows(
        concepts={
            "priming": "semantic priming",
            "simulation": "TITLE-ABS-KEY(mental simulation) OR TITLE-ABS-KEY(embodied simulation)",
        },
        intersections=[["priming", "simulation"]],
        abbrev=None,
        sep=" × ",
        field="TITLE-ABS-KEY",
    )
    # The bare term is wrapped; the field-tagged expression passes through.
    assert rows.loc[0, "query"] == "TITLE-ABS-KEY(semantic priming)"
    assert rows.loc[1, "query"] == (
        "TITLE-ABS-KEY(mental simulation) OR TITLE-ABS-KEY(embodied simulation)"
    )
    assert rows.loc[2, "query"] == (
        "(TITLE-ABS-KEY(semantic priming)) AND "
        "(TITLE-ABS-KEY(mental simulation) OR TITLE-ABS-KEY(embodied simulation))"
    )


def test_abbrev_shortens_only_intersection_labels():
    rows = _intersection_rows(
        concepts={"Semantic priming": "semantic priming",
                  "Mental simulation": "mental simulation"},
        intersections=[["Semantic priming", "Mental simulation"]],
        abbrev={"Semantic priming": "SP", "Mental simulation": "MS"},
        sep=" x ",
        field=None,
    )
    # Concept rows keep their full names; the intersection uses the short forms.
    assert list(rows["label"][:2]) == ["Semantic priming", "Mental simulation"]
    assert rows.loc[2, "label"] == "SP x MS"


def test_a_single_flat_intersection_is_accepted():
    rows = _intersection_rows(
        concepts={"A": "a", "B": "b", "C": "c"},
        intersections=["A", "B", "C"],
        abbrev=None,
        sep=" × ",
        field=None,
    )
    inter = rows[rows["type"] == "intersection"]
    assert len(inter) == 1
    assert inter.iloc[0]["size"] == 3
    assert inter.iloc[0]["label"] == "A × B × C"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(concepts={}), "non-empty mapping"),
        (dict(concepts={"A": ""}), "non-empty term"),
        (dict(concepts={"": "a"}), "non-empty string"),
        (dict(concepts={"A": "a", "B": "b"}, intersections=[["A"]]),
         "two or more distinct"),
        (dict(concepts={"A": "a"}, intersections=[["A", "A"]]),
         "two or more distinct"),
        (dict(concepts={"A": "a"}, intersections=[["A", "Z"]]),
         "not among the concept labels"),
        (dict(concepts={"A": "a"}, abbrev={"Z": "z"}),
         "abbrev keys not among"),
        (dict(concepts={"A": "a"}, sep=""), "sep must be a non-empty"),
    ],
)
def test_invalid_inputs_raise_value_error(kwargs, match):
    base = dict(intersections=None, abbrev=None, sep=" × ", field=None)
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        _intersection_rows(**base)


def test_colliding_labels_are_rejected():
    # abbrev maps both concepts to the same short form, so the intersection label
    # would collide with nothing here, but two concepts sharing a display label
    # is impossible via a dict; instead force a concept/intersection collision.
    with pytest.raises(ValueError, match="must be distinct"):
        _intersection_rows(
            concepts={"A": "a", "B": "b", "A × B": "c"},
            intersections=[["A", "B"]],
            abbrev=None,
            sep=" × ",
            field=None,
        )


def test_scopus_intersections_counts_each_row(monkeypatch):
    # Patch the counting so the public function runs fully offline.
    seen = {}

    def fake_count(query, years=None, view="STANDARD", **kwargs):
        seen[query] = seen.get(query, 0) + 1
        return {"TITLE-ABS-KEY(alpha)": 100,
                "TITLE-ABS-KEY(beta)": 40}.get(query, 7)

    monkeypatch.setattr("scopusflow.intersections.scopus_count", fake_count)
    out = scopus_intersections(
        concepts={"A": "alpha", "B": "beta"},
        intersections=[["A", "B"]],
        field="TITLE-ABS-KEY",
        years=[2020, 2021],
    )
    assert list(out.columns) == ["label", "query", "n", "type", "size", "members"]
    assert list(out["n"]) == [100, 40, 7]
    assert out["n"].dtype == "Int64"
    assert out.attrs["years"] == [2020, 2021]
    # One count request per row.
    assert sum(seen.values()) == 3


def test_plot_scopus_intersections_returns_an_axes():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from scopusflow.plots import plot_scopus_intersections

    df = pd.DataFrame({
        "label": ["A", "B", "A × B"],
        "n": pd.array([100, 40, 8], dtype="Int64"),
        "type": ["concept", "concept", "intersection"],
    })
    ax = plot_scopus_intersections(df, highlight=["A × B"])
    assert isinstance(ax, matplotlib.axes.Axes)
    assert ax.get_xscale() == "log"
    # The focal row is labelled in the legend.
    legend_texts = [t.get_text() for t in ax.get_legend().get_texts()]
    assert "Focal intersection" in legend_texts


def test_plot_drops_nonpositive_counts_with_a_warning():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from scopusflow.plots import plot_scopus_intersections

    df = pd.DataFrame({
        "label": ["A", "B"],
        "n": pd.array([100, 0], dtype="Int64"),
        "type": ["concept", "concept"],
    })
    with pytest.warns(UserWarning, match="log axis"):
        ax = plot_scopus_intersections(df)
    assert len(ax.get_yticklabels()) == 1
