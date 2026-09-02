from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIKnowledgeReference(StrictAIModel):
    chunk_id: str
    case_id: Optional[str] = None
    source_key: str
    source_title: str
    source_type: Optional[str] = None
    source_uri: Optional[str]
    source_version: Optional[str] = None
    locator: dict[str, Any] = Field(default_factory=dict)
    content: str
    similarity: float
    review_status: Literal["approved"] = "approved"
    retrieval_scores: dict[str, float] = Field(default_factory=dict)
    is_test_data: bool

    @model_validator(mode="after")
    def expose_structured_case_id(self) -> "AIKnowledgeReference":
        if self.source_type == "structured_case" and self.case_id is None:
            self.case_id = self.chunk_id
        return self


class AIDiagnosisInput(StrictAIModel):
    diagnosis_result_id: str
    episode_id: Optional[str] = None
    anonymous_device_id: str
    device_state: dict[str, Any]
    logs: list[dict[str, Any]]
    sensor_readings: list[dict[str, Any]]
    heartbeats: list[dict[str, Any]]
    rule_matches: list[dict[str, Any]]
    fault_tree_guidance: list[dict[str, Any]]
    knowledge: list[AIKnowledgeReference]
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    allowed_evidence: list[str]
    user_question: Optional[str] = None
    output_language: str = "zh-CN"
    is_test_data: bool


class AIReasonedCause(StrictAIModel):
    cause_id: str = Field(min_length=1, max_length=100)
    cause: str = Field(min_length=1, max_length=500)
    support_level: Literal["high", "medium", "low", "unknown"] = "unknown"
    used_evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    reason: str = Field(default="信息不足。", min_length=1, max_length=1000)
    # Compatibility-only fields for replaying records created before the V2
    # evidence-ID contract. New prompts never ask the model to emit them.
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    rationale: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def normalize_legacy_reasoning(self) -> "AIReasonedCause":
        if self.support_level == "unknown" and self.confidence is not None:
            self.support_level = (
                "high"
                if self.confidence >= 0.75
                else "medium"
                if self.confidence >= 0.45
                else "low"
            )
        if not self.used_evidence_ids and self.evidence:
            self.used_evidence_ids = list(self.evidence)
        if self.reason == "信息不足。" and self.rationale:
            self.reason = self.rationale
        return self


class AIReasoningResult(StrictAIModel):
    error_type: Optional[str] = Field(default=None, max_length=100)
    conclusion: Literal["ranked", "unknown"]
    ranked_causes: list[AIReasonedCause] = Field(default_factory=list, max_length=20)
    summary: str = Field(min_length=1, max_length=1000)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    next_verification_action: str | None = Field(default=None, max_length=1000)
    conflict: bool = False


class AIPossibleCause(StrictAIModel):
    cause: str = Field(min_length=1, max_length=500)
    support_level: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    knowledge_chunk_ids: list[str] = Field(default_factory=list, max_length=20)
    knowledge_case_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_legacy_confidence(self) -> "AIPossibleCause":
        if self.support_level == "unknown" and self.confidence is not None:
            self.support_level = (
                "high"
                if self.confidence >= 0.75
                else "medium"
                if self.confidence >= 0.45
                else "low"
            )
        return self


class AIStructuredExplanation(StrictAIModel):
    error_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=50)
    possible_causes: list[AIPossibleCause] = Field(default_factory=list, max_length=20)
    steps: list[str] = Field(default_factory=list, max_length=30)
    hint_level: int = Field(ge=1, le=4)
    need_teacher_help: bool
    limitations: list[str] = Field(default_factory=list, max_length=20)


class AIExplanationResponse(StrictAIModel):
    call_record_id: str
    diagnosis_result_id: str
    status: Literal["skipped", "succeeded", "failed"]
    mode: Literal["rules_only", "ai_enhanced"]
    provider_configured: bool
    rules_preserved: bool = True
    explanation: Optional[AIStructuredExplanation] = None
    knowledge_references: list[AIKnowledgeReference] = Field(default_factory=list)
    notice: str
    enhancement_status: Literal[
        "disabled",
        "skipped",
        "cache_hit",
        "local_success",
        "cloud_success",
        "failed_fallback",
    ] = "skipped"
    trigger_reason: str = "UNSPECIFIED"
    route: str = "none"
    route_path: str = "deterministic_only"
    deterministic_result: Optional[dict[str, Any]] = None


class AIStatusResponse(StrictAIModel):
    framework_ready: bool = True
    provider_configured: bool
    require_knowledge: bool
    provider: Optional[str]
    model: Optional[str]
    transport: str
    prompt_version: str
    notice: str
    ai_enabled: bool = False
    local_configured: bool = False
    cloud_configured: bool = False
    thinking_enabled: bool = False
    production_route: str = "cache → deepseek → deterministic_fallback"


class AIExplanationRequest(StrictAIModel):
    user_question: Optional[str] = Field(default=None, min_length=1, max_length=2000)
