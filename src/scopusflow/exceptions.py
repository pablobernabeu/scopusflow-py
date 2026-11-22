"""scopusflow's own exception types.

Two cases are raised as scopusflow's own types, because pybliometrics' error
would mislead. Other pybliometrics exceptions reach the caller unchanged,
except where a function's docstring says it catches them. scopus_abstract()
turns the error for one identifier into a warning and a row of NA, and
fetch_plan() raises pybliometrics' refusal to page a large cell by offset
again, naming the cell.

Entitlement is a property of the account, so a 403 met while retrieving one
identifier will meet the same 403 on every other identifier in the batch. The
error says so and stops the batch, where pybliometrics would raise its generic
HTTP error for each identifier in turn.

pybliometrics 4 also needs ``pybliometrics.init()`` once in every Python
session. A search made before it fails with 'No configuration file found',
even when a configuration file is in place, so scopusflow checks first and
says which call is missing.

A spent weekly quota gives a warning rather than an error, because it usually
comes part-way through a batch of abstracts, and an error would discard the
rows already retrieved.
"""

from __future__ import annotations


class ScopusFlowForbiddenError(Exception):
    """Raised when the Scopus API refuses a request (HTTP 403), most often
    because the configured key's entitlement does not cover the requested
    Abstract Retrieval view or field."""


class ScopusFlowConfigError(RuntimeError):
    """Raised before any request when pybliometrics has not been initialised
    in this Python session.

    pybliometrics 4 reads its configuration only when ``pybliometrics.init()``
    is called, so a configuration file on disk is not enough by itself. Run
    ``import pybliometrics; pybliometrics.init()`` once per session before the
    first search. It reads the configuration file, or creates it and asks for
    your key when there is none. scopusflow never calls ``init()`` itself.
    """


class ScopusFlowQuotaWarning(UserWarning):
    """Warned once when
    [`scopus_abstract`][scopusflow.abstract.scopus_abstract] stops a batch
    because the API key's weekly quota is spent.

    pybliometrics raises ``Scopus429Error`` only after it has tried every
    configured key, and documents the error as a depleted quota, so no later
    identifier in the batch could succeed. The rows already retrieved are
    returned, and each identifier not retrieved gets a row of ``NA``.
    """
