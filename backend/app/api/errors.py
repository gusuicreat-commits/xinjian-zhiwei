"""HTTP mapping shared by the production app and isolated evaluation apps."""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.auth import AuthorizationDenied


async def authorization_denied_handler(request: Request, exc: AuthorizationDenied):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": "CURRENT_AUTHORIZATION_DENIED", "message": str(exc)}},
    )
