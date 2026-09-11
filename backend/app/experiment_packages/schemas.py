from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.diagnosis.fault_tree_schemas import FaultTreeDefinition
from app.diagnosis.schemas import DiagnosisRule, ExpectedBehavior, StrictModel
from app.experiments.schemas import (
    HardwareDefinition,
    InterfaceDefinition,
    NormalizationDefinition,
    RuntimeExpectations,
)
from app.schemas.knowledge_case import KnowledgeCaseDefinition


class PackageExperimentIdentity(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    locale: str = Field(default="zh-CN", min_length=2, max_length=20)


class PackageRelease(StrictModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=50)
    status: Literal["draft"] = "draft"


class PackageCompatibility(StrictModel):
    engine: str = Field(default=">=2.0,<3.0", min_length=1, max_length=100)
    platforms: list[str] = Field(default_factory=list, min_length=1, max_length=20)


class PackageMaintainer(StrictModel):
    organization: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=200)


class PackageMetadata(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment: PackageExperimentIdentity
    package: PackageRelease
    compatibility: PackageCompatibility
    maintainer: PackageMaintainer


class HardwareConnection(StrictModel):
    component: str = Field(min_length=1, max_length=100)
    signal: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)


class EvidenceSource(StrictModel):
    type: Literal[
        "device_error_code",
        "device_status",
        "device_log",
        "sensor_reading",
        "student_feedback",
    ]
    value: str | int | float | bool


class EvidenceMapping(StrictModel):
    source: EvidenceSource
    evidence_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)


class PackageHardware(StrictModel):
    hardware: HardwareDefinition
    interfaces: list[InterfaceDefinition] = Field(default_factory=list)
    connections: list[HardwareConnection] = Field(default_factory=list)
    evidence_mapping: list[EvidenceMapping] = Field(default_factory=list)
    normalization: NormalizationDefinition = Field(default_factory=NormalizationDefinition)
    required_parameters: dict[str, Any] = Field(default_factory=dict)
    runtime_expectations: RuntimeExpectations | None = None

    @model_validator(mode="after")
    def validate_hardware_references(self) -> PackageHardware:
        component_ids = {item.id for item in self.hardware.components}
        interface_ids = {item.id for item in self.interfaces}
        pin_targets = {
            f"GPIO{value}" if isinstance(value, int) else str(value)
            for interface in self.interfaces
            for value in interface.pins.values()
        }
        for interface in self.interfaces:
            missing = set(interface.component_ids) - component_ids
            if missing:
                raise ValueError(
                    f"interface {interface.id} references unknown components: {sorted(missing)}"
                )
        for connection in self.connections:
            if connection.component not in component_ids:
                raise ValueError(f"connection references unknown component: {connection.component}")
            if connection.target.startswith("GPIO") and connection.target not in pin_targets:
                raise ValueError(
                    f"connection target is not declared by an interface: {connection.target}"
                )
        mapping_ids = [item.evidence_type for item in self.evidence_mapping]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise ValueError("evidence_type values must be unique")
        if len(interface_ids) != len(self.interfaces):
            raise ValueError("interface ids must be unique")
        return self


class PackageRules(StrictModel):
    version: str = Field(min_length=1, max_length=50)
    rules: list[DiagnosisRule] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def unique_rules(cls, rules: list[DiagnosisRule]) -> list[DiagnosisRule]:
        ids = [item.id for item in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return rules


class PackageFaultTrees(StrictModel):
    version: str = Field(min_length=1, max_length=50)
    trees: list[FaultTreeDefinition] = Field(min_length=1)


class PackageConcept(StrictModel):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    references: list[str] = Field(default_factory=list, max_length=20)


class PackageConcepts(StrictModel):
    concepts: list[PackageConcept] = Field(default_factory=list)


class PackageCases(StrictModel):
    cases: list[KnowledgeCaseDefinition] = Field(default_factory=list)


class ExperimentStep(StrictModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    expected_state: str = Field(min_length=1, max_length=1000)


class PackageSteps(StrictModel):
    steps: list[ExperimentStep] = Field(min_length=1)
    expected_behaviors: list[ExpectedBehavior] = Field(default_factory=list)


class PackageHint(StrictModel):
    cause_id: str = Field(min_length=1, max_length=100)
    levels: dict[int, str]

    @field_validator("levels")
    @classmethod
    def require_hint_levels(cls, levels: dict[int, str]) -> dict[int, str]:
        if set(levels) != {1, 2, 3, 4}:
            raise ValueError("package hints must define levels 1 through 4")
        return levels


class PackageHints(StrictModel):
    hints: list[PackageHint] = Field(min_length=1)


class PackageTestExpectation(StrictModel):
    error_type: str | None = Field(default=None, max_length=100)
    candidate_causes: list[str] = Field(default_factory=list, max_length=20)


class PackageTestCase(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    facts: dict[str, int | float] = Field(default_factory=dict)
    expected: PackageTestExpectation


class PackageTests(StrictModel):
    cases: list[PackageTestCase] = Field(min_length=1)


class ManifestEntry(StrictModel):
    path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PackageManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    files: list[ManifestEntry]
    package_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExperimentPackageBundle(StrictModel):
    metadata: PackageMetadata
    hardware: PackageHardware
    rules: PackageRules
    fault_trees: PackageFaultTrees
    concepts: PackageConcepts
    cases: PackageCases
    steps: PackageSteps
    hints: PackageHints
    normal_tests: PackageTests
    fault_tests: PackageTests
    manifest: PackageManifest


class PackageCheck(StrictModel):
    code: str
    passed: bool
    message: str


class PackageValidationReport(StrictModel):
    valid: bool
    experiment_code: str
    package_version: str
    package_hash: str
    checks: list[PackageCheck]
