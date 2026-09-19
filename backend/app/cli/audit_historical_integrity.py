"""Read-only inventory of records requiring human review; no private text output."""

import argparse
import json

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

# Reflection deliberately avoids ORM columns introduced after the inspected database.
_NEW_COLUMNS = {
    "device_logs": "experiment_session_id",
    "sensor_readings": "experiment_session_id",
    "device_heartbeats": "experiment_session_id",
    "knowledge_cases": "source_draft_id",
    "knowledge_case_drafts": "version_no",
    "diagnosis_results": "episode_evidence_revision",
    "diagnosis_episodes": "evidence_revision",
}


def audit_historical_integrity(db: Session) -> dict:
    findings = []
    schema_findings = []
    with db.no_autoflush:
        connection = db.connection()
        inspector = inspect(connection)
        names = set(inspector.get_table_names())
        metadata = MetaData()

        def table(name):
            if name not in names:
                return None
            if name not in metadata.tables:
                Table(name, metadata, autoload_with=connection, resolve_fks=False)
            return metadata.tables[name]

        def rows(name, *columns):
            obj = table(name)
            if obj is None:
                return []
            selected = [obj.c[col] for col in columns if col in obj.c]
            return list(connection.execute(select(*selected)).mappings())

        def add(name, record_id, reason):
            findings.append({"table": name, "record_id": record_id, "reason": reason})

        for name, column in [*_NEW_COLUMNS.items(), ("diagnosis_results", "episode_id")]:
            obj = table(name)
            if obj is None or column not in obj.c:
                schema_findings.append(
                    {"table": name, "column": column, "reason": "new_column_not_enabled"}
                )
        if "knowledge_cases" not in names or not any(
            item.get("column_names") == ["source_draft_id"]
            for item in inspector.get_unique_constraints("knowledge_cases")
        ):
            schema_findings.append(
                {"table": "knowledge_cases", "reason": "source_draft_unique_constraint_not_enabled"}
            )

        for name in ("device_logs", "sensor_readings", "device_heartbeats"):
            for row in rows(name, "id", "experiment_session_id"):
                if row.get("experiment_session_id") is None:
                    add(name, row["id"], "missing_recorded_session")
        cases_by_source = {}
        for case in rows("knowledge_cases", "id", "source_draft_id", "source_ref"):
            source = case.get("source_draft_id")
            if source is None and (case["source_ref"] or "").startswith("diagnosis-case-draft:"):
                source = case["source_ref"].removeprefix("diagnosis-case-draft:")
                add("knowledge_cases", case["id"], "legacy_draft_source_not_linked")
            if source:
                cases_by_source.setdefault(source, []).append(case["id"])
        for case_ids in cases_by_source.values():
            if len(case_ids) > 1:
                for case_id in case_ids:
                    add("knowledge_cases", case_id, "duplicate_draft_source")
        for draft in rows("knowledge_case_drafts", "id", "status"):
            if draft["status"] == "approved" and len(cases_by_source.get(draft["id"], [])) != 1:
                add(
                    "knowledge_case_drafts",
                    draft["id"],
                    "approved_draft_publication_count_mismatch",
                )

        sessions = {
            row["id"]: row
            for row in rows(
                "experiment_sessions",
                "id",
                "student_user_id",
                "device_id",
                "experiment_assignment_id",
            )
        }
        assignments = {row["id"]: row for row in rows("experiment_assignments", "id", "class_id")}
        workflows = {}
        for row in rows(
            "diagnosis_workflow_runs",
            "diagnosis_result_id",
            "experiment_session_id",
            "student_user_id",
            "device_id",
        ):
            workflows.setdefault(row["diagnosis_result_id"], []).append(row)
        owners = {}
        for diagnosis in rows(
            "diagnosis_results",
            "id",
            "device_id",
            "context_snapshot",
            "matched_rules",
            "episode_id",
            "episode_evidence_revision",
        ):
            scopes = [
                tuple(row[key] for key in ("experiment_session_id", "student_user_id", "device_id"))
                for row in workflows.get(diagnosis["id"], [])
            ]
            snapshot = diagnosis["context_snapshot"]
            recorded = snapshot.get("feedback_scope") if isinstance(snapshot, dict) else None
            invalid = recorded is not None and not isinstance(recorded, dict)
            if isinstance(recorded, dict):
                scopes.append(
                    tuple(
                        recorded.get(key)
                        for key in ("experiment_session_id", "student_user_id", "device_id")
                    )
                )
            owner = sessions.get(scopes[0][0]) if scopes else None
            if (
                invalid
                or not scopes
                or any(scope != scopes[0] for scope in scopes)
                or owner is None
                or owner["student_user_id"] != scopes[0][1]
                or owner["device_id"] != scopes[0][2]
                or diagnosis["device_id"] != scopes[0][2]
                or owner["experiment_assignment_id"] not in assignments
            ):
                owner = None
                add("diagnosis_results", diagnosis["id"], "missing_or_conflicting_recorded_scope")
            owners[diagnosis["id"]] = owner
            if diagnosis["matched_rules"] and diagnosis.get("episode_id") is None:
                add("diagnosis_results", diagnosis["id"], "missing_episode_ownership")
            if diagnosis.get("episode_id") and diagnosis.get("episode_evidence_revision") is None:
                add("diagnosis_results", diagnosis["id"], "missing_evidence_revision")
        for case in rows("intervention_cases", "id", "diagnosis_result_id", "class_id"):
            owner = owners.get(case["diagnosis_result_id"])
            if owner is None:
                add("intervention_cases", case["id"], "missing_recorded_diagnosis_scope")
            elif assignments[owner["experiment_assignment_id"]]["class_id"] != case["class_id"]:
                add("intervention_cases", case["id"], "conflicting_class_scope")
        histories = {}
        for row in rows("guidance_history", "diagnosis_result_id", "failure_count"):
            histories.setdefault(row["diagnosis_result_id"], []).append(row["failure_count"])
        for episode in rows(
            "diagnosis_episodes",
            "id",
            "last_diagnosis_result_id",
            "failure_count",
            "status",
            "resolved_at",
        ):
            counts = histories.get(episode["last_diagnosis_result_id"], [])
            if counts and max(counts) != episode["failure_count"]:
                add("diagnosis_episodes", episode["id"], "guidance_failure_count_mismatch")
            if episode["status"] == "resolved" and episode["resolved_at"] is None:
                add("diagnosis_episodes", episode["id"], "resolved_without_timestamp")
        versions = [row["version_num"] for row in rows("alembic_version", "version_num")]
    findings.sort(key=lambda item: (item["table"], item["record_id"], item["reason"]))
    return {
        "read_only": True,
        "schema_versions": sorted(versions),
        "schema_finding_count": len(schema_findings),
        "schema_findings": schema_findings,
        "finding_count": len(findings),
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", help="Optional explicit database; defaults to configured DB"
    )
    args = parser.parse_args()
    engine = create_engine(args.database_url or get_settings().database_url)
    try:
        with Session(engine) as db:
            if engine.dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
            elif engine.dialect.name == "sqlite":
                db.execute(text("PRAGMA query_only = ON"))
            report = audit_historical_integrity(db)
            db.rollback()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
