"""Shared telemetry checks; never infer a physical fault from missing reports."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.diagnosis.schemas import DiagnosisContext


def _age(now: datetime, then: datetime) -> float:
    return (
        now.replace(tzinfo=now.tzinfo or timezone.utc)
        - then.replace(tzinfo=then.tzinfo or timezone.utc)
    ).total_seconds()


def assess_runtime_health(context: DiagnosisContext) -> dict[str, Any]:
    spec = context.runtime_expectations
    if spec is None:
        return {"status": "unknown", "checks": [], "reason": "runtime expectations not defined"}
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, **details: Any) -> None:
        checks.append({"check": name, "status": status, **details})

    age = _age(context.evaluated_at, context.last_seen_at) if context.last_seen_at else None
    add(
        "device_online",
        "satisfied" if age is not None and 0 <= age < spec.offline_after_seconds else "violated",
        age_seconds=age,
        threshold=spec.offline_after_seconds,
    )
    beats = [(h.received_at, h.id) for h in context.heartbeats]
    if not beats:
        beats = [
            (e.occurred_at, e.source_ref) for e in context.events if e.type == "device_heartbeat"
        ]
    beat = max(beats, key=lambda item: item[0].timestamp()) if beats else None
    age = _age(context.evaluated_at, beat[0]) if beat else None
    limit = spec.heartbeat_maximum_age_seconds
    add(
        "heartbeat_fresh",
        "unknown"
        if limit is None
        else "satisfied"
        if age is not None and 0 <= age <= limit
        else "violated",
        age_seconds=age,
        threshold=limit,
        source_ref=beat[1] if beat else None,
    )
    if not spec.required_observations:
        add("required_data", "unknown", reason="required observations not defined")
    for required in spec.required_observations:
        items = sorted(
            (
                o
                for o in context.observations
                if o.component_id == required.component_id and o.metric == required.metric
            ),
            key=lambda o: (o.observed_at.timestamp(), o.id),
        )
        latest = items[-1] if items else None
        identity = {
            "component_id": required.component_id,
            "metric": required.metric,
            "source_refs": [o.source_ref for o in items],
        }
        age = _age(context.evaluated_at, latest.observed_at) if latest else None
        limit = required.maximum_age_seconds
        add(
            "data_fresh",
            "unknown"
            if limit is None
            else "satisfied"
            if age is not None and 0 <= age <= limit
            else "violated",
            **identity,
            age_seconds=age,
            threshold=limit,
        )
        valid = bool(items) and all(
            isinstance(o.value, (int, float))
            and not isinstance(o.value, bool)
            and math.isfinite(o.value)
            and o.status == "normal"
            and (required.allowed_values is None or o.value in required.allowed_values)
            and (required.unit is None or o.unit == required.unit)
            for o in items
        )
        add(
            "required_fields_valid",
            "satisfied" if valid else "unknown" if not items else "violated",
            **identity,
        )
        times = sorted({o.observed_at.timestamp() for o in items})
        gaps = [b - a for a, b in zip(times, times[1:])]
        add(
            "data_periodic",
            "unknown"
            if limit is None or not gaps
            else "satisfied"
            if max(gaps) <= limit
            else "violated",
            **identity,
            maximum_gap_seconds=max(gaps) if gaps else None,
            threshold=limit,
        )
    statuses = {c["status"] for c in checks}
    return {
        "status": "abnormal"
        if "violated" in statuses
        else "unknown"
        if "unknown" in statuses
        else "normal",
        "verification_status": spec.verification_status,
        "checks": checks,
        "scope": "reported_telemetry_only",
    }
