from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.loader import load_rules
from app.diagnosis.matcher import evaluate_rules
from app.diagnosis.schemas import (
    ContextHeartbeat,
    ContextLog,
    ContextReading,
    DiagnosisContext,
    DiagnosisOutcome,
    ExperimentTemplateContext,
)
from app.models.base import utc_now
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.diagnosis_result import DiagnosisResult
from app.models.sensor_reading import SensorReading


def build_diagnosis_context(
    db: Session,
    device: Device,
    *,
    evaluated_at: Optional[datetime] = None,
    lookback_seconds: int = 3600,
    experiment_template: Optional[ExperimentTemplateContext] = None,
) -> DiagnosisContext:
    reference = evaluated_at or datetime.now(timezone.utc)
    since = reference - timedelta(seconds=lookback_seconds)
    logs = db.scalars(
        select(DeviceLog)
        .where(DeviceLog.device_id == device.id, DeviceLog.occurred_at >= since)
        .order_by(DeviceLog.occurred_at, DeviceLog.id)
    ).all()
    heartbeats = db.scalars(
        select(DeviceHeartbeat)
        .where(DeviceHeartbeat.device_id == device.id, DeviceHeartbeat.observed_at >= since)
        .order_by(DeviceHeartbeat.observed_at, DeviceHeartbeat.id)
    ).all()
    readings = db.scalars(
        select(SensorReading)
        .where(SensorReading.device_id == device.id, SensorReading.observed_at >= since)
        .order_by(SensorReading.observed_at, SensorReading.id)
    ).all()
    return DiagnosisContext(
        device_id=device.device_key,
        evaluated_at=reference,
        last_seen_at=device.last_seen_at,
        logs=[
            ContextLog(
                id=item.id,
                level=item.level,
                message=item.message,
                event_code=item.event_code,
                occurred_at=item.occurred_at,
                is_test_data=item.is_test_data,
            )
            for item in logs
        ],
        heartbeats=[
            ContextHeartbeat(
                id=item.id,
                observed_at=item.observed_at,
                received_at=item.received_at,
                is_test_data=item.is_test_data,
            )
            for item in heartbeats
        ],
        readings=[
            ContextReading(
                id=item.id,
                sensor_type=item.sensor_type,
                metric_key=item.metric_key,
                value=item.value,
                unit=item.unit,
                observed_at=item.observed_at,
                is_test_data=item.is_test_data,
            )
            for item in readings
        ],
        experiment_template=experiment_template,
    )


def diagnose(context: DiagnosisContext) -> DiagnosisOutcome:
    ruleset, ruleset_hash = load_rules()
    return evaluate_rules(context, ruleset, ruleset_hash)


def save_diagnosis_result(
    db: Session,
    device: Device,
    context: DiagnosisContext,
    outcome: DiagnosisOutcome,
    *,
    commit: bool = True,
) -> DiagnosisResult:
    sources = [*context.logs, *context.heartbeats, *context.readings]
    record = DiagnosisResult(
        device_id=device.id,
        evaluated_at=context.evaluated_at,
        ruleset_version=outcome.ruleset_version,
        ruleset_hash=outcome.ruleset_hash,
        input_fingerprint=outcome.input_fingerprint,
        matched_rules=[match.model_dump(mode="json") for match in outcome.matches],
        evidence=[
            {
                "rule_id": match.rule_id,
                "items": [item.model_dump(mode="json") for item in match.evidence],
            }
            for match in outcome.matches
        ],
        context_snapshot=context.model_dump(mode="json"),
        is_test_data=bool(sources) and all(item.is_test_data for item in sources),
        created_at=utc_now(),
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    else:
        # Graph callers link the result to their workflow in the same transaction.
        # This closes the crash window where a result was committed but the replay
        # had no durable reference and therefore created a duplicate result.
        db.flush()
    return record
