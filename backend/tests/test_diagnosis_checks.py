from copy import deepcopy
from uuid import uuid4

from shared_error_boundary import workflow_environment
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from test_teaching_materials import start

from app.evaluation.workflow_environment import DEVICE_KEY
from app.models import DiagnosisCheck, DiagnosisResult


def check(env, **kwargs):
    return env.request(
        "POST",
        f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}",
        json={"request_id": str(uuid4()), **kwargs},
    )


def test_refresh_and_repeat_do_not_create_diagnoses_or_call_provider():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        calls = len(env.provider.calls)
        identity = str(uuid4())
        response = check(env, request_id=identity, baseline_id=first["diagnosis_result_id"])
        assert response.status_code == 201, response.text
        assert response.json()["check"]["status"] == "no_new_data"
        assert response.json()["id"] == first["id"]
        replay = check(env, request_id=identity, baseline_id=first["diagnosis_result_id"])
        assert replay.json()["check"] == response.json()["check"]
        assert len(env.provider.calls) == calls
        with env.sessions() as db:
            assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 1


def test_same_request_different_payload_conflicts():
    with workflow_environment("dht11_temperature_humidity") as env:
        start(env)
        identity = str(uuid4())
        assert check(env, request_id=identity).status_code == 201
        assert check(env, request_id=identity, lookback_seconds=123).status_code == 409


def test_receipt_query_is_read_only_and_scope_checked():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        response = check(env, baseline_id=first["diagnosis_result_id"])
        assert response.status_code == 201
        before = deepcopy(env.provider.calls)
        result = env.request(
            "GET", f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}/checks/latest"
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "no_new_data"
        assert env.provider.calls == before
        with env.sessions() as db:
            assert db.scalar(select(func.count()).select_from(DiagnosisCheck)) == 2


def ingest(env, *, records=None, when=None, request_id=None):
    import json
    from datetime import datetime, timezone

    from test_teaching_materials import PACKAGE_ROOT

    if records is None:
        records = next(
            c["records"]
            for c in json.loads(
                (PACKAGE_ROOT.parent / "evaluation/workflow_inputs.json").read_text()
            )
            if c["id"] == "dht-valid"
        )
    now = (when or datetime.now(timezone.utc)).isoformat()
    response = env.request(
        "POST",
        "/api/v1/device/ingest",
        json={
            "protocolVersion": "1.0",
            "schemaVersion": "1",
            "requestId": request_id or str(uuid4()),
            "bootId": str(uuid4()),
            "sequenceNo": 1,
            "sentAt": now,
            "isTestData": True,
            "records": [{**r, "occurredAt": now} for r in records],
        },
    )
    assert response.status_code == 201, response.text
    return response


def test_new_sampling_with_same_values_is_new_evidence_but_heartbeat_is_not_repair():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        ingest(env)
        response = check(env, baseline_id=first["diagnosis_result_id"])
        assert response.status_code == 201, response.text
        second = response.json()
        assert second["diagnosis_result_id"] != first["diagnosis_result_id"]
        assert second["check"]["new_records"] > 0
        assert any(i["observation"] == "still_detected" for i in second["check"]["issues"])
        ingest(env, records=[{"type": "heartbeat", "payload": {"metadata": {}}}])
        response = check(env, baseline_id=second["diagnosis_result_id"])
        assert response.status_code == 201, response.text
        assert response.json()["check"]["status"] == "no_new_data"
        assert all(
            i["observation"] == "no_new_related_data" for i in response.json()["check"]["issues"]
        )


def test_stale_baseline_with_different_new_input_is_rejected():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        ingest(env)
        assert check(env, baseline_id=first["diagnosis_result_id"]).status_code == 201
        ingest(env)
        assert check(env, baseline_id=first["diagnosis_result_id"]).status_code == 409


def test_snapshot_is_frozen_before_workflow_and_resume_after_receipt_failure(monkeypatch):
    from app.services import diagnosis_checks as service

    original = service.start_workflow
    compare = service.comparison
    with workflow_environment("dht11_temperature_humidity") as env:
        ingest(env)

        def upload_then_start(*args, **kwargs):
            ingest(env)
            return original(*args, **kwargs)

        monkeypatch.setattr(service, "start_workflow", upload_then_start)
        identity = str(uuid4())

        def fail_receipt(*args):
            raise OperationalError(
                "synthetic receipt read", {},
                Exception("synthetic receipt storage outage after business commit"),
            )

        monkeypatch.setattr(service, "comparison", fail_receipt)
        assert check(env, request_id=identity).status_code == 503
        with env.sessions() as db:
            cmd = db.scalar(select(DiagnosisCheck))
            diagnosis = db.scalar(select(DiagnosisResult))
            assert cmd.status == "pending"
            assert len(diagnosis.context_snapshot["logs"]) == len(cmd.context_snapshot["logs"])
            assert (
                diagnosis.context_snapshot["evaluated_at"] == cmd.context_snapshot["evaluated_at"]
            )
        calls = len(env.provider.calls)
        monkeypatch.setattr(service, "start_workflow", original)
        monkeypatch.setattr(service, "comparison", compare)
        # Read-only refresh never executes; another request cannot abandon an uncertain one.
        assert (
            env.request(
                "GET", f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}/checks/latest"
            ).json()["status"]
            == "pending"
        )
        assert check(env).status_code == 409
        response = check(env, request_id=identity)
        assert response.status_code == 201, response.text
        assert response.json()["check"]["status"] == "completed"
        assert len(env.provider.calls) == calls
        with env.sessions() as db:
            assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 1


def test_other_session_cannot_read_receipt_or_compare_baseline():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        other = env.other_student_headers()
        path = f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}"
        result = env.request("GET", path + "/checks/latest", headers=other)
        assert result.status_code == 200 and result.json() is None
        result = env.request(
            "POST",
            path,
            headers=other,
            json={"request_id": str(uuid4()), "baseline_id": first["diagnosis_result_id"]},
        )
        assert result.status_code == 403, result.text


def test_invalid_experiment_does_not_leave_an_unrecoverable_pending_command():
    with workflow_environment("dht11_temperature_humidity") as env:
        result = check(env, experiment_id="gpio_led_output")
        assert result.status_code == 403, result.text
        with env.sessions() as db:
            assert db.scalar(select(func.count()).select_from(DiagnosisCheck)) == 0
        assert check(env).status_code == 201


def test_late_upload_is_new_input_but_cannot_prove_post_repair_recovery():
    from datetime import datetime, timedelta, timezone

    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        ingest(env, when=datetime.now(timezone.utc) - timedelta(minutes=1))
        result = check(env, baseline_id=first["diagnosis_result_id"])
        assert result.status_code == 201, result.text
        assert result.json()["check"]["new_records"] > 0
        assert all(
            i["observation"] != "verified_recovery" for i in result.json()["check"]["issues"]
        )
        with env.sessions() as db:
            row = db.get(DiagnosisResult, result.json()["diagnosis_result_id"])
            assert row.context_snapshot["recheck_recovery_allowed"] is False


def test_legacy_deterministic_result_can_be_the_current_comparison_baseline():
    with workflow_environment("dht11_temperature_humidity") as env:
        start(env)
        ingest(env)
        legacy = env.request("POST", f"/api/v1/diagnosis/devices/{DEVICE_KEY}/run", json={})
        assert legacy.status_code == 201, legacy.text
        result = check(env, baseline_id=legacy.json()["id"])
        assert result.status_code == 201, result.text
        assert result.json()["check"]["baseline_id"] == legacy.json()["id"]


def test_duplicate_upload_does_not_create_another_check_result():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        original = next(e["request"] for e in env.events if e["path"].endswith("/ingest"))
        replay = env.request("POST", "/api/v1/device/ingest", json=original)
        assert replay.status_code in {200, 201}, replay.text
        result = check(env, baseline_id=first["diagnosis_result_id"])
        assert result.status_code == 201, result.text
        assert result.json()["check"]["status"] == "no_new_data"


def test_sliding_old_failures_out_of_window_does_not_confirm_recovery():
    from datetime import datetime, timedelta, timezone

    with workflow_environment("dht11_temperature_humidity") as env:
        ingest(env, when=datetime.now(timezone.utc) - timedelta(minutes=1))
        first = check(env, lookback_seconds=3600).json()
        result = check(env, baseline_id=first["diagnosis_result_id"], lookback_seconds=1)
        assert result.status_code == 201, result.text
        old_ids = {i["episode_id"] for i in first["check"]["issues"]}
        old = [i for i in result.json()["check"]["issues"] if i["episode_id"] in old_ids]
        assert old and all(i["observation"] == "no_new_related_data" for i in old)
        assert all(i["handling_status"] != "resolved" for i in old)


def test_waiting_teacher_keeps_its_work_order_and_recheck_uses_no_new_ai():
    from app.models import InterventionCase

    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        response = env.request(
            "POST",
            f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback",
            json={"request_id": str(uuid4()), "action": "request_teacher_help"},
        )
        assert response.status_code == 201, response.text
        with env.sessions() as db:
            before = [(c.id, c.status) for c in db.scalars(select(InterventionCase))]
        calls = len(env.provider.calls)
        ingest(env)
        result = check(env, baseline_id=first["diagnosis_result_id"])
        assert result.status_code == 201, result.text
        assert result.json()["diagnosis_result_id"] != first["diagnosis_result_id"]
        assert len(env.provider.calls) == calls
        with env.sessions() as db:
            assert [(c.id, c.status) for c in db.scalars(select(InterventionCase))] == before


def test_fallback_time_cannot_prove_recovery_and_device_cannot_forge_provenance():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        original = deepcopy(next(e["request"] for e in env.events if e["path"].endswith("/ingest")))
        original["requestId"] = str(uuid4())
        original["bootId"] = str(uuid4())
        for record in original["records"]:
            record["occurredAt"] = "invalid-device-time"
            record["payload"]["time_quality"] = "device_reported"
        assert env.request("POST", "/api/v1/device/ingest", json=original).status_code == 422
        for record in original["records"]:
            record["payload"].pop("time_quality")
        assert env.request("POST", "/api/v1/device/ingest", json=original).status_code == 201
        result = check(env, baseline_id=first["diagnosis_result_id"])
        assert result.status_code == 201, result.text
        with env.sessions() as db:
            context = db.get(DiagnosisResult, result.json()["diagnosis_result_id"]).context_snapshot
            assert context["recheck_recovery_allowed"] is False
            qualities = context["recheck_source_time_quality"]
            fallback = [
                row
                for row in context["logs"]
                if qualities.get("device_log:" + row["id"]) == "server_fallback"
            ]
            assert len(fallback) == 5


def test_after_resolution_fallback_records_do_not_reopen_but_new_timed_failures_do():
    from app.services.diagnosis_episode import issue_links

    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        closed = env.request(
            "POST",
            f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback",
            json={"request_id": str(uuid4()), "action": "resolved"},
        )
        assert closed.status_code == 201, closed.text
        original = deepcopy(next(e["request"] for e in env.events if e["path"].endswith("/ingest")))
        original.update(requestId=str(uuid4()), bootId=str(uuid4()))
        for record in original["records"]:
            record["occurredAt"] = "invalid"
        assert env.request("POST", "/api/v1/device/ingest", json=original).status_code == 201
        late = check(env, baseline_id=first["diagnosis_result_id"])
        assert late.status_code == 201, late.text
        assert all(i["observation"] == "late_or_unverified" for i in late.json()["check"]["issues"])
        with env.sessions() as db:
            links = issue_links(db, db.get(DiagnosisResult, late.json()["diagnosis_result_id"]))
            assert links and all(link.episode.status == "resolved" for link in links)
            original_ids = {link.episode_id for link in links}
        ingest(env)
        fresh = check(env, baseline_id=late.json()["diagnosis_result_id"])
        assert fresh.status_code == 201, fresh.text
        assert {i["observation"] for i in fresh.json()["check"]["issues"]} == {
            "closed_previous_incident",
            "newly_detected",
        }
        with env.sessions() as db:
            links = issue_links(db, db.get(DiagnosisResult, fresh.json()["diagnosis_result_id"]))
            assert links and all(link.episode_id not in original_ids for link in links)
            assert all(
                link.episode.failure_count == 1 and link.episode.status == "open" for link in links
            )


def test_new_component_reading_does_not_claim_old_failure_logs_are_new_failures():
    from app.services.diagnosis_episode import issue_links

    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        ingest(
            env,
            records=[
                {
                    "type": "reading",
                    "payload": {
                        "sensor_type": "dht11",
                        "metric_key": "temperature",
                        "value": 25,
                        "unit": "C",
                    },
                }
            ],
        )
        result = check(env, baseline_id=first["diagnosis_result_id"])
        assert result.status_code == 201, result.text
        assert any(
            i["observation"] == "prior_evidence_still_matches"
            for i in result.json()["check"]["issues"]
        )
        with env.sessions() as db:
            links = issue_links(db, db.get(DiagnosisResult, result.json()["diagnosis_result_id"]))
            assert all(link.episode.failure_count == 1 for link in links)
