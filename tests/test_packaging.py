"""Offline checks on the packaging metadata declared in pyproject.toml."""

from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject():
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


def test_build_backend_carries_no_upper_bound(pyproject):
    # hatchling was once held below 1.32 because twine could not parse the
    # Metadata-Version 2.5 it emits. Twine 7 accepts 2.5, so a ceiling would only
    # keep the build on an old backend and invite Dependabot to nudge it upwards.
    hatchling = [r for r in pyproject["build-system"]["requires"] if r.startswith("hatchling")]
    assert hatchling == ["hatchling"]


def test_licence_is_declared_once_as_an_spdx_expression(pyproject):
    # PEP 639 deprecates licence classifiers and lets build backends reject one
    # that accompanies a License-Expression, which the string below produces.
    project = pyproject["project"]
    assert project["license"] == "MIT"
    licence_classifiers = [c for c in project["classifiers"] if c.startswith("License ::")]
    assert licence_classifiers == []
