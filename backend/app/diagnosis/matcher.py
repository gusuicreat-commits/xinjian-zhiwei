import hashlib
import json
from dataclasses import dataclass
from datetime import timezone
from operator import eq, ge, gt, le, lt
from typing import Any, Callable, Optional

from app.diagnosis.expected_behavior import compare_expected_behaviors
from app.diagnosis.runtime_health import assess_runtime_health
from app.diagnosis.schemas import (
    DiagnosisContext,
    DiagnosisMatch,
    DiagnosisOutcome,
    EvidenceItem,
    RuleCondition,
    RuleSet,
)


@dataclass(frozen=True)
class FactResult:
    value: float
    details: list[dict[str, Any]]


def _log_event_count(context: DiagnosisContext, params: dict[str, Any]) -> FactResult:
    event_code = params.get("event_code")
    matching = [item for item in context.logs if item.event_code == event_code]
    details = [
        {
            "log_id": item.id,
            "event_code": item.event_code,
            "level": item.level,
            "message": item.message,
            "occurred_at": item.occurred_at.isoformat(),
        }
        for item in matching
    ]
    return FactResult(float(len(matching)), details)


def _seconds_since_last_seen(context: DiagnosisContext, _: dict[str, Any]) -> FactResult:
    if context.last_seen_at is None:
        return FactResult(315_576_000_000.0, [{"last_seen_at": None, "status": "never_seen"}])
    evaluated = context.evaluated_at.astimezone(timezone.utc)
    seen = context.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    seconds = max(0.0, (evaluated - seen.astimezone(timezone.utc)).total_seconds())
    return FactResult(
        seconds,
        [{"last_seen_at": seen.isoformat(), "evaluated_at": evaluated.isoformat()}],
    )


def _out_of_range_count(context: DiagnosisContext, params: dict[str, Any]) -> FactResult:
    template = context.experiment_template
    if template is None:
        return FactResult(0.0, [])
    metric_key = params.get("metric_key")
    details: list[dict[str, Any]] = []
    for reading in context.readings:
        if metric_key is not None and reading.metric_key != metric_key:
            continue
        bounds = template.metric_ranges.get(reading.metric_key)
        if bounds is None:
            continue
        below = bounds.minimum is not None and reading.value < bounds.minimum
        above = bounds.maximum is not None and reading.value > bounds.maximum
        if below or above:
            details.append(
                {
                    "reading_id": reading.id,
                    "metric_key": reading.metric_key,
                    "value": reading.value,
                    "unit": reading.unit,
                    "minimum": bounds.minimum,
                    "maximum": bounds.maximum,
                    "observed_at": reading.observed_at.isoformat(),
                }
            )
    return FactResult(float(len(details)), details)


def _event_type_count(context: DiagnosisContext, params: dict[str, Any]) -> FactResult:
    event_type = params.get("event_type")
    component_id = params.get("component_id")
    interface_id = params.get("interface_id")
    interface_type = params.get("interface_type")
    allowed_interfaces = (
        {item.id for item in context.interfaces if item.type == interface_type}
        if interface_type
        else set()
    )
    matching = [
        item
        for item in context.events
        if (event_type is None or item.type == event_type)
        and (component_id is None or item.component_id == component_id)
        and (interface_id is None or item.interface_id == interface_id)
        and (not interface_type or item.interface_id in allowed_interfaces)
    ]
    return FactResult(
        float(len(matching)),
        [
            {
                "event_id": item.id,
                "event_type": item.type,
                "component_id": item.component_id,
                "interface_id": item.interface_id,
                "source": item.source,
                "source_ref": item.source_ref,
                "occurred_at": item.occurred_at.isoformat(),
            }
            for item in matching
        ],
    )


def _expected_behavior_violation_count(
    context: DiagnosisContext, params: dict[str, Any]
) -> FactResult:
    behavior_id = params.get("behavior_id")
    matching = [
        item
        for item in compare_expected_behaviors(context)
        if item.status == "violated" and (behavior_id is None or item.behavior_id == behavior_id)
    ]
    return FactResult(
        float(len(matching)),
        [item.model_dump(mode="json") for item in matching],
    )


def _failure_count_in_window(context: DiagnosisContext, params: dict[str, Any]) -> FactResult:
    result = _event_type_count(context, params)
    return FactResult(result.value, [*result.details, {
        "failure_count_in_window": result.value,
        "consecutive_failure_count": None,
        "verification_status": "pending_hardware",
        "note": "No verified per-attempt success/failure sequence; consecutive count is unknown.",
    }])


def _runtime_health_failure(context: DiagnosisContext, params: dict[str, Any]) -> FactResult:
    names = {"data_fresh", "data_periodic"} if params.get("check") == "data_delivery" else {
        params.get("check")
    }
    details = [item for item in assess_runtime_health(context)["checks"]
               if item["check"] in names and item["status"] == "violated"]
    return FactResult(float(len(details)), details)


FACTS: dict[str, Callable[[DiagnosisContext, dict[str, Any]], FactResult]] = {
    "log_event_count": _log_event_count,
    "seconds_since_last_seen": _seconds_since_last_seen,
    "out_of_range_count": _out_of_range_count,
    "event_type_count": _event_type_count,
    "failure_count_in_window": _failure_count_in_window,
    "runtime_health_failure": _runtime_health_failure,
    "expected_behavior_violation_count": _expected_behavior_violation_count,
}
OPERATORS = {"eq": eq, "gte": ge, "gt": gt, "lte": le, "lt": lt}


def _evaluate_condition(
    context: DiagnosisContext, condition: RuleCondition
) -> Optional[EvidenceItem]:
    result = FACTS[condition.fact](context, condition.params)
    if not OPERATORS[condition.operator](result.value, condition.value):
        return None
    return EvidenceItem(
        fact=condition.fact,
        observed_value=result.value,
        details=result.details,
    )


def evaluate_rules(
    context: DiagnosisContext, ruleset: RuleSet, ruleset_hash: str
) -> DiagnosisOutcome:
    matches = []
    for rule in sorted(ruleset.rules, key=lambda item: (-item.priority, item.id)):
        if not rule.enabled:
            continue
        evidence = [_evaluate_condition(context, condition) for condition in rule.conditions]
        if all(item is not None for item in evidence):
            matches.append(
                DiagnosisMatch(
                    rule_id=rule.id,
                    error_type=rule.error_type,
                    priority=rule.priority,
                    summary=rule.summary,
                    evidence=[item for item in evidence if item is not None],
                    source_id=rule.source_id,
                    source_version=rule.source_version,
                    scope=rule.scope,
                )
            )
    context.normal_assessment = assess_runtime_health(context)
    context.normal_assessment["checks"].append({
        "check": "no_anomaly_rules", "status": "violated" if matches else "satisfied",
    })
    if context.runtime_expectations is not None:
        context.normal_assessment["checks"].extend(
            {"check": "expected_behavior", "behavior_id": c.behavior_id, "status": c.status}
            for c in compare_expected_behaviors(context)
        )
        statuses = {c["status"] for c in context.normal_assessment["checks"]}
        context.normal_assessment["status"] = (
            "abnormal" if "violated" in statuses else
            "unknown" if "unknown" in statuses else "normal"
        )
    elif matches:
        context.normal_assessment["status"] = "abnormal"
    canonical_context = json.dumps(
        context.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    fingerprint = hashlib.sha256(f"{ruleset_hash}:{canonical_context}".encode()).hexdigest()
    return DiagnosisOutcome(
        ruleset_version=ruleset.version,
        ruleset_hash=ruleset_hash,
        input_fingerprint=fingerprint,
        matches=matches,
    )
