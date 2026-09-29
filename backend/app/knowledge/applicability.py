"""Pure, bounded eligibility checks against already frozen diagnosis inputs.

Free text is preserved as a limitation; it is never parsed into executable rules.
This module does not access current device bindings, databases or providers.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.schemas.knowledge_case import (
    CaseApplicabilityCheck,
    CaseApplicabilityConditions,
    CaseApplicabilityProjection,
)


@dataclass(frozen=True)
class CaseApplicabilityContext:
    experiment_code: str | None = None
    package_version: str | None = None
    component_id: str | None = None


@dataclass(frozen=True)
class ApplicabilityEvaluation:
    projection: CaseApplicabilityProjection | None
    reason: str
    checks: tuple[CaseApplicabilityCheck, ...] = ()


def _identifier(value: Any) -> str | None:
    return value if (
        isinstance(value, str) and value.strip() == value and 0 < len(value) <= 100
    ) else None


def context_from_diagnosis(diagnosis, guidance) -> CaseApplicabilityContext:
    """Use immutable diagnosis metadata and an unambiguous recorded component scope."""
    snapshot = diagnosis.context_snapshot or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    recorded_code = _identifier(snapshot.get("experiment_id"))
    diagnosis_code = _identifier(getattr(diagnosis, "experiment_id", None))
    experiment_code = recorded_code or diagnosis_code
    if recorded_code and diagnosis_code and recorded_code != diagnosis_code:
        experiment_code = None

    frozen_id = _identifier(snapshot.get("experiment_version_id"))
    diagnosis_version_id = _identifier(getattr(diagnosis, "experiment_version_id", None))
    package_version = None
    if (frozen_id and frozen_id == diagnosis_version_id
            and _identifier(snapshot.get("experiment_package_hash"))):
        package_version = _identifier(snapshot.get("experiment_version"))

    components = set()
    valid_scope = bool(guidance)
    for item in guidance:
        scope = getattr(item, "fault_tree_scope", None) or {}
        if not isinstance(scope, dict):
            valid_scope = False
            break
        keys = scope.get("keys")
        if (scope.get("kind") != "component" or not isinstance(keys, list)
                or len(keys) != 1 or _identifier(keys[0]) is None):
            valid_scope = False
            break
        components.add(keys[0])
    component_id = next(iter(components)) if valid_scope and len(components) == 1 else None
    return CaseApplicabilityContext(experiment_code, package_version, component_id)


def evaluate_case_applicability(
    solution_record: Any,
    context: CaseApplicabilityContext,
) -> ApplicabilityEvaluation:
    """Extract only the canonical limits and return a fixed, non-sensitive reason."""
    if solution_record is None:
        return ApplicabilityEvaluation(None, "applicability_missing")
    if not isinstance(solution_record, dict):
        return ApplicabilityEvaluation(None, "applicability_invalid")
    material = solution_record.get("confirmation_material")
    if material is None:
        return ApplicabilityEvaluation(None, "applicability_missing")
    if not isinstance(material, dict):
        return ApplicabilityEvaluation(None, "applicability_invalid")
    limits = material.get("applicability_limits")
    if limits is None or (isinstance(limits, str) and not limits.strip()):
        return ApplicabilityEvaluation(None, "applicability_missing")
    if not isinstance(limits, str) or len(limits) > 2000:
        return ApplicabilityEvaluation(None, "applicability_invalid")

    raw_conditions = material.get("applicability_conditions")
    if raw_conditions is None:
        return ApplicabilityEvaluation(
            CaseApplicabilityProjection(limits_text=limits, condition_status="text_only"),
            "eligible",
        )
    try:
        conditions = CaseApplicabilityConditions.model_validate(raw_conditions)
    except ValidationError:
        return ApplicabilityEvaluation(None, "applicability_invalid")
    checks = []
    for condition in conditions.conditions:
        actual = getattr(context, condition.field)
        status = "unknown" if actual is None else (
            "matched" if actual in condition.values else "mismatch"
        )
        checks.append(CaseApplicabilityCheck(
            **condition.model_dump(), actual=actual, status=status,
        ))
    if any(check.status == "mismatch" for check in checks):
        return ApplicabilityEvaluation(None, "applicability_mismatch", tuple(checks))
    if any(check.status == "unknown" for check in checks):
        return ApplicabilityEvaluation(None, "applicability_unknown", tuple(checks))
    return ApplicabilityEvaluation(
        CaseApplicabilityProjection(limits_text=limits, condition_status="matched", checks=checks),
        "eligible", tuple(checks),
    )
