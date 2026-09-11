from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.experiments.schemas import (
    ComponentDefinition,
    DiagnosticArtifactSelection,
    ExpectedBehavior,
    InterfaceDefinition,
    KnowledgeScope,
    RuntimeExpectations,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextLog(StrictModel):
    id: str
    level: str
    message: str
    event_code: Optional[str]
    occurred_at: datetime
    is_test_data: bool
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ContextHeartbeat(StrictModel):
    id: str
    observed_at: datetime
    received_at: datetime
    is_test_data: bool
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ContextReading(StrictModel):
    id: str
    sensor_type: str
    metric_key: str
    value: float
    unit: Optional[str]
    observed_at: datetime
    is_test_data: bool
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class DeviceDescriptor(StrictModel):
    id: str
    family: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextObservation(StrictModel):
    id: str
    component_id: Optional[str] = None
    interface_id: Optional[str] = None
    metric: str
    value: Any
    unit: Optional[str] = None
    status: Literal["normal", "warning", "error", "unknown"] = "unknown"
    observed_at: datetime
    source: str
    source_ref: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ContextEvent(StrictModel):
    id: str
    type: str
    component_id: Optional[str] = None
    interface_id: Optional[str] = None
    status: Literal["normal", "warning", "error", "unknown"] = "unknown"
    occurred_at: datetime
    source: str
    source_ref: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class RawDeviceRecord(StrictModel):
    id: Optional[str] = None
    source: str
    payload: dict[str, Any]
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UnknownRawRecord(StrictModel):
    source: str
    source_ref: str
    reason: str
    received_at: datetime
    raw_payload: dict[str, Any]


class NormalizationResult(StrictModel):
    observations: list[ContextObservation] = Field(default_factory=list)
    events: list[ContextEvent] = Field(default_factory=list)
    unknown_records: list[UnknownRawRecord] = Field(default_factory=list)


class BehaviorComparison(StrictModel):
    behavior_id: str
    kind: str
    status: Literal["satisfied", "violated", "unknown"]
    expected: dict[str, Any]
    observed: Any = None
    evidence_refs: list[str] = Field(default_factory=list)


class TroubleshootingAction(StrictModel):
    action_id: str
    status: Literal["suggested", "started", "completed", "failed"]
    recorded_at: datetime
    notes: Optional[str] = None


class DiagnosisInferenceState(StrictModel):
    rule_hits: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    suspected_faults: list[dict[str, Any]] = Field(default_factory=list)


class TeacherInterventionState(StrictModel):
    required: bool = False
    status: Literal["not_required", "pending", "reviewed"] = "not_required"


class MetricRange(StrictModel):
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "MetricRange":
        if self.minimum is None and self.maximum is None:
            raise ValueError("at least one metric bound is required")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class ExperimentTemplateContext(StrictModel):
    template_id: Optional[str] = None
    metric_ranges: dict[str, MetricRange] = Field(default_factory=dict)


class DiagnosisContext(StrictModel):
    diagnosis_id: Optional[str] = None
    device_id: str
    evaluated_at: datetime
    last_seen_at: Optional[datetime]
    logs: list[ContextLog] = Field(default_factory=list)
    heartbeats: list[ContextHeartbeat] = Field(default_factory=list)
    readings: list[ContextReading] = Field(default_factory=list)
    experiment_template: Optional[ExperimentTemplateContext] = None
    experiment_id: Optional[str] = None
    experiment_version: Optional[str] = None
    experiment_record_id: Optional[str] = None
    experiment_version_id: Optional[str] = None
    experiment_package_hash: Optional[str] = None
    experiment_package_schema_version: Optional[str] = None
    experiment_package_is_test_data: bool = False
    experiment_definition_hash: Optional[str] = None
    device: Optional[DeviceDescriptor] = None
    components: list[ComponentDefinition] = Field(default_factory=list)
    interfaces: list[InterfaceDefinition] = Field(default_factory=list)
    observations: list[ContextObservation] = Field(default_factory=list)
    events: list[ContextEvent] = Field(default_factory=list)
    unknown_raw_data: list[UnknownRawRecord] = Field(default_factory=list)
    expected_behaviors: list[ExpectedBehavior] = Field(default_factory=list)
    artifact_selection: DiagnosticArtifactSelection = Field(
        default_factory=DiagnosticArtifactSelection
    )
    knowledge_scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    runtime_expectations: Optional[RuntimeExpectations] = None
    normal_assessment: dict[str, Any] = Field(default_factory=dict)
    package_rule_document: Optional[dict[str, Any]] = None
    package_fault_tree_document: Optional[dict[str, Any]] = None
    inference_state: DiagnosisInferenceState = Field(default_factory=DiagnosisInferenceState)
    troubleshooting_history: list[TroubleshootingAction] = Field(default_factory=list)
    current_hint_level: Literal[1, 2, 3, 4] = 1
    teacher_intervention_state: TeacherInterventionState = Field(
        default_factory=TeacherInterventionState
    )


class ArtifactScope(StrictModel):
    kind: Literal["common", "interface", "component", "experiment"] = "common"
    keys: list[str] = Field(default_factory=list)


class RuleCondition(StrictModel):
    fact: Literal[
        "log_event_count",
        "seconds_since_last_seen",
        "out_of_range_count",
        "event_type_count",
        "failure_count_in_window",
        "runtime_health_failure",
        "expected_behavior_violation_count",
    ]
    operator: Literal["eq", "gte", "gt", "lte", "lt"]
    value: Union[int, float]
    params: dict[str, Any] = Field(default_factory=dict)


class DiagnosisRule(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    error_type: str = Field(min_length=1, max_length=100)
    priority: int = 0
    enabled: bool = True
    summary: str = Field(min_length=1, max_length=500)
    conditions: list[RuleCondition] = Field(min_length=1)
    source_id: str = "legacy"
    source_path: Optional[str] = None
    source_version: str = "1"
    scope: ArtifactScope = Field(default_factory=ArtifactScope)


class RuleSet(StrictModel):
    version: str = Field(min_length=1)
    rules: list[DiagnosisRule]
    source_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("rules")
    @classmethod
    def reject_duplicate_rule_ids(cls, rules: list[DiagnosisRule]) -> list[DiagnosisRule]:
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return rules


class EvidenceItem(StrictModel):
    fact: str
    observed_value: Union[int, float]
    details: list[dict[str, Any]] = Field(default_factory=list)


class DiagnosisMatch(StrictModel):
    rule_id: str
    error_type: str
    priority: int
    summary: str
    evidence: list[EvidenceItem]
    source_id: str = "legacy"
    source_version: str = "1"
    scope: ArtifactScope = Field(default_factory=ArtifactScope)


class DiagnosisOutcome(StrictModel):
    ruleset_version: str
    ruleset_hash: str
    input_fingerprint: str
    matches: list[DiagnosisMatch]


class DiagnosisRunRequest(StrictModel):
    lookback_seconds: int = Field(default=3600, ge=1, le=604800)
    experiment_template: Optional[ExperimentTemplateContext] = None
    experiment_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    experiment_version: Optional[str] = Field(default=None, min_length=1, max_length=50)
    experiment_version_id: Optional[str] = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_experiment_reference(self) -> "DiagnosisRunRequest":
        if self.experiment_version is not None and self.experiment_id is None:
            raise ValueError("experiment_version requires experiment_id")
        return self


class DiagnosisRunResponse(StrictModel):
    id: str
    device_id: str
    evaluated_at: datetime
    ruleset_version: str
    input_fingerprint: str
    matches: list[DiagnosisMatch]
    is_test_data: bool
    created_at: datetime
    deterministic_result: Optional[dict[str, Any]] = None
    explanation: Optional[dict[str, Any]] = None
    ai_enhancement: Optional[dict[str, Any]] = None
    episode: Optional[dict[str, Any]] = None
    experiment_id: Optional[str] = None
    experiment_version: Optional[str] = None
    experiment_version_id: Optional[str] = None
    knowledge_scope: Optional[dict[str, Any]] = None


class DiagnosisEvidenceResponse(StrictModel):
    id: str
    diagnosis_id: str
    experiment_version_id: Optional[str] = None
    evidence_type: str
    source_type: str
    source_ref: str
    normalized_value: dict[str, Any]
    occurred_at: datetime
    created_at: datetime
