"""Bounded public projections; none of these fields grant AI tool authority."""
from typing import Any, Literal

from pydantic import Field

from app.diagnosis.schemas import StrictModel


class MemorySource(StrictModel):
    kind: Literal["package", "package_case", "case", "unresolved_case"]
    id: str
    version: str | None
    hash: str | None
    package_id: str | None = None


class FactMemory(StrictModel):
    kind: Literal["configuration"]
    subject: str
    value: dict[str, Any]
    source: MemorySource
    physical_verification: Literal["not_asserted"]
    is_test_data: bool


class ExperienceMemory(StrictModel):
    source: MemorySource
    status: Literal["approved_reference"]
    root_cause_for_this_task: Literal["not_confirmed"]


class WorkingFeedback(StrictModel):
    id: str
    episode_id: str | None
    action: str
    source: Literal["student_report"]
    created_at: str


class WorkingMemory(StrictModel):
    workflow_id: str
    session_id: str
    diagnosis_result_id: str | None
    package_version_id: str | None
    revision: int
    active: bool
    status: str
    evidence_ids: list[str] = Field(max_length=50)
    evidence_truncated: bool
    feedback: list[WorkingFeedback] = Field(max_length=20)
    feedback_truncated: bool
    next_step: str | None
    is_test_data: bool


class MemoryContext(StrictModel):
    contract_version: Literal["memory-v1"]
    available: bool
    facts: list[FactMemory] = Field(max_length=21)
    experiences: list[ExperienceMemory] = Field(max_length=20)
    working: WorkingMemory
