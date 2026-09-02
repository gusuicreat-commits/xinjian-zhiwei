from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictKnowledgeCaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeCaseDefinition(StrictKnowledgeCaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    experiment_type: str = Field(alias="experimentType", min_length=1, max_length=100)
    error_type: str = Field(alias="errorType", min_length=1, max_length=100)
    symptom: str = Field(min_length=1, max_length=2000)
    normal_state: dict[str, Any] = Field(alias="normalState", default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    possible_causes: list[str] = Field(alias="possibleCauses", default_factory=list, max_length=20)
    solution_steps: list[str] = Field(alias="solutionSteps", default_factory=list, max_length=30)
    teacher_notes: str | None = Field(alias="teacherNotes", default=None, max_length=4000)
    facts: dict[str, Any] = Field(default_factory=dict)
    root_cause_value: str | None = Field(alias="rootCauseValue", default=None)
    root_cause_status: Literal["confirmed", "probable", "unknown"] = Field(
        alias="rootCauseStatus", default="unknown"
    )
    confirmed_by: str | None = Field(alias="confirmedBy", default=None)
    confirmed_at: datetime | None = Field(alias="confirmedAt", default=None)
    solution_record: dict[str, Any] = Field(alias="solutionRecord", default_factory=dict)
    ai_generated_fields: dict[str, Any] = Field(
        alias="aiGeneratedFields", default_factory=dict
    )
    source_type: str = Field(alias="sourceType", default="curated_template")
    facts_locked: bool = Field(alias="factsLocked", default=False)
    quality_check_passed: bool = Field(alias="qualityCheckPassed", default=False)
    review_status: Literal["draft", "pending", "approved", "rejected"] = Field(
        alias="reviewStatus", default="draft"
    )
    source_ref: str = Field(alias="sourceRef", min_length=1, max_length=500)
    version: str = Field(default="1", min_length=1, max_length=50)
    is_test_data: bool = Field(alias="isTestData", default=False)


class KnowledgeCaseResponse(StrictKnowledgeCaseModel):
    id: str
    experiment_type: str
    error_type: str
    symptom: str
    normal_state: dict[str, Any]
    evidence: list[dict[str, Any]]
    possible_causes: list[str]
    solution_steps: list[str]
    teacher_notes: str | None
    facts: dict[str, Any]
    root_cause_value: str | None
    root_cause_status: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    solution_record: dict[str, Any]
    ai_generated_fields: dict[str, Any]
    source_type: str
    facts_locked: bool
    quality_check_passed: bool
    review_status: str
    source_ref: str
    version: str
    is_test_data: bool
    created_at: datetime
    updated_at: datetime


class MatchedKnowledgeCase(StrictKnowledgeCaseModel):
    case_id: str
    experiment_type: str
    error_type: str
    symptom: str
    evidence: list[dict[str, Any]]
    possible_causes: list[str]
    solution_steps: list[str]
    teacher_notes: str | None
    root_cause_value: str | None
    root_cause_status: Literal["confirmed", "probable", "unknown"]
    source_ref: str
    version: str
    match_score: float = Field(ge=0, le=1)
    matched_on: list[str] = Field(default_factory=list)
    is_test_data: bool = False


class KnowledgeCaseDraftResponse(StrictKnowledgeCaseModel):
    id: str
    diagnosis_result_id: str
    feedback_id: str
    experiment_type: str
    error_type: str
    fact_snapshot: dict[str, Any]
    template_payload: dict[str, Any]
    polished_payload: dict[str, Any] | None
    quality_checks: list[dict[str, Any]]
    root_cause: dict[str, Any]
    solution_record: dict[str, Any]
    source_ids: list[str]
    allowed_ai_fields: list[str]
    facts_locked: bool
    ai_audit: dict[str, Any]
    status: str
    reviewer_ref: str | None
    reviewed_at: datetime | None
    is_test_data: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeCaseDraftApproveRequest(StrictKnowledgeCaseModel):
    case_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    confirmed_root_cause: str = Field(min_length=1, max_length=200)
    final_solution_steps: list[str] = Field(min_length=1, max_length=30)
    confirmation_note: str = Field(min_length=1, max_length=4000)


class AICasePolishFields(StrictKnowledgeCaseModel):
    title: str = Field(min_length=1, max_length=300)
    symptom_description: str = Field(
        alias="symptomDescription", min_length=1, max_length=2000
    )
    teaching_note: str = Field(alias="teachingNote", min_length=1, max_length=4000)
    solution_summary: str = Field(
        alias="solutionSummary", min_length=1, max_length=2000
    )
    source_ids: list[str] = Field(alias="sourceIds", min_length=1, max_length=100)
