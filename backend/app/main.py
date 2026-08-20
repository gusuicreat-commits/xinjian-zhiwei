from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.api.v1.router import api_router
from app.api.v1.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

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


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Device-ID",
        "X-Device-Token",
        "X-Review-Token",
    ],
)


@app.middleware("http")
async def request_security_and_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    if not request_id or len(request_id) > 100:
        request_id = str(uuid4())
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    logger.info(
        "http_request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    )
    return response


# Conventional probe paths remain available at the service root for container
# orchestrators. The versioned aliases are retained for backwards compatibility.
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)
