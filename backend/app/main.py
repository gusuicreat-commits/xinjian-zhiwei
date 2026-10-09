import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse, JSONResponse

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.api.errors import authorization_denied_handler
from app.api.http_boundary import ResponseBoundary
from app.api.v1.router import api_router
from app.api.v1.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.auth import AuthorizationDenied

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_started",
        extra={
            "environment": settings.app_env,
            "version": settings.app_version,
            "diagnosis_graph_version": settings.diagnosis_graph_version,
            "diagnosis_checkpoint_backend": settings.diagnosis_checkpoint_backend,
        },
    )
    app.state.diagnosis_graph = None
    if settings.diagnosis_workflow_enabled:
        if settings.diagnosis_checkpoint_backend == "postgres":
            from langgraph.checkpoint.postgres import PostgresSaver

            with PostgresSaver.from_conn_string(settings.diagnosis_checkpoint_dsn or "") as saver:
                if settings.diagnosis_checkpoint_setup:
                    saver.setup()
                app.state.diagnosis_graph = build_diagnosis_graph(saver)
                yield
        else:
            from langgraph.checkpoint.memory import InMemorySaver

            app.state.diagnosis_graph = build_diagnosis_graph(InMemorySaver())
            yield
    else:
        yield
    logger.info("application_stopped")


class BoundedFastAPI(FastAPI):
    def build_middleware_stack(self):
        return ResponseBoundary(super().build_middleware_stack(), logger)


app = BoundedFastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


app.add_exception_handler(AuthorizationDenied, authorization_denied_handler)



app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Device-ID",
        "X-Device-Token",
        "X-Experiment-Session-ID",
        "X-Review-Token",
    ],
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500, content={"detail": {"code": "INTERNAL_ERROR", "message": "Request failed"}}
    )


def _documentation_response(document: HTMLResponse) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    html = document.body.decode("utf-8").replace("<script", f'<script nonce="{nonce}"')
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}' https://cdn.jsdelivr.net; "
                "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com "
                "https://cdn.redoc.ly/redoc/logo-mini.svg; "
                "connect-src 'self'; worker-src blob:; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


@app.get("/docs", include_in_schema=False)
def swagger_documentation(request: Request):
    root = request.scope.get("root_path", "").rstrip("/")
    return _documentation_response(
        get_swagger_ui_html(
            openapi_url=root + app.openapi_url,
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=root + "/docs/oauth2-redirect",
        )
    )


@app.get("/redoc", include_in_schema=False)
def redoc_documentation(request: Request):
    root = request.scope.get("root_path", "").rstrip("/")
    return _documentation_response(
        get_redoc_html(
            openapi_url=root + app.openapi_url,
            title=app.title + " - ReDoc",
            with_google_fonts=False,
        )
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
def swagger_oauth_redirect():
    return _documentation_response(get_swagger_ui_oauth2_redirect_html())


# Conventional probe paths remain available at the service root for container
# orchestrators. The versioned aliases are retained for backwards compatibility.
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)
