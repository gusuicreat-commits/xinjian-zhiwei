from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator
from typing_extensions import TypedDict

from app.diagnosis.schemas import ExperimentTemplateContext, StrictModel

DiagnosisWorkflowStatus = Literal[
    "created",
    "collecting",
    "deterministic_analysis",
    "retrieving",
    "ai_analysis",
    "waiting_feedback",
    "waiting_teacher",
    "completed",
    "rejected",
    "failed",
]


class WorkflowRuleHit(TypedDict):
    rule_id: str
    error_type: str
    summary: str
    priority: int
    evidence: list[dict[str, Any]]


class WorkflowCandidateCause(TypedDict):
    cause_id: str
    name: str
    score: float
    evidence_refs: list[str]


class WorkflowRetrievedChunk(TypedDict):
    chunk_id: str
    source_id: str
    title: str
    score: float
    metadata: dict[str, Any]


class DiagnosisState(TypedDict, total=False):
    """V2 state for one controlled diagnosis run.

    The first block is the product-facing state contract. Fields below it retain
    identifiers, audit metadata and V1 aliases required by existing APIs and
    persisted workflow records.
    """

    device_status: dict[str, Any]
    experiment_type: str | None
    logs: list[dict[str, Any]]
    sensor_data: list[dict[str, Any]]
    sensor_values: list[dict[str, Any]]
    experiment_context: dict[str, Any]
    error_type: str | None
    evidence: list[dict[str, Any]]
    possible_causes: list[dict[str, Any]]
    knowledge_context: list[WorkflowRetrievedChunk]
    hint_level: int
    student_feedback: dict[str, Any] | None
    historical_failures: int
    attempt_count: int
    need_teacher_help: bool
    diagnosis_status: DiagnosisWorkflowStatus
    failure_count: int
    anomaly_duration_seconds: int
    reasoned_causes: list[dict[str, Any]]
    reasoning_status: Literal["ranked", "unknown", "fallback"]
    reasoning_summary: str
    reasoning_mode: Literal["ai", "deterministic_fallback"]
    missing_evidence: list[str]
    next_verification_action: str | None
    evidence_conflict: bool
    evidence_registry: list[dict[str, Any]]
    allowed_verification_actions: list[dict[str, Any]]
    knowledge_validation: dict[str, Any]

    # Workflow identity and audit metadata.
    diagnosis_id: str
    student_user_id: str
    experiment_session_id: str
    diagnosis_result_id: str
    device_id: str
    experiment_template: dict[str, Any] | None
    experiment_id: str | None
    experiment_version: str | None
    question: str | None
    lookback_seconds: int
    evaluated_at: str
    context_ref: dict[str, Any]
    rule_hits: list[WorkflowRuleHit]
    rule_engine_version: str
    rule_engine_hash: str
    input_fingerprint: str
    fault_tree_candidates: list[WorkflowCandidateCause]
    fault_tree_version: str
    evidence_score: float
    guidance_level: int
    needs_rag: bool
    retrieval_query: str
    retrieved_chunks: list[WorkflowRetrievedChunk]
    ai_result: dict[str, Any] | None
    deterministic_result: dict[str, Any] | None
    model_id: str | None
    needs_teacher: bool
    teacher_review: dict[str, Any] | None
    status: DiagnosisWorkflowStatus
    errors: Annotated[list[str], operator.add]
    node_trace: Annotated[list[str], operator.add]
    node_metrics: Annotated[list[dict[str, Any]], operator.add]


class DiagnosisWorkflowStartRequest(StrictModel):
    lookback_seconds: int = Field(default=3600, ge=1, le=604800)
    experiment_template: ExperimentTemplateContext | None = None
    experiment_id: str | None = Field(default=None, min_length=1, max_length=100)
    experiment_version: str | None = Field(default=None, min_length=1, max_length=50)
    question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_experiment_reference(self) -> DiagnosisWorkflowStartRequest:
        if self.experiment_version is not None and self.experiment_id is None:
            raise ValueError("experiment_version requires experiment_id")
        return self


class TeacherEditedDiagnosis(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)
    possible_causes: list[str] | None = Field(default=None, max_length=20)
    steps: list[str] | None = Field(default=None, max_length=30)
    limitations: list[str] | None = Field(default=None, max_length=20)


class DiagnosisWorkflowReviewRequest(StrictModel):
    action: Literal["approve", "edit", "reject"]
    comment: str | None = Field(default=None, max_length=4000)
    edited_result: TeacherEditedDiagnosis | None = None

    @model_validator(mode="after")
    def validate_edit_payload(self) -> DiagnosisWorkflowReviewRequest:
        if self.action == "edit" and self.edited_result is None:
            raise ValueError("edit action requires edited_result")
        if self.action != "edit" and self.edited_result is not None:
            raise ValueError("edited_result is only accepted for edit action")
        return self


class DiagnosisWorkflowReviewResponse(StrictModel):
    id: str
    reviewer_user_id: str
    action: Literal["approve", "edit", "reject"]
    comment: str | None
    edited_result: dict[str, Any] | None
    created_at: datetime


class DiagnosisWorkflowMetricsResponse(StrictModel):
    total: int
    in_progress: int
    completed: int
    waiting_teacher: int
    rejected: int
    failed: int
    reviewed: int
    edit_rate: float
    reject_rate: float
    needs_rag_count: int
    resume_count: int
    average_node_duration_ms: float | None
    ai_call_count: int
    ai_input_tokens: int
    ai_output_tokens: int
    ai_estimated_cost: float
    student_feedback_count: int
    student_resolved_count: int
    student_resolution_rate: float | None


class DiagnosisWorkflowResponse(StrictModel):
    id: str
    diagnosis_id: str
    diagnosis_result_id: str | None
    device_id: str
    student_user_id: str
    experiment_session_id: str
    graph_thread_id: str
    graph_version: str
    status: DiagnosisWorkflowStatus
    current_node: str | None
    evidence_score: float | None
    guidance_level: int | None
    needs_rag: bool
    needs_teacher: bool
    rule_engine_version: str | None
    fault_tree_version: str | None
    embedding_version: str | None
    model_id: str | None
    node_trace: list[str]
    node_metrics: list[dict[str, Any]]
    retrieval_audit: dict[str, Any]
    resume_count: int
    final_result: dict[str, Any] | None
    error_messages: list[str]
    review_request: dict[str, Any] | None = None
    reviews: list[DiagnosisWorkflowReviewResponse] = Field(default_factory=list)
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
