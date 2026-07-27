from typing import Literal, Optional

from pydantic import BaseModel


class ReadinessItem(BaseModel):
    key: str
    label: str
    status: Literal["ready", "blocked", "not_required", "test_only"]
    evidence: str
    required_input: Optional[str] = None


class ReadinessResponse(BaseModel):
    overall: Literal["ready", "blocked", "test_only"]
    version: str
    software_ready: bool
    demo_ready: bool
    hardware_ready: bool
    knowledge_ready: bool
    organization_ready: bool
    production_ready: bool
    items: list[ReadinessItem]
