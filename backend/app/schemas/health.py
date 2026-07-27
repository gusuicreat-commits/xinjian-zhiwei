from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str
    environment: str


class DependencyHealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    dependencies: dict[str, dict[str, Any]]


class OpsStatusResponse(BaseModel):
    version: str
    environment: str
    database: str
    ai_enabled: bool
    ai_configured: bool
    formal_knowledge_documents: int
    test_knowledge_documents: int
    pending_interventions: int
    active_sessions: int
