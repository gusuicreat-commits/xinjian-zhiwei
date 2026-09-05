from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import Field, field_validator, model_validator

from app.diagnosis.schemas import ArtifactScope, StrictModel


class EvidenceCriterion(StrictModel):
    fact: Literal[
        "diagnosis_error_count",
        "log_event_count",
        "event_type_count",
        "expected_behavior_violation_count",
    ]
    operator: Literal["eq", "gte", "gt", "lte", "lt"]
    value: Union[int, float]
    weight: int = Field(ge=1, le=100)
    description: str = Field(min_length=1, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict)


class CauseDefinition(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    evidence: list[EvidenceCriterion] = Field(min_length=1)
    hints: dict[int, str]

    @field_validator("hints")
    @classmethod
    def require_all_hint_levels(cls, hints: dict[int, str]) -> dict[int, str]:
        if set(hints) != {1, 2, 3, 4}:
            raise ValueError("hints must define levels 1 through 4")
        return hints


class EscalationLevel(StrictModel):
    level: Literal[1, 2, 3, 4]
    min_failure_count: int = Field(ge=1)
    min_duration_seconds: int = Field(ge=0)


class FaultTreeDefinition(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    status: Literal["placeholder", "approved"] = "placeholder"
    enabled: bool = True
    continuity_window_seconds: int = Field(default=3600, ge=1)
    trigger: list[EvidenceCriterion] = Field(min_length=1)
    causes: list[CauseDefinition] = Field(min_length=2)
    escalation: list[EscalationLevel] = Field(min_length=4, max_length=4)
    source_id: str = "legacy"
    source_path: Optional[str] = None
    source_version: str = "1"
    scope: ArtifactScope = Field(default_factory=ArtifactScope)

    @model_validator(mode="after")
    def validate_unique_ids_and_levels(self) -> "FaultTreeDefinition":
        cause_ids = [cause.id for cause in self.causes]
        if len(cause_ids) != len(set(cause_ids)):
            raise ValueError("cause ids must be unique within a fault tree")
        if {item.level for item in self.escalation} != {1, 2, 3, 4}:
            raise ValueError("escalation must define levels 1 through 4")
        return self


class FaultTreeSet(StrictModel):
    version: str = Field(min_length=1)
    trees: list[FaultTreeDefinition]
    source_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("trees")
    @classmethod
    def reject_duplicate_tree_ids(
        cls, trees: list[FaultTreeDefinition]
    ) -> list[FaultTreeDefinition]:
        ids = [tree.id for tree in trees]
        if len(ids) != len(set(ids)):
            raise ValueError("fault tree ids must be unique")
        return trees


class MatchedCauseEvidence(StrictModel):
    fact: str
    description: str
    weight: int
    observed_value: Union[int, float]
    details: list[dict[str, Any]] = Field(default_factory=list)


class RankedCause(StrictModel):
    cause_id: str
    title: str
    score: int = Field(ge=1, le=100)
    confidence: Literal["low", "medium", "high"]
    evidence: list[MatchedCauseEvidence]


class GuidanceHint(StrictModel):
    cause_id: str
    level: Literal[1, 2, 3, 4]
    text: str


class FaultTreeEvaluation(StrictModel):
    tree_id: str
    tree_title: str
    tree_status: Literal["placeholder", "approved"]
    hint_level: Literal[1, 2, 3, 4]
    failure_count: int
    anomaly_duration_seconds: int
    teacher_intervention_required: bool
    ranked_causes: list[RankedCause]
    hints: list[GuidanceHint]
    source_id: str = "legacy"
    source_version: str = "1"
    scope: ArtifactScope = Field(default_factory=ArtifactScope)


class GuidanceRecordResponse(FaultTreeEvaluation):
    id: str
    diagnosis_result_id: str
    device_id: str
    fault_tree_version: str
    created_at: datetime


class GuidanceRunResponse(StrictModel):
    items: list[GuidanceRecordResponse]


class InterventionItem(StrictModel):
    device_id: str
    diagnosis_result_id: str
    tree_id: str
    tree_title: str
    hint_level: Literal[4]
    failure_count: int
    anomaly_duration_seconds: int
    created_at: datetime
