"""Referenced synthetic raw records must survive whole-run cleanup attempts."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from test_device_protocol_v1 import _batch

from app.models import (
    Device,
    DiagnosisEvidence,
    DiagnosisResult,
    SensorReading,
)


def test_synthetic_cleanup_leaves_evidence_pointing_to_deleted_reading(api_context):
    run_id = str(uuid4())
    payload = _batch()
    payload["testRunId"] = run_id
    client = api_context["client"]
    created = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)
    assert created.status_code == 201
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        reading = db.scalar(select(SensorReading))
        diagnosis = DiagnosisResult(
            device_id=device.id,
            evaluated_at=datetime.now(timezone.utc),
            ruleset_version="synthetic",
            ruleset_hash="x" * 64,
            input_fingerprint="y" * 64,
            matched_rules=[],
            evidence=[],
            context_snapshot={},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.flush()
        evidence = DiagnosisEvidence(
            diagnosis_id=diagnosis.id,
            evidence_type="reading",
            source_type="sensor_reading",
            source_ref=reading.id,
            normalized_value={"value": reading.value},
            raw_payload=reading.raw_payload,
            occurred_at=reading.observed_at,
        )
        db.add(evidence)
        db.commit()
        reading_id, evidence_id = reading.id, evidence.id
    deleted = client.delete(f"/api/v1/device/test-runs/{run_id}", headers=api_context["headers"])
    assert deleted.status_code == 409
    with api_context["session_factory"]() as db:
        assert db.get(SensorReading, reading_id) is not None
        assert db.get(DiagnosisEvidence, evidence_id).source_ref == reading_id
