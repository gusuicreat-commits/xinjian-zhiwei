from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StableId = str
InterfaceType = Literal["gpio", "i2c", "spi", "uart", "adc", "network"]
BehaviorKind = Literal[
    "device_online",
    "component_present",
    "interface_communicates",
    "metric_range",
    "state_equals",
    "event_occurs",
]


class StrictExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentIdentity(StrictExperimentModel):
    id: StableId = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)


class ComponentDefinition(StrictExperimentModel):
    id: StableId = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class HardwareDefinition(StrictExperimentModel):
    family: str = Field(min_length=1, max_length=100)
    board_model: str = Field(min_length=1, max_length=200)
    components: list[ComponentDefinition] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def reject_duplicate_components(
        cls, components: list[ComponentDefinition]
    ) -> list[ComponentDefinition]:
        ids = [item.id for item in components]
        if len(ids) != len(set(ids)):
            raise ValueError("component ids must be unique")
        return components


class InterfaceDefinition(StrictExperimentModel):
    id: StableId = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    type: InterfaceType
    component_ids: list[StableId] = Field(default_factory=list)
    pins: dict[str, int | str] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExpectedBehavior(StrictExperimentModel):
    id: StableId = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    kind: BehaviorKind
    component_id: StableId | None = None
    interface_id: StableId | None = None
    metric: str | None = Field(default=None, max_length=100)
    expected: str | int | float | bool | None = None
    minimum: float | None = None
    maximum: float | None = None
    event_type: str | None = Field(default=None, max_length=100)
    within_seconds: int | None = Field(default=None, ge=1, le=604800)

    @model_validator(mode="after")
    def validate_kind_parameters(self) -> ExpectedBehavior:
        if self.kind == "component_present" and self.component_id is None:
            raise ValueError("component_present requires component_id")
        if self.kind == "interface_communicates" and self.interface_id is None:
            raise ValueError("interface_communicates requires interface_id")
        if self.kind == "metric_range":
            if self.metric is None:
                raise ValueError("metric_range requires metric")
            if self.minimum is None and self.maximum is None:
                raise ValueError("metric_range requires minimum or maximum")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("minimum cannot exceed maximum")
        if self.kind == "state_equals" and (self.metric is None or self.expected is None):
            raise ValueError("state_equals requires metric and expected")
        if self.kind == "event_occurs" and self.event_type is None:
            raise ValueError("event_occurs requires event_type")
        return self


class NormalizationMapping(StrictExperimentModel):
    id: StableId = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    match: dict[str, Any] = Field(default_factory=dict)
    output: Literal["observation", "event"]
    component_id: StableId | None = None
    interface_id: StableId | None = None
    metric: str | None = Field(default=None, max_length=100)
    metric_field: str | None = Field(default=None, max_length=100)
    value_field: str | None = Field(default=None, max_length=100)
    status_field: str | None = Field(default=None, max_length=100)
    default_status: Literal["normal", "warning", "error", "unknown"] = "unknown"
    event_type: str | None = Field(default=None, max_length=100)
    event_type_field: str | None = Field(default=None, max_length=100)
    timestamp_field: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_output_fields(self) -> NormalizationMapping:
        if self.output == "observation":
            if self.metric is None and self.metric_field is None:
                raise ValueError("observation mapping requires metric or metric_field")
            if self.value_field is None:
                raise ValueError("observation mapping requires value_field")
        if self.output == "event" and self.event_type is None and self.event_type_field is None:
            raise ValueError("event mapping requires event_type or event_type_field")
        return self


class NormalizationDefinition(StrictExperimentModel):
    adapter: str = Field(default="mapping", min_length=1, max_length=100)
    mappings: list[NormalizationMapping] = Field(default_factory=list)

    @field_validator("mappings")
    @classmethod
    def reject_duplicate_mappings(
        cls, mappings: list[NormalizationMapping]
    ) -> list[NormalizationMapping]:
        ids = [item.id for item in mappings]
        if len(ids) != len(set(ids)):
            raise ValueError("normalization mapping ids must be unique")
        return mappings


class DiagnosticArtifactSelection(StrictExperimentModel):
    rule_sources: list[str] = Field(default_factory=list)
    fault_tree_sources: list[str] = Field(default_factory=list)


class KnowledgeScope(StrictExperimentModel):
    hardware_families: list[str] = Field(default_factory=list)
    board_models: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    interfaces: list[InterfaceType] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    knowledge_version: str | None = Field(default=None, max_length=50)


class ExperimentDefinition(StrictExperimentModel):
    schema_version: Literal["1"] = "1"
    experiment: ExperimentIdentity
    hardware: HardwareDefinition
    interfaces: list[InterfaceDefinition] = Field(default_factory=list)
    required_parameters: dict[str, Any] = Field(default_factory=dict)
    expected_behaviors: list[ExpectedBehavior] = Field(default_factory=list)
    diagnostics: DiagnosticArtifactSelection = Field(default_factory=DiagnosticArtifactSelection)
    normalization: NormalizationDefinition = Field(default_factory=NormalizationDefinition)
    knowledge_scope: KnowledgeScope = Field(default_factory=KnowledgeScope)

    @model_validator(mode="after")
    def validate_references(self) -> ExperimentDefinition:
        component_ids = {item.id for item in self.hardware.components}
        interface_ids = {item.id for item in self.interfaces}
        if len(interface_ids) != len(self.interfaces):
            raise ValueError("interface ids must be unique")
        behavior_ids = [item.id for item in self.expected_behaviors]
        if len(behavior_ids) != len(set(behavior_ids)):
            raise ValueError("expected behavior ids must be unique")
        for interface in self.interfaces:
            missing = set(interface.component_ids) - component_ids
            if missing:
                raise ValueError(
                    f"interface {interface.id} references unknown components: {sorted(missing)}"
                )
        for behavior in self.expected_behaviors:
            if behavior.component_id and behavior.component_id not in component_ids:
                raise ValueError(
                    f"behavior {behavior.id} references unknown component {behavior.component_id}"
                )
            if behavior.interface_id and behavior.interface_id not in interface_ids:
                raise ValueError(
                    f"behavior {behavior.id} references unknown interface {behavior.interface_id}"
                )
        for mapping in self.normalization.mappings:
            if mapping.component_id and mapping.component_id not in component_ids:
                raise ValueError(
                    f"mapping {mapping.id} references unknown component {mapping.component_id}"
                )
            if mapping.interface_id and mapping.interface_id not in interface_ids:
                raise ValueError(
                    f"mapping {mapping.id} references unknown interface {mapping.interface_id}"
                )
        return self
