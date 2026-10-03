"""scopusflow's own exception types.

The package otherwise lets pybliometrics' exceptions bubble up unchanged (see
each module's docstring for what it catches and why). Two cases are raised as
scopusflow-specific types, because pybliometrics' own error would mislead.

Entitlement is a property of the account, so a 403 met while retrieving one
identifier will meet the same 403 on every other identifier in the batch. The
message says so plainly, where pybliometrics would surface its generic HTTP
error for each one in turn.

pybliometrics 4 also needs ``pybliometrics.init()`` once in every Python
session. A search made before it fails with "No configuration file found",
even when a configuration file is in place, so scopusflow checks first and
says which call is missing.
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
