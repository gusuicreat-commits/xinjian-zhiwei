from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.diagnosis.schemas import ArtifactScope
from app.experiment_packages.schemas import (
    ExperimentPackageBundle,
    ManifestEntry,
    PackageCases,
    PackageCheck,
    PackageConcepts,
    PackageFaultTrees,
    PackageHardware,
    PackageHints,
    PackageManifest,
    PackageMetadata,
    PackageRules,
    PackageSteps,
    PackageTests,
    PackageValidationReport,
)
from app.experiments.schemas import (
    DiagnosticArtifactSelection,
    ExperimentDefinition,
    ExperimentIdentity,
    KnowledgeScope,
)

DEFAULT_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "experiment_packages"
PACKAGE_FILES: dict[str, type] = {
    "metadata.yaml": PackageMetadata,
    "hardware.yaml": PackageHardware,
    "diagnosis/rules.yaml": PackageRules,
    "diagnosis/fault_tree.yaml": PackageFaultTrees,
    "knowledge/concepts.yaml": PackageConcepts,
    "knowledge/cases.yaml": PackageCases,
    "teaching/steps.yaml": PackageSteps,
    "teaching/hints.yaml": PackageHints,
    "tests/normal_cases.yaml": PackageTests,
    "tests/fault_cases.yaml": PackageTests,
}


class ExperimentPackageLoadError(ValueError):
    """A package is missing, unsafe, internally inconsistent, or fails tests."""


def _canonical(value: Any) -> bytes:
    def json_default(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"unsupported package value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")


def _read_documents(directory: Path) -> tuple[dict[str, Any], PackageManifest]:
    documents: dict[str, Any] = {}
    entries: list[ManifestEntry] = []
    for relative in PACKAGE_FILES:
        path = directory / relative
        if not path.is_file():
            raise ExperimentPackageLoadError(f"missing package file: {relative}")
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ExperimentPackageLoadError(f"cannot read package file {relative}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ExperimentPackageLoadError(f"package file root must be an object: {relative}")
        documents[relative] = payload
        entries.append(
            ManifestEntry(
                path=relative,
                sha256=hashlib.sha256(_canonical(payload)).hexdigest(),
            )
        )
    package_hash = hashlib.sha256(
        _canonical({item.path: item.sha256 for item in entries})
    ).hexdigest()
    return documents, PackageManifest(files=entries, package_hash=package_hash)


def _manifest_for_documents(documents: dict[str, Any]) -> PackageManifest:
    missing = sorted(set(PACKAGE_FILES) - set(documents))
    extra = sorted(set(documents) - set(PACKAGE_FILES))
    if missing or extra:
        raise ExperimentPackageLoadError(
            f"package file set mismatch: missing={missing}, extra={extra}"
        )
    entries = [
        ManifestEntry(
            path=relative,
            sha256=hashlib.sha256(_canonical(documents[relative])).hexdigest(),
        )
        for relative in PACKAGE_FILES
    ]
    package_hash = hashlib.sha256(
        _canonical({item.path: item.sha256 for item in entries})
    ).hexdigest()
    return PackageManifest(files=entries, package_hash=package_hash)


def _parse_bundle(documents: dict[str, Any], manifest: PackageManifest) -> ExperimentPackageBundle:
    try:
        parsed = {
            relative: model.model_validate(documents[relative])
            for relative, model in PACKAGE_FILES.items()
        }
        return ExperimentPackageBundle(
            metadata=parsed["metadata.yaml"],
            hardware=parsed["hardware.yaml"],
            rules=parsed["diagnosis/rules.yaml"],
            fault_trees=parsed["diagnosis/fault_tree.yaml"],
            concepts=parsed["knowledge/concepts.yaml"],
            cases=parsed["knowledge/cases.yaml"],
            steps=parsed["teaching/steps.yaml"],
            hints=parsed["teaching/hints.yaml"],
            normal_tests=parsed["tests/normal_cases.yaml"],
            fault_tests=parsed["tests/fault_cases.yaml"],
            manifest=manifest,
        )
    except ValidationError as exc:
        raise ExperimentPackageLoadError(f"package schema validation failed: {exc}") from exc


def package_to_experiment_definition(bundle: ExperimentPackageBundle) -> ExperimentDefinition:
    metadata = bundle.metadata
    return ExperimentDefinition(
        schema_version="1",
        experiment=ExperimentIdentity(
            id=metadata.experiment.code,
            name=metadata.experiment.name,
            version=metadata.package.version,
        ),
        hardware=bundle.hardware.hardware,
        interfaces=bundle.hardware.interfaces,
        required_parameters=bundle.hardware.required_parameters,
        expected_behaviors=bundle.steps.expected_behaviors,
        diagnostics=DiagnosticArtifactSelection(),
        normalization=bundle.hardware.normalization,
        knowledge_scope=KnowledgeScope(
            hardware_families=[bundle.hardware.hardware.family],
            board_models=[bundle.hardware.hardware.board_model],
            components=[
                value
                for item in bundle.hardware.hardware.components
                for value in (item.id, item.kind, item.model)
                if value
            ],
            interfaces=[item.type for item in bundle.hardware.interfaces],
            document_types=["experiment_package", "teacher_confirmed_case"],
            knowledge_version=metadata.package.version,
        ),
    )


def _criterion_key(fact: str, params: dict[str, Any]) -> str:
    if len(params) == 1:
        return f"{fact}:{next(iter(params.values()))}"
    return fact


def _condition_matches(observed: int | float, operator: str, expected: int | float) -> bool:
    return {
        "eq": observed == expected,
        "gte": observed >= expected,
        "gt": observed > expected,
        "lte": observed <= expected,
        "lt": observed < expected,
    }[operator]


def _run_package_tests(bundle: ExperimentPackageBundle) -> list[PackageCheck]:
    checks: list[PackageCheck] = []
    trees_by_error = {
        str(criterion.params.get("error_type")): tree
        for tree in bundle.fault_trees.trees
        for criterion in tree.trigger
        if criterion.fact == "diagnosis_error_count" and criterion.params.get("error_type")
    }
    for group_name, tests in (
        ("normal", bundle.normal_tests),
        ("fault", bundle.fault_tests),
    ):
        for case in tests.cases:
            matched_errors = [
                rule.error_type
                for rule in bundle.rules.rules
                if rule.enabled
                and all(
                    _criterion_key(condition.fact, condition.params) in case.facts
                    and _condition_matches(
                        case.facts[_criterion_key(condition.fact, condition.params)],
                        condition.operator,
                        condition.value,
                    )
                    for condition in rule.conditions
                )
            ]
            error_ok = (
                not matched_errors
                if case.expected.error_type is None
                else case.expected.error_type in matched_errors
            )
            tree = trees_by_error.get(str(case.expected.error_type))
            known_causes = {item.id for item in tree.causes} if tree else set()
            causes_ok = set(case.expected.candidate_causes).issubset(known_causes)
            checks.append(
                PackageCheck(
                    code=f"test.{group_name}.{case.name}",
                    passed=error_ok and causes_ok,
                    message=(
                        "package test passed"
                        if error_ok and causes_ok
                        else f"matched_errors={matched_errors}, known_causes={sorted(known_causes)}"
                    ),
                )
            )
    return checks


def validate_experiment_package(bundle: ExperimentPackageBundle) -> PackageValidationReport:
    code = bundle.metadata.experiment.code
    rule_ids = [item.id for item in bundle.rules.rules]
    error_types = {item.error_type for item in bundle.rules.rules}
    cause_ids = {cause.id for tree in bundle.fault_trees.trees for cause in tree.causes}
    evidence_types = {item.evidence_type for item in bundle.hardware.evidence_mapping}
    checks = [
        PackageCheck(
            code="schema.valid",
            passed=True,
            message="all package files satisfy the strict Pydantic/JSON Schema contract",
        ),
        PackageCheck(
            code="rules.unique",
            passed=len(rule_ids) == len(set(rule_ids)),
            message="rule ids are unique",
        ),
        PackageCheck(
            code="fault_tree.errors",
            passed=all(
                criterion.fact != "diagnosis_error_count"
                or not criterion.params.get("error_type")
                or criterion.params["error_type"] in error_types
                for tree in bundle.fault_trees.trees
                for criterion in tree.trigger
            ),
            message="fault trees only reference error types emitted by package rules",
        ),
        PackageCheck(
            code="hints.causes",
            passed=all(item.cause_id in cause_ids for item in bundle.hints.hints),
            message="all teaching hints reference package fault-tree causes",
        ),
        PackageCheck(
            code="cases.experiment",
            passed=all(item.experiment_type == code for item in bundle.cases.cases),
            message="all cases belong to the package experiment",
        ),
        PackageCheck(
            code="cases.evidence",
            passed=all(
                not evidence.get("evidenceType") or evidence.get("evidenceType") in evidence_types
                for case in bundle.cases.cases
                for evidence in case.evidence
            ),
            message="all case evidence types are declared by hardware evidence mappings",
        ),
        PackageCheck(
            code="cases.causes",
            passed=all(
                case.root_cause_value is None or case.root_cause_value in cause_ids
                for case in bundle.cases.cases
            ),
            message="confirmed case roots reference package fault-tree causes",
        ),
    ]
    checks.extend(_run_package_tests(bundle))
    return PackageValidationReport(
        valid=all(item.passed for item in checks),
        experiment_code=code,
        package_version=bundle.metadata.package.version,
        package_hash=bundle.manifest.package_hash,
        checks=checks,
    )


def load_experiment_package_payload(
    documents: dict[str, Any],
) -> tuple[ExperimentPackageBundle, PackageValidationReport]:
    """Validate untrusted package documents and generate the authoritative manifest."""

    manifest = _manifest_for_documents(documents)
    bundle = _parse_bundle(documents, manifest)
    report = validate_experiment_package(bundle)
    if not report.valid:
        failed = ", ".join(item.code for item in report.checks if not item.passed)
        raise ExperimentPackageLoadError(f"package validation failed: {failed}")
    return bundle, report


def package_documents(bundle: ExperimentPackageBundle) -> dict[str, Any]:
    """Return the immutable, filename-keyed document snapshot stored in PostgreSQL."""

    return {
        "metadata.yaml": bundle.metadata.model_dump(mode="json", by_alias=True),
        "hardware.yaml": bundle.hardware.model_dump(mode="json", by_alias=True),
        "diagnosis/rules.yaml": bundle.rules.model_dump(mode="json", by_alias=True),
        "diagnosis/fault_tree.yaml": bundle.fault_trees.model_dump(mode="json", by_alias=True),
        "knowledge/concepts.yaml": bundle.concepts.model_dump(mode="json", by_alias=True),
        "knowledge/cases.yaml": bundle.cases.model_dump(mode="json", by_alias=True),
        "teaching/steps.yaml": bundle.steps.model_dump(mode="json", by_alias=True),
        "teaching/hints.yaml": bundle.hints.model_dump(mode="json", by_alias=True),
        "tests/normal_cases.yaml": bundle.normal_tests.model_dump(mode="json", by_alias=True),
        "tests/fault_cases.yaml": bundle.fault_tests.model_dump(mode="json", by_alias=True),
    }


def load_experiment_package(
    directory: Path,
) -> tuple[ExperimentPackageBundle, PackageValidationReport]:
    documents, manifest = _read_documents(directory)
    bundle = _parse_bundle(documents, manifest)
    report = validate_experiment_package(bundle)
    if not report.valid:
        failed = ", ".join(item.code for item in report.checks if not item.passed)
        raise ExperimentPackageLoadError(f"package validation failed: {failed}")
    return bundle, report


def load_experiment_packages(
    root: Path = DEFAULT_PACKAGE_ROOT,
) -> list[tuple[ExperimentPackageBundle, PackageValidationReport]]:
    if not root.is_dir():
        raise ExperimentPackageLoadError(f"experiment package root not found: {root}")
    packages = [load_experiment_package(path) for path in sorted(root.iterdir()) if path.is_dir()]
    identities = [
        (item[0].metadata.experiment.code, item[0].metadata.package.version) for item in packages
    ]
    if len(identities) != len(set(identities)):
        raise ExperimentPackageLoadError("experiment package identities must be unique")
    return packages


def package_rule_document(bundle: ExperimentPackageBundle) -> dict[str, Any]:
    scope = ArtifactScope(kind="experiment", keys=[bundle.metadata.experiment.code])
    return {
        "version": bundle.rules.version,
        "source_id": f"package.{bundle.metadata.experiment.code}.rules",
        "scope": scope.model_dump(mode="json"),
        "rules": [item.model_dump(mode="json") for item in bundle.rules.rules],
    }


def package_fault_tree_document(bundle: ExperimentPackageBundle) -> dict[str, Any]:
    scope = ArtifactScope(kind="experiment", keys=[bundle.metadata.experiment.code])
    return {
        "version": bundle.fault_trees.version,
        "source_id": f"package.{bundle.metadata.experiment.code}.fault_tree",
        "scope": scope.model_dump(mode="json"),
        "trees": [item.model_dump(mode="json") for item in bundle.fault_trees.trees],
    }
