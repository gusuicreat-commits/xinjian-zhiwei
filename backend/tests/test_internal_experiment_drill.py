"""A clean PostgreSQL lab: admin APIs, operator CLI, student APIs and real diagnosis.

All records are synthetic. No board, provider or business database participates.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_internal_experiment_preparation import SECRETS
from test_migration_r2 import migration_db as _migration_db

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.session import get_db
from app.experiment_packages.loader import load_experiment_package, package_documents
from app.models import (
    AICallRecord,
    Course,
    DiagnosisEvidence,
    ExperimentSession,
    SensorReading,
    User,
)
from app.services.rbac import assign_role, ensure_rbac_catalog

migration_db = _migration_db
ROOT = Path(__file__).resolve().parents[2]


def test_clean_lab_cli_and_api_drill(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        roles = ensure_rbac_catalog(db)
        actor = User(
            username="internal-drill-admin",
            display_name="合成管理员，仅软件自审",
            password_hash=hash_password("internal-drill-admin-password", iterations=1000),
            is_test_data=True,
        )
        db.add(actor)
        db.flush()
        assign_role(db, actor, roles["admin"])
        db.commit()
        assert db.scalar(select(func.count(Course.id))) == 0
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.state.diagnosis_graph = build_diagnosis_graph(InMemorySaver())
    settings = Settings(
        _env_file=None,
        app_env="test",
        ai_enabled=False,
        ai_api_key=None,
        ai_local_api_key=None,
        ai_cloud_api_key=None,
    )

    def get_test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_settings] = lambda: settings
    events = []
    with TestClient(app) as client:

        def request(method, path, *, expected=200, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            assert response.status_code == expected, response.text
            body = response.json()
            events.append(
                {
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "request": None if path == "/auth/session" else kwargs.get("json"),
                    "result": {"authenticated": True} if path == "/auth/session" else body,
                }
            )
            return body

        login = request(
            "POST",
            "/auth/session",
            json={"username": "internal-drill-admin", "password": "internal-drill-admin-password"},
        )
        admin_headers = {"Authorization": "Bearer " + login["access_token"]}
        bundle, _ = load_experiment_package(
            ROOT / "backend/experiment_packages/dht11_temperature_humidity"
        )
        payload = {"documents": package_documents(bundle), "is_test_data": True}
        request("POST", "/experiments/packages/validate", headers=admin_headers, json=payload)
        version = request(
            "POST",
            "/experiments/packages/import",
            expected=201,
            headers=admin_headers,
            json=payload,
        )
        for status in ["pending", "approved", "published"]:
            request(
                "POST",
                "/experiments/package-versions/" + version["id"] + "/status",
                headers=admin_headers,
                json={"status": status},
            )
        cli_env = {
            **os.environ,
            "APP_ENV": "test",
            "PYTHONPATH": str(ROOT / "backend"),
            "DRILL_TEST_DSN": engine.url.render_as_string(hide_password=False),
            "DRILL_ADMIN_TOKEN": login["access_token"],
            "DRILL_STUDENT_PASSWORD": SECRETS["student_password"],
            "DRILL_TEACHER_PASSWORD": SECRETS["teacher_password"],
            "DRILL_DEVICE_TOKEN": SECRETS["device_token"],
        }

        def cli(operation):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.cli.prepare_internal_experiment",
                    operation,
                    "--test-database",
                    "--dsn-env",
                    "DRILL_TEST_DSN",
                    "--actor-token-env",
                    "DRILL_ADMIN_TOKEN",
                    "--prefix",
                    "lab-drill",
                    "--package-version-id",
                    version["id"],
                    "--package-hash",
                    version["package_hash"],
                    "--student-password-env",
                    "DRILL_STUDENT_PASSWORD",
                    "--teacher-password-env",
                    "DRILL_TEACHER_PASSWORD",
                    "--device-token-env",
                    "DRILL_DEVICE_TOKEN",
                ],
                env=cli_env,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            assert all(value not in result.stdout + result.stderr for value in SECRETS.values())
            body = json.loads(result.stdout)
            events.append({"cli": operation, "result": body})
            return body

        assert cli("plan")["state"] == "absent"
        prepared = cli("apply")
        assert cli("apply") == prepared == cli("status")
        objects = prepared["objects"]
        student = request(
            "POST",
            "/auth/session",
            json={"username": "lab-drill-student", "password": SECRETS["student_password"]},
        )
        user_headers = {"Authorization": "Bearer " + student["access_token"]}
        tasks = request("GET", "/student/assignments", headers=user_headers)
        assert len(tasks) == 1 and tasks[0]["id"] == objects["assignment_id"]
        session = request(
            "POST",
            "/student/experiment-sessions",
            expected=201,
            headers=user_headers,
            json={
                "request_id": str(uuid4()),
                "device_id": objects["device_key"],
                "experiment_assignment_id": objects["assignment_id"],
            },
        )
        assert session["experiment_version_id"] == version["id"]
        user_headers["X-Experiment-Session-ID"] = session["id"]
        user_headers["X-Device-ID"] = objects["device_key"]
        device_headers = {
            "X-Device-ID": objects["device_key"],
            "X-Device-Token": SECRETS["device_token"],
            "X-Experiment-Session-ID": session["id"],
        }
        path = "/diagnosis-workflows/devices/" + objects["device_key"]

        def check(baseline=None):
            data = {"request_id": str(uuid4())}
            if baseline:
                data["baseline_id"] = baseline
            return request("POST", path, expected=201, headers=user_headers, json=data)

        def batch(records, when=None):
            now = (when or datetime.now(timezone.utc)).isoformat()
            return {
                "protocolVersion": "1.0",
                "schemaVersion": "1",
                "requestId": str(uuid4()),
                "bootId": "synthetic-drill-" + str(uuid4()),
                "sequenceNo": 1,
                "sentAt": datetime.now(timezone.utc).isoformat(),
                "isTestData": True,
                "records": [{**record, "occurredAt": now} for record in records],
            }

        empty = check()
        assert empty["experiment_version_id"] == version["id"]
        missing = [
            item
            for item in empty["check"]["normal_assessment"]["checks"]
            if item["check"] == "required_fields_valid"
        ]
        assert {item["metric"] for item in missing} == {"temperature", "humidity"}
        assert all(item["status"] == "unknown" and not item["source_refs"] for item in missing)
        normal_records = json.loads(
            (ROOT / "firmware/esp32_dht11/docs/protocol-example.json").read_text()
        )["records"]
        first_payload = batch(normal_records)
        request("POST", "/device/ingest", expected=201, headers=device_headers, json=first_payload)
        with factory() as db:
            count = db.scalar(select(func.count(SensorReading.id)))
        request("POST", "/device/ingest", expected=201, headers=device_headers, json=first_payload)
        with factory() as db:
            assert db.scalar(select(func.count(SensorReading.id))) == count
        normal = check(empty["diagnosis_result_id"])
        assert normal["diagnosis_result_id"] != empty["diagnosis_result_id"]
        assessment = normal["check"]["normal_assessment"]
        assert assessment["status"] == "unknown"
        assert assessment["verification_status"] == "pending_hardware"
        assert all(
            item["status"] == "satisfied"
            for item in assessment["checks"]
            if item["check"] == "required_fields_valid"
        )
        # A wrong session/device is rejected without storing a new reading.
        request(
            "POST",
            "/device/ingest",
            expected=401,
            headers={**device_headers, "X-Device-ID": "not-the-drill-device"},
            json=batch(normal_records),
        )
        request(
            "POST",
            "/device/ingest",
            expected=403,
            headers={**device_headers, "X-Experiment-Session-ID": str(uuid4())},
            json=batch(normal_records),
        )
        with factory() as db:
            assert db.scalar(select(func.count(SensorReading.id))) == count
        faults = next(
            c["records"]
            for c in json.loads((ROOT / "backend/evaluation/workflow_inputs.json").read_text())
            if c["id"] == "dht-valid"
        )
        request("POST", "/device/ingest", expected=201, headers=device_headers, json=batch(faults))
        fault = check(normal["diagnosis_result_id"])
        assert fault["status"] == "waiting_feedback"
        assert {item["error_type"] for item in fault["check"]["issues"]} == {"SENSOR_READ_FAILED"}
        visible = request("GET", "/student/dashboard", headers=user_headers)
        encoded = json.dumps(visible["guidance"], ensure_ascii=False)
        assert "dht11.delivery_evidence" in encoded and "dht11.identity_scope" in encoded
        request(
            "POST",
            "/student/diagnoses/" + fault["diagnosis_result_id"] + "/feedback",
            expected=201,
            headers=user_headers,
            json={
                "request_id": str(uuid4()),
                "action": "unresolved",
            },
        )
        request(
            "POST",
            "/device/ingest",
            expected=201,
            headers=device_headers,
            json=batch(normal_records[:1], datetime.now(timezone.utc) - timedelta(hours=1)),
        )
        checked = check(fault["diagnosis_result_id"])
        assert checked["check"]["status"] == "no_new_data"
        assert checked["diagnosis_result_id"] == fault["diagnosis_result_id"]
        request(
            "POST",
            "/device/ingest",
            expected=201,
            headers=device_headers,
            json=batch(normal_records),
        )
        rechecked = check(checked["diagnosis_result_id"])
        assert rechecked["experiment_version_id"] == version["id"]
        assert rechecked["diagnosis_result_id"] != checked["diagnosis_result_id"]
        # New valid values do not erase the failures still in the diagnosis window.
        assert rechecked["check"]["normal_assessment"]["status"] == "abnormal"
        assert any(
            item["error_type"] == "SENSOR_READ_FAILED"
            and item["observation"] == "prior_evidence_still_matches"
            and item["handling_status"] == "open"
            for item in rechecked["check"]["issues"]
        )
        with factory() as db:
            audits = list(db.scalars(select(AICallRecord)))
            assert audits and all(a.status == "skipped" and a.attempt_count == 0 for a in audits)
            assert db.scalar(select(func.count(DiagnosisEvidence.id))) > 0
            assert db.get(ExperimentSession, session["id"]).experiment_version_id == version["id"]
        request(
            "POST",
            "/student/experiment-sessions/" + session["id"] + "/end",
            headers=user_headers,
            json={"request_id": str(uuid4()), "expected_version": 1, "reason": "completed"},
        )
        with factory() as db:
            assert db.get(ExperimentSession, session["id"]).status == "completed"
        assert cli("status") == prepared
    report = os.environ.get("XINJIAN_INTERNAL_DRILL_REPORT")
    if report:
        p = Path(report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "status": "passed",
                    "data_origin": "synthetic",
                    "real_provider_calls": 0,
                    "package": version,
                    "preparation": prepared,
                    "events": events,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
