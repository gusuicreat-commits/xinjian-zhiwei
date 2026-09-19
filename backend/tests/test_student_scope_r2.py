"""Student projections must use durable session ownership, never today's binding."""

from datetime import datetime, timezone

from app.models import ExperimentSession, User
from app.models.device_log import DeviceLog


def _diagnose(api_context):
    client, headers = api_context["client"], api_context["headers"]
    assert (
        client.post(
            "/api/v1/device/logs",
            headers=headers,
            json={
                "level": "error",
                "message": "old student private detail",
                "event_code": "SENSOR_READ_FAILED",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "is_test_data": True,
            },
        ).status_code
        == 201
    )
    response = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={"lookback_seconds": 60},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_device_reassignment_hides_previous_session(api_context):
    _diagnose(api_context)
    with api_context["session_factory"]() as db:
        old = db.get(ExperimentSession, api_context["experiment_session_id"])
        old.status = "completed"
        old.ended_at = datetime.now(timezone.utc)
        student = User(
            username="replacement",
            display_name="新学生",
            password_hash="test",
            is_active=True,
            is_test_data=True,
        )
        db.add(student)
        db.flush()
        current = ExperimentSession(
            experiment_assignment_id=old.experiment_assignment_id,
            student_user_id=student.id,
            device_id=old.device_id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(current)
        db.commit()
        session_id = current.id
    headers = {**api_context["headers"], "X-Experiment-Session-ID": session_id}
    result = api_context["client"].get("/api/v1/student/dashboard", headers=headers)
    assert result.status_code == 200
    assert result.json()["diagnosis"] is None
    assert result.json()["logs"] == []
    assert result.json()["readings"] == []
    assert result.json()["guidance"] == []


def test_dashboard_rejects_wrong_or_inactive_session_and_empty_without_session(api_context):
    _diagnose(api_context)
    client = api_context["client"]
    headers = {**api_context["headers"], "X-Experiment-Session-ID": "missing"}
    assert client.get("/api/v1/student/dashboard", headers=headers).status_code == 403
    with api_context["session_factory"]() as db:
        db.get(ExperimentSession, api_context["experiment_session_id"]).status = "completed"
        db.commit()
    assert (
        client.get("/api/v1/student/dashboard", headers=api_context["headers"]).status_code == 409
    )
    legacy = {k: v for k, v in api_context["headers"].items() if k != "X-Experiment-Session-ID"}
    result = client.get("/api/v1/student/dashboard", headers=legacy)
    assert result.status_code == 200
    assert result.json()["diagnosis"] is None
    assert result.json()["logs"] == []


def test_dashboard_ambiguous_session_and_unowned_logs(api_context):
    with api_context["session_factory"]() as db:
        old = db.get(ExperimentSession, api_context["experiment_session_id"])
        db.add(
            DeviceLog(
                device_id=old.device_id,
                level="error",
                message="unknown owner",
                occurred_at=datetime.now(timezone.utc),
                raw_payload={},
            )
        )
        db.add(
            ExperimentSession(
                experiment_assignment_id=old.experiment_assignment_id,
                student_user_id=old.student_user_id,
                device_id=old.device_id,
                status="active",
                started_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    legacy = {k: v for k, v in api_context["headers"].items() if k != "X-Experiment-Session-ID"}
    assert api_context["client"].get("/api/v1/student/dashboard", headers=legacy).status_code == 409
    result = api_context["client"].get("/api/v1/student/dashboard", headers=api_context["headers"])
    assert result.status_code == 200
    assert result.json()["logs"] == []


def test_old_raw_evidence_is_not_reintroduced_by_new_diagnosis(api_context):
    from app.models import Device
    from app.services.diagnosis import build_diagnosis_context

    _diagnose(api_context)
    with api_context["session_factory"]() as db:
        old = db.get(ExperimentSession, api_context["experiment_session_id"])
        current = ExperimentSession(
            experiment_assignment_id=old.experiment_assignment_id,
            student_user_id=old.student_user_id,
            device_id=old.device_id,
            status="active",
            started_at=datetime.now(timezone.utc),
        )
        old.status = "completed"
        db.add(current)
        db.commit()
        context = build_diagnosis_context(
            db, db.get(Device, old.device_id), experiment_session_id=current.id
        )
        assert context.logs == []
        assert context.readings == []


def test_ingestion_records_only_verifiable_scope_and_never_backfills(api_context):
    from datetime import timedelta

    from app.models import Device
    from app.schemas.device import DeviceLogCreate
    from app.services.device_ingest import save_log

    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        device = db.get(Device, session.device_id)
        payload = DeviceLogCreate(
            level="error",
            message="delayed data",
            occurred_at=session.started_at.replace(tzinfo=timezone.utc) - timedelta(minutes=1),
        )
        unowned = save_log(db, device, payload)
        assert unowned.experiment_session_id is None
        explicit = save_log(db, device, payload, experiment_session_id=session.id)
        assert explicit.experiment_session_id == session.id
        db.refresh(unowned)
        assert unowned.experiment_session_id is None
    invalid = api_context["client"].post(
        "/api/v1/device/logs",
        headers={**api_context["headers"], "X-Experiment-Session-ID": "foreign"},
        json=payload.model_dump(mode="json"),
    )
    assert invalid.status_code == 403


def test_historical_inventory_is_read_only_and_contains_no_private_content(api_context):
    import json

    from app.cli.audit_historical_integrity import audit_historical_integrity
    from app.models import Device

    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        row = DeviceLog(
            device_id=device.id,
            level="error",
            message="private student raw text",
            occurred_at=datetime.now(timezone.utc),
            raw_payload={"password": "secret"},
        )
        db.add(row)
        db.commit()
        before = db.query(DeviceLog).count()
        report = audit_historical_integrity(db)
        assert report["read_only"] is True
        assert {
            "table": "device_logs",
            "record_id": row.id,
            "reason": "missing_recorded_session",
        } in report["findings"]
        assert "private student raw text" not in json.dumps(report)
        assert "secret" not in json.dumps(report)
        assert db.query(DeviceLog).count() == before
        db.refresh(row)
        assert row.experiment_session_id is None
        assert not db.dirty and not db.deleted and not db.new
