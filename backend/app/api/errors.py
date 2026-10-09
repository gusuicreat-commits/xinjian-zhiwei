"""HTTP mapping shared by the production app and isolated evaluation apps."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import (
    AccessDenied,
    ConflictError,
    DomainError,
    InvalidRequest,
    StaleError,
    TemporarilyUnavailable,
)
from app.services.auth import AuthorizationDenied


async def authorization_denied_handler(request: Request, exc: AuthorizationDenied):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": "CURRENT_AUTHORIZATION_DENIED", "message": str(exc)}},
    )


async def access_denied_handler(request: Request, exc: AccessDenied):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


def _detail_response(status_code: int, exc: DomainError):
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


async def conflict_handler(request: Request, exc: ConflictError):
    return _detail_response(409, exc)


async def invalid_request_handler(request: Request, exc: InvalidRequest):
    return _detail_response(422, exc)


async def stale_handler(request: Request, exc: StaleError):
    return _detail_response(409, exc)


async def temporarily_unavailable_handler(request: Request, exc: TemporarilyUnavailable):
    # Runtime exception text can contain DSNs or source payloads. Only publish
    # the stable code; QueryUnavailable already used this exact string detail.
    return JSONResponse(status_code=503, content={"detail": exc.error_code})


def register_error_handlers(app: FastAPI) -> None:
    """Register the five categories and the existing authorization envelope.

    Local adapters remain authoritative where detail/status/rollback differs or
    an isolated evaluation application has not opted into these handlers.
    """
    app.add_exception_handler(AccessDenied, access_denied_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_exception_handler(InvalidRequest, invalid_request_handler)
    app.add_exception_handler(StaleError, stale_handler)
    app.add_exception_handler(TemporarilyUnavailable, temporarily_unavailable_handler)
    app.add_exception_handler(AuthorizationDenied, authorization_denied_handler)
