from __future__ import annotations

from datetime import timezone
from typing import Any

from app.diagnosis.schemas import BehaviorComparison, DiagnosisContext
from app.experiments.schemas import ExpectedBehavior


def _refs(items: list[Any]) -> list[str]:
    return [f"{item.source}:{item.source_ref}" for item in items]


def compare_expected_behavior(
    context: DiagnosisContext, behavior: ExpectedBehavior
) -> BehaviorComparison:
    status = "unknown"
    observed: Any = None
    references: list[str] = []
    if behavior.kind == "device_online":
        if context.last_seen_at is None:
            status, observed = "violated", None
        else:
            evaluated = context.evaluated_at.astimezone(timezone.utc)
            seen = context.last_seen_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            elapsed = max(0.0, (evaluated - seen.astimezone(timezone.utc)).total_seconds())
            threshold = behavior.within_seconds or 90
            status, observed = ("satisfied" if elapsed <= threshold else "violated"), elapsed
    elif behavior.kind == "component_present":
        items = [
            item
            for item in [*context.observations, *context.events]
            if item.component_id == behavior.component_id
        ]
        status, observed, references = (
            ("satisfied", True, _refs(items)) if items else ("violated", False, [])
        )
    elif behavior.kind == "interface_communicates":
        items = [item for item in context.events if item.interface_id == behavior.interface_id]
        failures = [item for item in items if item.type == "communication_failure"]
        successes = [item for item in items if item.type == "communication_success"]
        if failures:
            status, observed, references = "violated", "communication_failure", _refs(failures)
        elif successes:
            status, observed, references = "satisfied", "communication_success", _refs(successes)
    elif behavior.kind in {"metric_range", "state_equals"}:
        items = [
            item
            for item in context.observations
            if item.metric == behavior.metric
            and (behavior.component_id is None or item.component_id == behavior.component_id)
            and (behavior.interface_id is None or item.interface_id == behavior.interface_id)
        ]
        references = _refs(items)
        if items:
            observed = items[-1].value
            if behavior.kind == "state_equals":
                status = "satisfied" if observed == behavior.expected else "violated"
            else:
                numeric = [item.value for item in items if isinstance(item.value, (int, float))]
                if not numeric:
                    status = "unknown"
                else:
                    violated = any(
                        (behavior.minimum is not None and value < behavior.minimum)
                        or (behavior.maximum is not None and value > behavior.maximum)
                        for value in numeric
                    )
                    status = "violated" if violated else "satisfied"
    elif behavior.kind == "event_occurs":
        items = [
            item
            for item in context.events
            if item.type == behavior.event_type
            and (behavior.component_id is None or item.component_id == behavior.component_id)
            and (behavior.interface_id is None or item.interface_id == behavior.interface_id)
        ]
        status, observed, references = (
            ("satisfied", True, _refs(items)) if items else ("violated", False, [])
        )
    return BehaviorComparison(
        behavior_id=behavior.id,
        kind=behavior.kind,
        status=status,
        expected=behavior.model_dump(mode="json", exclude_none=True),
        observed=observed,
        evidence_refs=references,
    )


def compare_expected_behaviors(context: DiagnosisContext) -> list[BehaviorComparison]:
    return [compare_expected_behavior(context, item) for item in context.expected_behaviors]
