"""Synthetic inputs, real HTTP ingestion, package publication and diagnosis persistence.

No ORM rows for pipeline-derived models are fabricated here. Record factories follow
firmware/esp32_dht11/src/main.cpp and docs/device-protocol.md; LED records follow the
HTTP trust test's explicit measurement-source contract. Expected evidence types stay
in the consuming tests, independently of the production normalizer.
"""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from shared_authorization import session_actor_fixture
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import select

from app.experiment_packages.loader import load_experiment_package, package_documents
from app.models import (
    Classroom,
    Device,
    DiagnosisEvidence,
    DiagnosisResult,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentVersion,
    User,
)
from app.models.base import utc_now
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result
from app.services.experiment_packages import (
    import_experiment_package,
    transition_experiment_package,
)
from app.services.rbac import assign_role, ensure_rbac_catalog
from app.services.student_authorization import StudentActorContext

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "experiment_packages"


def _record(kind, payload, occurred_at):
    return {"type": kind, "occurredAt": (occurred_at or utc_now()).isoformat(), "payload": payload}


def dht11_failure_log(*, snapshot=None, occurred_at=None, read_completed_uptime_ms=3000):
    """An explicit snapshot replaces defaults, allowing missing-GPIO test inputs."""
    if snapshot is None:
        snapshot = {
            "component_id": "dht11",
            "interface_id": "dht11_gpio",
            "gpio": 4,
            "read_completed_uptime_ms": read_completed_uptime_ms,
        }
    return _record(
        "log",
        {
            "level": "warning",
            "message": "synthetic read failure",
            "event_code": "DHT11_READ_FAILED",
            "sensor_snapshot": dict(snapshot),
        },
        occurred_at,
    )


def dht11_reading(
    metric,
    value,
    *,
    occurred_at=None,
    conversion_triggered_uptime_ms=0,
    read_completed_uptime_ms=3000,
):
    """DHT11 measurements refer to the previous conversion, as in the firmware."""
    units = {"temperature": "°C", "humidity": "%RH"}
    return _record(
        "reading",
        {
            "sensor_type": "dht11",
            "metric_key": metric,
            "value": value,
            "unit": units[metric],
            "metadata": {
                "conversion_triggered_uptime_ms": conversion_triggered_uptime_ms,
                "read_completed_uptime_ms": read_completed_uptime_ms,
                "measurement_semantics": "previous_conversion",
                "event_time_quality": "device_reported",
            },
        },
        occurred_at,
    )


def heartbeat(*, firmware_version=None, occurred_at=None, primed=False):
    payload = {
        "metadata": {
            "source": "xinjian-esp32-dht11",
            "event_time_quality": "device_reported",
            "dht11_sample_primed": primed,
        }
    }
    # Legacy record-level firmware metadata is still accepted by protocol v1;
    # current firmware normally sends it on the envelope via ingest_batch.
    if firmware_version is not None:
        payload["firmware_version"] = firmware_version
    return _record("heartbeat", payload, occurred_at)


def led_reading(metric, value, source, *, command_id="synthetic-command", occurred_at=None):
    return _record(
        "reading",
        {
            "sensor_type": "status_led",
            "metric_key": metric,
            "value": value,
            "metadata": {"measurement_source": source, "command_id": command_id},
        },
        occurred_at,
    )


def ingest_batch(
    client,
    headers,
    records,
    *,
    boot_id=None,
    sequence_no=1,
    sent_at=None,
    request_id=None,
    firmware_version=None,
    uptime_ms=None,
    test_run_id=None,
):
    """Return the real ingestion receipt; derived rows are written only by HTTP."""
    envelope = {
        "protocolVersion": "1.0",
        "schemaVersion": "1",
        "requestId": request_id or str(uuid4()),
        "bootId": boot_id or f"pipeline-{uuid4()}",
        "sequenceNo": sequence_no,
        "sentAt": (sent_at or utc_now()).isoformat(),
        "isTestData": True,
        "records": records,
    }
    for key, value in (
        ("firmwareVersion", firmware_version),
        ("uptimeMs", uptime_ms),
        ("testRunId", test_run_id),
    ):
        if value is not None:
            envelope[key] = value
    response = client.post("/api/v1/device/ingest", headers=headers, json=envelope)
    assert response.status_code == 201, response.text
    return response.json()


def publish_package(db, name="dht11_temperature_humidity") -> ExperimentVersion:
    """Import the on-disk package and traverse its real review/publication states."""
    publisher = User(
        username=f"pipeline-publisher-{uuid4().hex}",
        display_name="synthetic publisher",
        password_hash="test-only",
        is_test_data=True,
    )
    db.add(publisher)
    authorize_write_fixture(db, publisher)
    bundle, _ = load_experiment_package(PACKAGE_ROOT / name)
    _, version = import_experiment_package(db, publisher, package_documents(bundle))
    for status in ("pending", "approved", "published"):
        transition_experiment_package(db, publisher, version, status)
    return version


def diagnose_session(
    db,
    session: ExperimentSession,
    *,
    evaluated_at: datetime | None = None,
) -> DiagnosisResult:
    """Use the session's published package; the deterministic service never calls AI."""
    device = db.get(Device, session.device_id)
    context = build_diagnosis_context(
        db,
        device,
        experiment_session_id=session.id,
        evaluated_at=evaluated_at,
    )
    # The product workflow supplies this server-owned scope before saving.
    context.feedback_scope = {
        "experiment_session_id": session.id,
        "student_user_id": session.student_user_id,
        "device_id": device.id,
    }
    return save_diagnosis_result(db, device, context, diagnose(context))


def query_task_factory(api_context):
    """Shared source/task fixture, extracted from test_query_sources.real_task."""
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        student = db.get(User, session.student_user_id)
        assign_role(db, student, ensure_rbac_catalog(db)["student"])
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        db.add(Enrollment(class_id=assignment.class_id, user_id=student.id, status="active"))
        session_actor_fixture(db, student)
        identity = StudentActorContext(
            session.device_id,
            session.id,
            account=student._actor_context,
        )
        db.commit()

        def build(batches):
            now = utc_now()
            for index, (snapshot, firmware, boot) in enumerate(batches):
                records = [
                    dht11_failure_log(
                        snapshot={"component_id": "dht11", **snapshot},
                        occurred_at=now,
                    )
                    for _ in range(5)
                ]
                if firmware is not None:
                    records.append(heartbeat(firmware_version=firmware, occurred_at=now))
                ingest_batch(
                    api_context["client"],
                    api_context["headers"],
                    records,
                    boot_id=boot,
                    sequence_no=index + 1,
                    sent_at=now,
                )
            version = publish_package(db)
            session.experiment_version_id = version.id
            db.commit()
            diagnosis = diagnose_session(db, session, evaluated_at=now + timedelta(seconds=1))
            rows = list(
                db.scalars(
                    select(DiagnosisEvidence).where(
                        DiagnosisEvidence.diagnosis_id == diagnosis.id,
                        DiagnosisEvidence.source_type == "device_log",
                    )
                )
            )
            return dict(
                factory=api_context["session_factory"],
                db=db,
                session=session,
                student=student,
                assignment=assignment,
                classroom=db.get(Classroom, assignment.class_id),
                device=db.get(Device, session.device_id),
                version=version,
                diagnosis=diagnosis,
                identity=identity,
                rows=rows,
            )

        yield build
