from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIKnowledgeReference(StrictAIModel):
    chunk_id: str
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
    allowed_evidence: list[str]
    user_question: Optional[str] = None
    output_language: str = "zh-CN"
    is_test_data: bool


class AIPossibleCause(StrictAIModel):
    cause: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    knowledge_chunk_ids: list[str] = Field(default_factory=list, max_length=20)


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
    embedding_client_configured: bool
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
