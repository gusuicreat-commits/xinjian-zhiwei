"""Historical inventory runs against old and current schemas without modifying either."""

import json

import pytest
from sqlalchemy import MetaData, select, text
from sqlalchemy.orm import Session
from test_migration_r2 import _seed
from test_migration_r2 import migration_db as _migration_db

from app.cli.audit_historical_integrity import audit_historical_integrity

migration_db = _migration_db


@pytest.mark.parametrize("revision", ["20260912_0027", "20260917_0028", "20260917_0029"])
def test_inventory_on_real_migration_schema_is_read_only_and_private(migration_db, revision):
    engine, migrate = migration_db
    migrate("upgrade", revision)
    secret = "SYNTHETIC-PRIVATE-TEXT-李明"
    with engine.begin() as conn:
        device = _seed(conn, "devices")
        diagnosis = _seed(
            conn,
            "diagnosis_results",
            device_id=device["id"],
            context_snapshot={"student_name": secret, "feedback_scope": secret},
            matched_rules=[{"private": secret}],
        )
        feedback = _seed(
            conn, "diagnosis_feedback", device_id=device["id"], diagnosis_result_id=diagnosis["id"]
        )
        draft = _seed(
            conn,
            "knowledge_case_drafts",
            diagnosis_result_id=diagnosis["id"],
            feedback_id=feedback["id"],
            status="approved",
        )
        for _ in range(2):
            _seed(conn, "knowledge_cases", source_ref=f"diagnosis-case-draft:{draft['id']}")
        for name in ("device_logs", "sensor_readings", "device_heartbeats"):
            _seed(conn, name, device_id=device["id"])
        _seed(
            conn,
            "diagnosis_episodes",
            device_id=device["id"],
            last_diagnosis_result_id=diagnosis["id"],
            failure_count=3,
            status="resolved",
            resolved_at=None,
        )
        _seed(
            conn,
            "guidance_history",
            device_id=device["id"],
            diagnosis_result_id=diagnosis["id"],
            failure_count=1,
        )

    def snapshot():
        with engine.connect() as conn:
            metadata = MetaData()
            metadata.reflect(bind=conn)
            return {
                name: list(conn.execute(select(obj)).mappings())
                for name, obj in metadata.tables.items()
            }

    before = snapshot()
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        report = audit_historical_integrity(db)
        db.rollback()
    assert snapshot() == before
    assert report["read_only"] is True
    assert report["schema_versions"] == [revision]
    assert secret not in json.dumps(report, ensure_ascii=False)
    reasons = [item["reason"] for item in report["findings"]]
    assert reasons.count("duplicate_draft_source") == 2
    assert reasons.count("missing_recorded_session") == 3
    assert "approved_draft_publication_count_mismatch" in reasons
    assert "missing_or_conflicting_recorded_scope" in reasons
    assert "guidance_failure_count_mismatch" in reasons
    assert "resolved_without_timestamp" in reasons
    if not revision.endswith("0029"):
        assert report["schema_finding_count"] == (13 if revision.endswith("0027") else 12)
        assert any(
            item["reason"] == "source_draft_unique_constraint_not_enabled"
            for item in report["schema_findings"]
        )
    else:
        assert {item["table"] for item in report["schema_findings"]} == {
            "experiment_sessions",
            "guidance_history",
            "intervention_cases",
            "ai_usage_reservations",
        }


def test_current_sqlite_inventory_accepts_read_only_connection(api_context):
    with api_context["session_factory"]() as db:
        db.execute(text("PRAGMA query_only = ON"))
        try:
            report = audit_historical_integrity(db)
            assert report["schema_findings"] == []
            assert report["read_only"] is True
        finally:
            db.execute(text("PRAGMA query_only = OFF"))
