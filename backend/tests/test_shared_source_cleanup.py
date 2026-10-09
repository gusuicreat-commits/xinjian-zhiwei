"""Referenced synthetic raw records must survive whole-run cleanup attempts."""

from datetime import timedelta
from uuid import uuid4

from pipeline import dht11_reading, diagnose_session, heartbeat, ingest_batch, publish_package
from sqlalchemy import select

from app.models import DiagnosisEvidence, ExperimentSession, SensorReading
from app.models.base import utc_now


def test_synthetic_cleanup_leaves_evidence_pointing_to_deleted_reading(api_context):
    run_id = str(uuid4())
    now = utc_now()
    client = api_context["client"]
    ingest_batch(
        client,
        api_context["headers"],
        [dht11_reading("temperature", 24, occurred_at=now), heartbeat(occurred_at=now)],
        sent_at=now,
        test_run_id=run_id,
    )
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        session.experiment_version_id = publish_package(db).id
        db.commit()
        diagnosis = diagnose_session(db, session, evaluated_at=now + timedelta(seconds=1))
        reading = db.scalar(select(SensorReading))
        evidence = db.scalar(
            select(DiagnosisEvidence).where(
                DiagnosisEvidence.diagnosis_id == diagnosis.id,
                DiagnosisEvidence.source_type == "sensor_reading",
                DiagnosisEvidence.source_ref == reading.id,
            )
        )
        reading_id, evidence_id = reading.id, evidence.id
    deleted = client.delete(f"/api/v1/device/test-runs/{run_id}", headers=api_context["headers"])
    assert deleted.status_code == 409
    with api_context["session_factory"]() as db:
        assert db.get(SensorReading, reading_id) is not None
        assert db.get(DiagnosisEvidence, evidence_id).source_ref == reading_id
