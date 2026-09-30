"""One transaction boundary for raw-source use and synthetic-run deletion."""

from sqlalchemy import select

from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.diagnosis_check import DiagnosisCheck
from app.models.diagnosis_evidence import DiagnosisEvidence
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowRun
from app.models.sensor_reading import SensorReading
from app.services.data_scope import ScopeConflict


def lock_source_device(db, device_id):
    device = db.scalar(
        select(Device)
        .where(Device.id == device_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if device is None:
        raise ScopeConflict("source device is unavailable")
    return device


def protect_context_sources(db, device_id, context):
    """Revalidate frozen input under the same lock held through reference commit."""
    lock_source_device(db, device_id)
    for model, records in (
        (DeviceLog, context.logs),
        (DeviceHeartbeat, context.heartbeats),
        (SensorReading, context.readings),
    ):
        ids = {record.id for record in records}
        source_type = {
            DeviceLog: "device_log",
            DeviceHeartbeat: "device_heartbeat",
            SensorReading: "sensor_reading",
        }[model]
        ids.update(
            item.source_ref
            for item in [*context.observations, *context.events]
            if item.source == source_type
        )
        if ids:
            current = set(
                db.scalars(select(model.id).where(model.device_id == device_id, model.id.in_(ids)))
            )
            if current != ids:
                raise ScopeConflict("frozen input contains unavailable raw sources; check again")


def _references(value, source_ids):
    if isinstance(value, str):
        # Includes historic log_id:<uuid> / reading:<uuid> and normalized refs.
        return any(source_id in value for source_id in source_ids)
    if isinstance(value, dict):
        return any(_references(item, source_ids) for item in value.values())
    if isinstance(value, list):
        return any(_references(item, source_ids) for item in value)
    return False


def assert_sources_unused(db, device_id, source_ids):
    if not source_ids:
        return
    # Old in-flight workflows may have checkpoint-only input. Fail closed until
    # their durable outcome can be inspected; never inspect only the latest run.
    if db.scalar(
        select(DiagnosisWorkflowRun.id)
        .where(
            DiagnosisWorkflowRun.device_id == device_id,
            DiagnosisWorkflowRun.status.not_in(["completed", "rejected", "failed"]),
        )
        .limit(1)
    ):
        raise ScopeConflict("raw sources may be in use by a pending workflow")
    for evidence in db.scalars(
        select(DiagnosisEvidence)
        .join(DiagnosisResult, DiagnosisResult.id == DiagnosisEvidence.diagnosis_id)
        .where(DiagnosisResult.device_id == device_id)
    ):
        if _references(evidence.source_ref, source_ids) or _references(
            evidence.normalized_value, source_ids
        ):
            raise ScopeConflict("raw sources are retained by diagnosis evidence")
    for model in (DiagnosisResult, DiagnosisCheck):
        for row in db.scalars(select(model).where(model.device_id == device_id)):
            snapshot = row.context_snapshot
            if not snapshot or _references(snapshot, source_ids):
                raise ScopeConflict("raw sources are retained by frozen diagnostic input")
