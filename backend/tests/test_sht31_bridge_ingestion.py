"""Real HTTP ingestion of the delivered bridge sample, without invented hardware data."""

import json
from datetime import timedelta
from pathlib import Path

from pipeline import diagnose_session, publish_package
from sqlalchemy import select

from app.models import DiagnosisEvidence, ExperimentSession
from app.models.base import utc_now


def test_delivered_bridge_sample_normalizes_sht31_observations_and_failure(api_context):
    sample = json.loads(
        (Path(__file__).resolve().parents[2] / "bridge/docs/protocol-example.json").read_text()
    )
    response = api_context["client"].post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=sample,
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["records"]) == 5
    with api_context["session_factory"]() as db:
        version = publish_package(db)
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        session.experiment_version_id = version.id
        db.commit()
        diagnosis = diagnose_session(db, session, evaluated_at=utc_now() + timedelta(seconds=1))
        rows = list(
            db.scalars(
                select(DiagnosisEvidence).where(
                    DiagnosisEvidence.diagnosis_id == diagnosis.id,
                )
            )
        )
        by_type = {row.evidence_type: row for row in rows}
        for kind, value, unit in (
            ("observation.temperature", 26.56, "°C"),
            ("observation.humidity", 40.8, "%RH"),
        ):
            reading = by_type[kind]
            assert reading.normalized_value["component_id"] == "sht31"
            assert reading.normalized_value["interface_id"] == "sht31_i2c"
            assert reading.normalized_value["value"] == value
            assert reading.normalized_value["unit"] == unit
            assert reading.raw_payload["sensor_type"] == "SHT31"
        failed = by_type["sensor.read_failed"]
        assert failed.normalized_value["component_id"] == "sht31"
        assert failed.normalized_value["interface_id"] == "sht31_i2c"
        assert failed.raw_payload["event_code"] == "SHT31_READ_FAILED"
        assert failed.raw_payload["sensor_snapshot"] == {
            "time_source": "replay_unknown",
            "source": "serial_bridge",
        }
        assert (
            diagnosis.context_snapshot["normal_assessment"]["verification_status"]
            == "pending_hardware"
        )
        # Boot is retained as a log event; it is not a sensor failure or observation.
        assert sum(row.evidence_type == "sensor.read_failed" for row in rows) == 1
