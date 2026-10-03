# Contributing

Thanks for your interest in improving scopusflow. Contributions of all sizes are
welcome, from typo fixes to new workflow helpers.

## Setup

Clone the repository and install the package in editable mode with the
development and plotting extras:

```bash
pip install -e ".[dev,plot]"
```

The pure-logic helpers need no Scopus API key. Everything that contacts the API
calls pybliometrics, which keeps the key in `~/.config/pybliometrics.cfg` and
reads it only after `import pybliometrics; pybliometrics.init()`, once in every
session. Without that call, scopusflow raises `ScopusFlowConfigError` before
any request.

## Run the tests

The test suite is offline by design, so it runs without a key or a network
connection. Point Python at `src` and run pytest:

```bash
PYTHONPATH=src pytest
```

## Lint

Code is linted with [ruff](https://docs.astral.sh/ruff/) at a line length of
100. Please make sure your changes are clean before opening a pull request:

```bash
ruff check .
```

## Releasing

Changes collect under `## [Unreleased]` in `CHANGELOG.md`. Nothing presents a
version as released before its tag exists, so `CITATION.cff`, the README's
citation and the version in the documentation header keep naming the last
release until then. A release runs through these steps:

1. Bump `__version__` in [`src/scopusflow/__init__.py`](https://github.com/pablobernabeu/scopusflow-py/blob/main/src/scopusflow/__init__.py) (the version in
   `pyproject.toml` is dynamic and reads it from there). The bump can come well
   before the release, and it dates nothing.
2. Verify with `PYTHONPATH=src pytest`, `ruff check .`, `python -m build` and
   `python -m twine check dist/*`. The local build only shows that the package
   builds. Never upload it, since `publish.yml` builds the release from the
   tagged commit.
3. On the day of the release, date it in one commit. In `CHANGELOG.md`, rename
   `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and drop any note that the
   section is not yet released. Then add its compare link at the foot and point
   the `[Unreleased]` link at the new tag. Set `version` and `date-released` in
   `CITATION.cff`, the version and year in the README's citation, and the
   version in the `mkdocs.yml` fallback. Use the UTC date of the day you publish
   the GitHub release. Tag the commit with
   `git tag -a vX.Y.Z -m "scopusflow X.Y.Z"` and run
   `python tools/check_release.py --tag vX.Y.Z`. It makes the same check as
   `publish.yml`, against today's date. Push the commit and the tag once it
   passes.
4. Create the GitHub release for the tag the same day. Publishing it runs
   `publish.yml`, which repeats the check and then builds the distribution and
   uploads it to PyPI through trusted publishing, so no token is stored in the
   repository. The documentation is rebuilt as well, and its header then names
   the new release.

If the app's layout changed in the release, recapture `docs/assets/app-window.png`
and `docs/assets/app-compare.png` from `scopusflow-gui` in demo mode, which needs
no key. Every other figure on the docs site is rendered at build time and cannot
go stale, but these two are static and will drift silently.

Trusted publishing needs a one-time setup on PyPI. In the project's Publishing
settings, add this repository as a trusted publisher with workflow file
`publish.yml` and environment `pypi`. The workflow handles every PyPI release
from 0.1.0 onwards.

## Relationship to other projects

scopusflow is the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/); the two aim to mirror
each other's behaviour and naming where it makes sense, so a fix in one is often
worth porting to the other.

It is built deliberately *on top of*
[pybliometrics](https://pybliometrics.readthedocs.io), which already handles the
Scopus HTTP, cursor pagination, quota rotation and per-query caching. scopusflow
adds the reproducible workflow around it, and re-implements none of that
plumbing, so changes that belong in the API layer should go upstream to
pybliometrics.
