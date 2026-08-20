"""scopusflow's own exception types.

The package otherwise lets pybliometrics' exceptions bubble up unchanged (see
each module's docstring for what it catches and why). This one case is
deliberately re-raised as a scopusflow-specific type: entitlement is a property
of the account, so a 403 met while retrieving one identifier will meet the same
403 on every other identifier in the batch. The message says so plainly, where
pybliometrics would surface its generic HTTP error for each one in turn.
"""

from __future__ import annotations


class ScopusFlowForbiddenError(Exception):
    """Raised when the Scopus API refuses a request (HTTP 403), most often
    because the configured key's entitlement does not cover the requested
    Abstract Retrieval view or field."""
