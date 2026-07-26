from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import Field

from app.diagnosis.schemas import StrictModel


class DiagnosisCore(StrictModel):
    diagnosis_result_id: str
    primary_error_code: Optional[str]
    summary: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    suggested_steps: list[str] = Field(default_factory=list)
    hint_level: int = Field(ge=1, le=4)
    need_teacher_help: bool
    rule_ids: list[str] = Field(default_factory=list)
    knowledge_chunk_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DeterministicExplanation(StrictModel):
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    hint_level: int = Field(ge=1, le=4)
    need_teacher_help: bool
    limitations: list[str] = Field(default_factory=list)
    provenance: Literal["rules_and_reviewed_knowledge"] = "rules_and_reviewed_knowledge"


class AIEnhancementState(StrictModel):
    status: Literal[
        "disabled",
        "skipped",
        "cache_hit",
        "local_success",
        "cloud_success",
        "failed_fallback",
    ]
    trigger_reason: str
    route: str
    route_path: str = "deterministic_only"
    cache_status: Literal["not_checked", "miss", "hit"]
    fallback_reason: Optional[str] = None
    call_record_id: Optional[str] = None


class DiagnosisEpisodeResponse(StrictModel):
    id: str
    status: Literal["open", "escalated", "resolved"]
    primary_error_code: str
    started_at: datetime
    last_seen_at: datetime
    failure_count: int
    current_hint_level: int
    ai_call_count: int


class AIPolicyDecision(StrictModel):
    should_call: bool
    reason: str
    confidence: float = Field(ge=0, le=1)
    budget_allowed: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
