from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.loader import include_runtime_health_rules, load_rules, load_rules_from_document
from app.diagnosis.matcher import evaluate_rules
from app.diagnosis.normalization import normalize_legacy_context, normalize_raw_device_data
from app.diagnosis.schemas import (
    ContextHeartbeat,
    ContextLog,
    ContextReading,
    DeviceDescriptor,
    DiagnosisContext,
    DiagnosisOutcome,
    ExperimentTemplateContext,
    RawDeviceRecord,
)
from app.experiment_packages.loader import ExperimentPackageLoadError
from app.experiments.loader import experiment_definition_hash, load_experiment_definition
from app.experiments.schemas import ExperimentDefinition
from app.models.base import utc_now
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.diagnosis_evidence import DiagnosisEvidence
from app.models.diagnosis_result import DiagnosisResult
from app.models.sensor_reading import SensorReading
from app.services.experiment_packages import load_experiment_package_runtime


def build_diagnosis_context(
    db: Session,
    device: Device,
    *,
    evaluated_at: Optional[datetime] = None,
    lookback_seconds: int = 3600,
    experiment_template: Optional[ExperimentTemplateContext] = None,
    experiment_id: Optional[str] = None,
    experiment_version: Optional[str] = None,
    experiment_version_id: Optional[str] = None,
) -> DiagnosisContext:
    definition: ExperimentDefinition | None = None
    definition_hash: str | None = None
    package_runtime = None
    if experiment_version_id is not None:
        package_runtime = load_experiment_package_runtime(db, experiment_version_id)
        definition = package_runtime.definition
        definition_hash = experiment_definition_hash(definition)
        if experiment_id is not None and experiment_id != definition.experiment.id:
            raise ExperimentPackageLoadError("experiment id does not match package version")
        if experiment_version is not None and experiment_version != definition.experiment.version:
            raise ExperimentPackageLoadError("experiment version does not match package version")
    elif experiment_id is not None:
        definition, definition_hash = load_experiment_definition(experiment_id, experiment_version)
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
    context_logs = [
        ContextLog(
            id=item.id,
            level=item.level,
            message=item.message,
            event_code=item.event_code,
            occurred_at=item.occurred_at,
            is_test_data=item.is_test_data,
            raw_payload=item.raw_payload,
        )
        for item in logs
    ]
    context_heartbeats = [
        ContextHeartbeat(
            id=item.id,
            observed_at=item.observed_at,
            received_at=item.received_at,
            is_test_data=item.is_test_data,
            raw_payload=item.raw_payload,
        )
        for item in heartbeats
    ]
    context_readings = [
        ContextReading(
            id=item.id,
            sensor_type=item.sensor_type,
            metric_key=item.metric_key,
            value=item.value,
            unit=item.unit,
            observed_at=item.observed_at,
            is_test_data=item.is_test_data,
            raw_payload=item.raw_payload,
        )
        for item in readings
    ]
    normalized = normalize_legacy_context(
        logs=context_logs,
        heartbeats=context_heartbeats,
        readings=context_readings,
        definition=definition,
    )
    if package_runtime:
        error_code_types = {
            str(item.source.value): item.evidence_type
            for item in package_runtime.bundle.hardware.evidence_mapping
            if item.source.type == "device_error_code"
        }
        normalized.events = [
            item.model_copy(update={"type": error_code_types.get(item.type, item.type)})
            for item in normalized.events
        ]
    return DiagnosisContext(
        device_id=device.device_key,
        evaluated_at=reference,
        last_seen_at=device.last_seen_at,
        logs=context_logs,
        heartbeats=context_heartbeats,
        readings=context_readings,
        experiment_template=experiment_template,
        experiment_id=definition.experiment.id if definition else None,
        experiment_version=definition.experiment.version if definition else None,
        experiment_record_id=(package_runtime.experiment.id if package_runtime else None),
        experiment_version_id=(package_runtime.version.id if package_runtime else None),
        experiment_package_hash=(package_runtime.version.package_hash if package_runtime else None),
        experiment_package_schema_version=(
            package_runtime.version.schema_version if package_runtime else None
        ),
        experiment_package_is_test_data=(
            package_runtime.version.is_test_data if package_runtime else False
        ),
        experiment_definition_hash=definition_hash,
        device=DeviceDescriptor(
            id=device.device_key,
            family=(definition.hardware.family if definition else device.device_type),
            model=(definition.hardware.board_model if definition else device.hardware_model),
            firmware_version=device.firmware_version,
            metadata=device.metadata_json,
        ),
        components=definition.hardware.components if definition else [],
        interfaces=definition.interfaces if definition else [],
        observations=normalized.observations,
        events=normalized.events,
        unknown_raw_data=normalized.unknown_records,
        expected_behaviors=definition.expected_behaviors if definition else [],
        runtime_expectations=definition.runtime_expectations if definition else None,
        artifact_selection=definition.diagnostics if definition else {},
        knowledge_scope=definition.knowledge_scope if definition else {},
        package_rule_document=(package_runtime.rule_document if package_runtime else None),
        package_fault_tree_document=(
            package_runtime.fault_tree_document if package_runtime else None
        ),
    )


def build_raw_diagnosis_context(
    *,
    device_id: str,
    definition: ExperimentDefinition,
    records: list[RawDeviceRecord],
    evaluated_at: datetime,
    last_seen_at: Optional[datetime] = None,
    firmware_version: Optional[str] = None,
    device_metadata: Optional[dict] = None,
) -> DiagnosisContext:
    """Build the same core context from experiment-specific raw data.

    This is the non-database entry point used by future adapters and migration
    fixtures. It shares the rule, fault-tree and result engines with the legacy
    PostgreSQL-backed flow.
    """

    normalized = normalize_raw_device_data(records, definition)
    return DiagnosisContext(
        device_id=device_id,
        evaluated_at=evaluated_at,
        last_seen_at=last_seen_at,
        experiment_id=definition.experiment.id,
        experiment_version=definition.experiment.version,
        experiment_definition_hash=experiment_definition_hash(definition),
        device=DeviceDescriptor(
            id=device_id,
            family=definition.hardware.family,
            model=definition.hardware.board_model,
            firmware_version=firmware_version,
            metadata=device_metadata or {},
        ),
        components=definition.hardware.components,
        interfaces=definition.interfaces,
        observations=normalized.observations,
        events=normalized.events,
        unknown_raw_data=normalized.unknown_records,
        expected_behaviors=definition.expected_behaviors,
        runtime_expectations=definition.runtime_expectations,
        artifact_selection=definition.diagnostics,
        knowledge_scope=definition.knowledge_scope,
    )


def diagnose(context: DiagnosisContext) -> DiagnosisOutcome:
    if context.package_rule_document:
        ruleset, ruleset_hash = load_rules_from_document(
            context.package_rule_document,
            context=context,
        )
    else:
        ruleset, ruleset_hash = load_rules(context=context if context.experiment_id else None)
    if context.runtime_expectations is not None:
        ruleset, ruleset_hash = include_runtime_health_rules(ruleset)
    outcome = evaluate_rules(context, ruleset, ruleset_hash)
    context.inference_state.rule_hits = [item.model_dump(mode="json") for item in outcome.matches]
    context.inference_state.evidence = [
        {
            "rule_id": item.rule_id,
            "items": [evidence.model_dump(mode="json") for evidence in item.evidence],
        }
        for item in outcome.matches
    ]
    return outcome


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
        experiment_id=context.experiment_id,
        experiment_version=context.experiment_version,
        experiment_record_id=context.experiment_record_id,
        experiment_version_id=context.experiment_version_id,
        experiment_definition_hash=context.experiment_definition_hash,
        knowledge_scope=context.knowledge_scope.model_dump(mode="json"),
        is_test_data=context.experiment_package_is_test_data
        or any(item.is_test_data for item in sources),
        created_at=utc_now(),
    )
    db.add(record)
    db.flush()
    evidence_rows = [
        DiagnosisEvidence(
            diagnosis_id=record.id,
            experiment_record_id=context.experiment_record_id,
            experiment_version_id=context.experiment_version_id,
            evidence_type=f"observation.{item.metric}"[:100],
            source_type=item.source[:50],
            source_ref=item.source_ref[:200],
            normalized_value={
                "kind": "observation",
                "normalized_id": item.id,
                "component_id": item.component_id,
                "interface_id": item.interface_id,
                "metric": item.metric,
                "value": item.value,
                "unit": item.unit,
                "status": item.status,
            },
            raw_payload=item.raw_payload,
            occurred_at=item.observed_at,
        )
        for item in context.observations
    ] + [
        DiagnosisEvidence(
            diagnosis_id=record.id,
            experiment_record_id=context.experiment_record_id,
            experiment_version_id=context.experiment_version_id,
            evidence_type=item.type[:100],
            source_type=item.source[:50],
            source_ref=item.source_ref[:200],
            normalized_value={
                "kind": "event",
                "normalized_id": item.id,
                "component_id": item.component_id,
                "interface_id": item.interface_id,
                "event_type": item.type,
                "status": item.status,
            },
            raw_payload=item.raw_payload,
            occurred_at=item.occurred_at,
        )
        for item in context.events
    ]
    evidence_rows.extend(
        DiagnosisEvidence(
            diagnosis_id=record.id,
            experiment_record_id=context.experiment_record_id,
            experiment_version_id=context.experiment_version_id,
            evidence_type=f"rule.{evidence.fact}"[:100],
            source_type="rule_engine",
            source_ref=f"rule:{match.rule_id}:{index}"[:200],
            normalized_value={
                "kind": "rule_fact",
                "rule_id": match.rule_id,
                "error_type": match.error_type,
                "fact": evidence.fact,
                "observed_value": evidence.observed_value,
                "details": evidence.details,
            },
            raw_payload={},
            occurred_at=context.evaluated_at,
        )
        for match in outcome.matches
        for index, evidence in enumerate(match.evidence)
    )
    seen: set[tuple[str, str, str]] = set()
    for evidence in evidence_rows:
        key = (evidence.evidence_type, evidence.source_type, evidence.source_ref)
        if key not in seen:
            db.add(evidence)
            seen.add(key)
    if commit:
        db.commit()
        db.refresh(record)
    else:
        # Graph callers link the result to their workflow in the same transaction.
        # This closes the crash window where a result was committed but the replay
        # had no durable reference and therefore created a duplicate result.
        db.flush()
    return record
