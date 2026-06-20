# Contributing

Thanks for your interest in improving scopusflow. Contributions of all sizes are
welcome, from typo fixes to new workflow helpers.

## Setup

Clone the repository and install the package in editable mode with the
development and plotting extras:

```bash
pip install -e ".[dev,plot]"
```

The pure-logic helpers need no Scopus API key. Only the live retrieval functions
(`fetch_plan`, `scopus_trend`, `scopus_abstract`) call pybliometrics, which
expects a key in its standard `~/.config/pybliometrics.cfg`.

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

## Relationship to other projects

scopusflow is the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/); the two aim to mirror
each other's behaviour and naming where it makes sense, so a fix in one is often
worth porting to the other.

It is built deliberately *on top of*
[pybliometrics](https://pybliometrics.readthedocs.io), which already handles the
Scopus HTTP, cursor pagination, quota rotation and per-query caching. scopusflow
adds the reproducible workflow around it rather than re-implementing that
plumbing, so changes that belong in the API layer should go upstream to
pybliometrics.
