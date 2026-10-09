from typing import Literal

from pydantic import BaseModel, ConfigDict


class KnowledgeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework_ready: bool = True
    content_available: bool
    case_count: int = 0
    approved_case_count: int = 0
    matching_mode: Literal["structured"] = "structured"
    notice: str
