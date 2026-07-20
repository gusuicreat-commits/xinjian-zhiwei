import hashlib
import json
from dataclasses import dataclass
from datetime import timezone
from operator import eq, ge, gt, le, lt
from typing import Any, Callable, Optional

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


FACTS: dict[str, Callable[[DiagnosisContext, dict[str, Any]], FactResult]] = {
    "log_event_count": _log_event_count,
    "seconds_since_last_seen": _seconds_since_last_seen,
    "out_of_range_count": _out_of_range_count,
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
                )
            )
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
