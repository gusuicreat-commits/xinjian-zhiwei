"""Outermost response boundary, including ServerErrorMiddleware responses."""

import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders


class ResponseBoundary:
    def __init__(self, app, logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", incoming) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500
        response_started = False
        response_complete = False

        async def safe_send(message):
            nonlocal status, response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers.setdefault(
                    "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                )
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception as exc:
            # ServerErrorMiddleware re-raises after its safe response. Do not let
            # the server logger echo the raw exception/credentials a second time.
            self.logger.error(
                "http_request_failed",
                extra={"request_id": request_id, "error_type": type(exc).__name__},
            )
            if not response_started:
                from fastapi.responses import JSONResponse

                response = JSONResponse(
                    status_code=500,
                    content={"detail": {"code": "INTERNAL_ERROR", "message": "Request failed"}},
                )
                await response(scope, receive, safe_send)
            elif not response_complete:
                # A streaming failure must remain a failed stream. Sanitise the
                # exception rather than sending a second header or success body.
                raise RuntimeError(
                    "response stream interrupted; request_id=" + request_id
                ) from None
        finally:
            self.logger.info(
                "http_request_completed",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": getattr(scope.get("route"), "path", "unmatched"),
                    "status_code": status,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
