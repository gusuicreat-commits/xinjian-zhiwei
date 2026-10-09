"""Domain error taxonomy; HTTP presentation belongs to app.api.errors.

The stable error_code is internal metadata, not a new response field. Legacy
wrappers spanning several categories inherit DomainError until their producers
can be split: inheritance alone must not invent certainty or permission to retry.
"""


class DomainError(Exception):
    """Base for classified failures and explicitly retained mixed legacy wrappers."""


class AccessDenied(DomainError, PermissionError):
    """Invalid authentication (401) or insufficient current authorization (403)."""

    error_code = "ACCESS_DENIED"
    status_code = 403


class ConflictError(DomainError, ValueError):
    """State, version or idempotency conflict; refresh/reconcile before retrying."""

    error_code = "CONFLICT"


class InvalidRequest(DomainError, ValueError):
    """The request itself is invalid; retrying unchanged input cannot repair it."""

    error_code = "INVALID_REQUEST"


class StaleError(DomainError, ValueError):
    """Source/version is definitively invalid, never inferred from a read failure.

    An uncaught error maps to 409. Existing contracts may consume it and return
    a 200 stale projection; that behavior must be preserved at those boundaries.
    """

    error_code = "STALE"


class TemporarilyUnavailable(DomainError, RuntimeError):
    """Retryable infrastructure failure; roll back business writes before raising.

    This category does not authorize resending a Provider request whose outcome
    is unknown. Such legacy wrappers must retain their explicit governance.
    """

    error_code = "TEMPORARILY_UNAVAILABLE"
