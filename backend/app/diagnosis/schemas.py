from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextLog(StrictModel):
    id: str
    level: str
    message: str
    event_code: Optional[str]
    occurred_at: datetime
    is_test_data: bool


class ContextHeartbeat(StrictModel):
    id: str
    observed_at: datetime
    received_at: datetime
    is_test_data: bool


class ContextReading(StrictModel):
    id: str
    sensor_type: str
    metric_key: str
    value: float
    unit: Optional[str]
    observed_at: datetime
    is_test_data: bool


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
    device_id: str
    evaluated_at: datetime
    last_seen_at: Optional[datetime]
    logs: list[ContextLog] = Field(default_factory=list)
    heartbeats: list[ContextHeartbeat] = Field(default_factory=list)
    readings: list[ContextReading] = Field(default_factory=list)
    experiment_template: Optional[ExperimentTemplateContext] = None


class RuleCondition(StrictModel):
    fact: Literal["log_event_count", "seconds_since_last_seen", "out_of_range_count"]
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


class RuleSet(StrictModel):
    version: str = Field(min_length=1)
    rules: list[DiagnosisRule]

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


class DiagnosisOutcome(StrictModel):
    ruleset_version: str
    ruleset_hash: str
    input_fingerprint: str
    matches: list[DiagnosisMatch]


class DiagnosisRunRequest(StrictModel):
    lookback_seconds: int = Field(default=3600, ge=1, le=604800)
    experiment_template: Optional[ExperimentTemplateContext] = None


class DiagnosisRunResponse(StrictModel):
    id: str
    device_id: str
    evaluated_at: datetime
    ruleset_version: str
    input_fingerprint: str
    matches: list[DiagnosisMatch]
    is_test_data: bool
    created_at: datetime
