"""Exercise real HTTP handlers and LangGraph; expected answers stay in the evaluator."""

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.evaluation.workflow_environment import DEVICE_KEY, workflow_environment
from app.models import AICallRecord, DiagnosisEvidence, DiagnosisFeedback, DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.models.knowledge import KnowledgeCase

DATA = Path(__file__).resolve().parents[2] / "evaluation"


def snapshot(env, workflow_id):
    graph = env.app.state.diagnosis_graph
    state = dict(
        graph.get_state({"configurable": {"thread_id": f"diagnosis:{workflow_id}"}}).values
    )
    with env.sessions() as db:
        workflow = db.get(DiagnosisWorkflowRun, workflow_id)
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
        evidence = list(
            db.scalars(
                select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == diagnosis.id)
            )
        )
        calls = list(
            db.scalars(select(AICallRecord).where(AICallRecord.workflow_run_id == workflow_id))
        )
        feedback = list(
            db.scalars(
                select(DiagnosisFeedback).where(
                    DiagnosisFeedback.diagnosis_result_id == diagnosis.id
                )
            )
        )
        reviews = list(
            db.scalars(
                select(DiagnosisWorkflowReview).where(
                    DiagnosisWorkflowReview.workflow_run_id == workflow_id
                )
            )
        )
        return {
            "workflow_id": workflow.id,
            "diagnosis_id": diagnosis.id,
            "session_id": workflow.experiment_session_id,
            "package_version_id": workflow.experiment_version_id,
            "package_hash": state.get("experiment_package_hash"),
            "status": workflow.status,
            "resume_count": workflow.resume_count,
            "errors": [r["error_type"] for r in diagnosis.matched_rules],
            "normal_assessment": diagnosis.context_snapshot.get("normal_assessment"),
            "evidence": [
                {
                    "id": e.id,
                    "diagnosis_id": e.diagnosis_id,
                    "version_id": e.experiment_version_id,
                    "type": e.evidence_type,
                    "source_type": e.source_type,
                    "source_ref": e.source_ref,
                    "value": e.normalized_value,
                }
                for e in evidence
            ],
            "state": {
                k: state.get(k)
                for k in (
                    "node_trace",
                    "node_metrics",
                    "rule_hits",
                    "fault_tree_candidates",
                    "reasoned_causes",
                    "reasoning_status",
                    "reasoning_mode",
                    "missing_evidence",
                    "allowed_verification_actions",
                    "knowledge_validation",
                    "ai_result",
                    "deterministic_result",
                    "attempt_count",
                )
            },
            "ai_audit": [
                {
                    "id": a.id,
                    "stage": a.call_stage,
                    "status": a.status,
                    "prompt_version": a.prompt_version,
                    "prompt_hash": a.prompt_hash,
                    "output": a.output_json,
                    "is_test_data": a.is_test_data,
                }
                for a in calls
            ],
            "feedback_ids": [f.id for f in feedback],
            "feedback_requests": [
                {
                    "id": f.id,
                    "request_id": f.request_id,
                    "session_id": f.experiment_session_id,
                    "processing_status": f.processing_status,
                    "action": f.action,
                    "note": f.note,
                }
                for f in feedback
            ],
            "review_ids": [r.id for r in reviews],
            "approved_knowledge_ids": list(
                db.scalars(
                    select(KnowledgeCase.id).where(KnowledgeCase.review_status == "approved")
                )
            ),
            "provider_calls": len(env.provider.calls),
            "is_test_data": workflow.is_test_data and diagnosis.is_test_data,
        }


def execute_case(case, postgres_dsn=None):
    result = {"id": case["id"], "input": case, "snapshots": [], "events": [], "action_results": []}
    with workflow_environment(case["package"], case.get("provider", "valid"), postgres_dsn) as env:
        now = datetime.now(timezone.utc).isoformat()
        records = case["records"]
        batch = {
            "protocolVersion": "1.0",
            "schemaVersion": "1",
            "requestId": str(uuid4()),
            "bootId": "workflow-evaluation",
            "sequenceNo": 1,
            "sentAt": now,
            "isTestData": True,
            "records": [{**r, "occurredAt": now} for r in records],
        }
        result["events"] = env.events
        result["package_hash"] = env.hashes[case["package"]]
        ingested = env.request("POST", "/api/v1/device/ingest", json=batch)
        if ingested.status_code != 201:
            result["execution_error"] = "ingest did not return 201"
            return result
        started = env.request(
            "POST",
            f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}",
            json={"lookback_seconds": 3600, "question": "请解释现有证据的限制，不能确认具体根因。"},
        )
        if started.status_code != 201:
            result["execution_error"] = "workflow start did not return 201"
            return result
        workflow_id = started.json()["id"]
        result["snapshots"].append(snapshot(env, workflow_id))
        last_feedback = None
        for action in case.get("actions", []):
            previous = result["snapshots"][-1]
            event_count = len(env.events)
            if action == "restart":
                env.restart_graph()
            elif action in {"resolved", "unresolved", "request_teacher_help"}:
                last_feedback = {
                    "request_id": str(uuid4()),
                    "action": action,
                    "note": "合成评测反馈",
                }
                env.request(
                    "POST",
                    f"/api/v1/student/diagnoses/{previous['diagnosis_id']}/feedback",
                    json=last_feedback,
                )
            elif action in {
                "repeat_feedback",
                "conflicting_feedback_action",
                "conflicting_feedback_note",
            }:
                if last_feedback is None:
                    raise ValueError("feedback replay requires a preceding feedback request")
                feedback = dict(last_feedback)
                if action == "conflicting_feedback_action":
                    feedback["action"] = "resolved"
                elif action == "conflicting_feedback_note":
                    feedback["note"] = "同一请求 ID 的不同内容"
                env.request(
                    "POST",
                    f"/api/v1/student/diagnoses/{previous['diagnosis_id']}/feedback",
                    json=feedback,
                )
            elif action in {
                "feedback_without_session",
                "feedback_without_request_id",
                "feedback_invalid_request_id",
            }:
                headers = dict(env.headers)
                feedback = {
                    "request_id": str(uuid4()),
                    "action": "unresolved",
                    "note": "合成缺字段探测",
                }
                if action == "feedback_without_session":
                    headers.pop("X-Experiment-Session-ID")
                elif action == "feedback_without_request_id":
                    feedback.pop("request_id")
                else:
                    feedback["request_id"] = "not-a-uuid"
                env.request(
                    "POST",
                    f"/api/v1/student/diagnoses/{previous['diagnosis_id']}/feedback",
                    headers=headers,
                    json=feedback,
                )
            elif action == "teacher_approve":
                from app.evaluation.workflow_environment import LOGIN_PASSWORD

                login = env.request(
                    "POST",
                    "/api/v1/auth/session",
                    json={"username": "synthetic-teacher", "password": LOGIN_PASSWORD},
                )
                env.request(
                    "POST",
                    f"/api/v1/diagnosis-workflows/{workflow_id}/review",
                    headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                    json={
                        "action": "approve",
                        "comment": "仅验证合成教师角色操作，不确认知识真实性",
                    },
                )
            elif action == "foreign_session_read":
                other = env.other_student_headers()
                env.request("GET", f"/api/v1/diagnosis-workflows/{workflow_id}", headers=other)
            elif action in {"foreign_session_feedback", "foreign_session_feedback_replay"}:
                other = env.other_student_headers()
                feedback = {
                    "request_id": str(uuid4()),
                    "action": "resolved",
                    "note": "另一学生的合成越权探测",
                }
                if action == "foreign_session_feedback_replay":
                    if last_feedback is None:
                        raise ValueError("foreign replay requires an existing owner request")
                    feedback = dict(last_feedback)
                env.request(
                    "POST",
                    f"/api/v1/student/diagnoses/{previous['diagnosis_id']}/feedback",
                    headers=other,
                    json=feedback,
                )
            elif action == "foreign_version":
                other = next(v for p, v in env.versions.items() if p != case["package"])
                env.request(
                    "POST",
                    f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}",
                    json={"experiment_version_id": other},
                )
            elif action == "read":
                env.request("GET", f"/api/v1/diagnosis-workflows/{workflow_id}")
            else:
                raise ValueError(f"unsupported evaluation action: {action}")
            result["action_results"].append(
                {
                    "action": action,
                    "status_code": env.events[-1]["status_code"]
                    if len(env.events) > event_count
                    else None,
                }
            )
            result["snapshots"].append(snapshot(env, workflow_id))
        result["mock_calls"] = env.provider.calls
    return result


def assess_case(actual, expected):
    checks = []

    def check(requirement, expected_value, actual_value):
        checks.append(
            {
                "requirement": requirement,
                "expected": expected_value,
                "actual": actual_value,
                "status": "passed" if expected_value == actual_value else "failed",
            }
        )

    snapshots = actual["snapshots"]
    check("execution_completed", None, actual.get("execution_error"))
    if not snapshots:
        return checks
    first, last = snapshots[0], snapshots[-1]
    check("rule_errors_exact", sorted(expected["errors"]), sorted(first["errors"]))
    check("status_sequence", expected["statuses"], [s["status"] for s in snapshots])
    if "action_http_statuses" in expected:
        check(
            "action_http_statuses",
            expected["action_http_statuses"],
            [a["status_code"] for a in actual["action_results"]],
        )
    check("normal_status", expected["normal"], (first["normal_assessment"] or {}).get("status"))
    check("test_provenance", True, all(s["is_test_data"] for s in snapshots))
    for index, s in enumerate(snapshots):
        prefix = f"snapshot_{index}"
        ids = {e["id"] for e in s["evidence"]}
        check(
            prefix + ".evidence_scope",
            True,
            all(
                e["diagnosis_id"] == s["diagnosis_id"]
                and e["version_id"] == s["package_version_id"]
                and str(UUID(e["id"])) == e["id"]
                for e in s["evidence"]
            ),
        )
        check(prefix + ".package_hash", actual["package_hash"], s["package_hash"])
        check(prefix + ".same_session", first["session_id"], s["session_id"])
        check(prefix + ".same_diagnosis", first["diagnosis_id"], s["diagnosis_id"])
        check(
            prefix + ".feedback_scope_persisted",
            True,
            all(f["session_id"] == s["session_id"] for f in s["feedback_requests"]),
        )
        request_ids = [f["request_id"] for f in s["feedback_requests"]]
        check(
            prefix + ".feedback_request_unique",
            True,
            len(request_ids) == len(set(request_ids))
            and all(str(UUID(request_id)) == request_id for request_id in request_ids),
        )
        check(
            prefix + ".feedback_applied",
            True,
            all(f["processing_status"] == "applied" for f in s["feedback_requests"]),
        )
        check(prefix + ".no_automatic_knowledge_approval", [], s["approved_knowledge_ids"])
        raw_ids = {r["id"] for r in actual["events"][0]["response"].get("records", [])}
        check(
            prefix + ".raw_source_traceable",
            True,
            all(
                e["source_ref"] in raw_ids
                for e in s["evidence"]
                if e["source_type"] != "rule_engine"
            ),
        )
        expected_nodes = [
            "context_builder",
            "rule_engine",
            "fault_tree_analyzer",
            "knowledge_context",
            "ai_reasoning",
            "knowledge_validation",
            "ai_explanation",
        ]
        check(prefix + ".pipeline_prefix", expected_nodes, (s["state"]["node_trace"] or [])[:7])
        ai_result = s["state"].get("ai_result")
        if ai_result:
            allowed_actions = {a["text"] for a in s["state"]["allowed_verification_actions"] or []}
            check(
                prefix + ".explanation_steps_allowed",
                True,
                set(ai_result["steps"]) <= allowed_actions,
            )
            check(
                prefix + ".ai_error_preserved",
                True,
                ai_result["error_type"] in s["errors"]
                or (not s["errors"] and ai_result["error_type"] == "UNCLASSIFIED_ANOMALY"),
            )
        candidates = {c["cause_id"] for c in s["state"]["fault_tree_candidates"] or []}
        check(
            prefix + ".candidate_membership",
            True,
            all(c["cause_id"] in candidates for c in s["state"]["reasoned_causes"] or []),
        )
        check(
            prefix + ".evidence_references",
            True,
            all(set(c["used_evidence_ids"]) <= ids for c in s["state"]["reasoned_causes"] or []),
        )
        candidate_refs = {
            c["cause_id"]: set(c.get("evidence_refs", []))
            for c in s["state"]["fault_tree_candidates"] or []
        }
        check(
            prefix + ".reasoning_uses_candidate_evidence",
            True,
            all(
                set(c["used_evidence_ids"]) <= candidate_refs.get(c["cause_id"], set())
                for c in s["state"]["reasoned_causes"] or []
            ),
        )
        stages = [a["stage"] for a in s["ai_audit"]]
        check(prefix + ".audit_stage_unique", True, len(stages) == len(set(stages)))
    if expected.get("reasoning"):
        check("reasoning_status", expected["reasoning"], first["state"]["reasoning_status"])
        if expected["reasoning"] == "unknown":
            check("unknown_has_no_ranked_causes", [], first["state"]["reasoned_causes"])
    if expected.get("reasoning_mode"):
        check("reasoning_mode", expected["reasoning_mode"], first["state"]["reasoning_mode"])
        check(
            "reasoning_audit_status",
            expected["reasoning_audit_status"],
            next((a["status"] for a in first["ai_audit"] if a["stage"] == "reasoning"), None),
        )
    if expected.get("candidate_evidence_types"):
        allowed = {
            e["id"] for e in first["evidence"] if e["type"] in expected["candidate_evidence_types"]
        }
        refs = [c["evidence_refs"] for c in first["state"]["fault_tree_candidates"] or []]
        check(
            "candidate_refs_support_the_triggering_anomaly",
            True,
            bool(refs) and all(bool(r) and set(r) <= allowed for r in refs),
        )
    if "minimum_mock_calls" in expected:
        check("provider_exercised", True, first["provider_calls"] >= expected["minimum_mock_calls"])
    if expected.get("no_physical_light"):
        check(
            "no_fabricated_optical_evidence",
            False,
            "observation.led_physically_on" in {e["type"] for e in first["evidence"]},
        )
    if "final_http_status" in expected:
        check(
            "final_http_status", expected["final_http_status"], actual["events"][-1]["status_code"]
        )
    if expected.get("last_action_no_side_effects"):
        before = snapshots[-2]
        for key in (
            "feedback_ids",
            "feedback_requests",
            "review_ids",
            "resume_count",
            "provider_calls",
            "state",
            "ai_audit",
            "evidence",
            "status",
        ):
            check("no_side_effects." + key, before[key], last[key])
    if expected.get("feedback_replayed_exactly"):
        feedback_events = [e for e in actual["events"] if e["path"].endswith("/feedback")]
        before, after = feedback_events[-2:]
        for key in ("request", "status_code", "response"):
            check("feedback_replay." + key, before[key], after[key])
    if expected.get("new_feedback_attempt"):
        before = snapshots[-2]
        check(
            "new_attempt.feedback_count", len(before["feedback_ids"]) + 1, len(last["feedback_ids"])
        )
        check("new_attempt.resume_count", before["resume_count"] + 1, last["resume_count"])
        check(
            "new_attempt.attempt_count",
            before["state"]["attempt_count"] + 1,
            last["state"]["attempt_count"],
        )
        check(
            "new_attempt.provider_called", True, last["provider_calls"] > before["provider_calls"]
        )
        feedback_events = [e for e in actual["events"] if e["path"].endswith("/feedback")]
        check(
            "new_attempt.distinct_request_id",
            True,
            feedback_events[-1]["request"]["request_id"]
            != feedback_events[-2]["request"]["request_id"],
        )
    if expected.get("restart_preserves_state"):
        index = actual["input"]["actions"].index("restart")
        before, after = snapshots[index : index + 2]
        for key in (
            "workflow_id",
            "diagnosis_id",
            "package_version_id",
            "evidence",
            "ai_audit",
            "provider_calls",
            "state",
        ):
            check("restart." + key, before[key], after[key])
    return checks


def run_workflow_evaluation(*, postgres_dsn=None):
    cases = json.loads((DATA / "workflow_inputs.json").read_text())
    expectations = json.loads((DATA / "workflow_expectations.json").read_text())
    identifiers = [case["id"] for case in cases]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(expectations):
        raise ValueError("evaluation inputs and expectations must match one-to-one")
    report = {
        "version": "workflow-evaluation-v2-remediation",
        "is_test_data": True,
        "database": "postgresql_isolated_schema" if postgres_dsn else "sqlite_memory",
        "real_provider_calls": 0,
        "semantic_review": "not_run",
        "hardware_validation": "not_run",
        "cases": [],
    }
    report["fixture_hashes"] = {
        name: hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        for name in ("workflow_inputs.json", "workflow_expectations.json")
    }
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    repo = Path(__file__).resolve().parents[3]
    report["git_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    report["worktree_dirty"] = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout
    )
    report["code_hashes"] = {
        str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((repo / "backend/app").rglob("*.py"))
    }
    for case in cases:
        if "restart" in case.get("actions", []) and not postgres_dsn:
            report["cases"].append(
                {
                    "id": case["id"],
                    "status": "not_run",
                    "reason": "requires isolated PostgreSQL",
                    "checks": [],
                }
            )
            continue
        try:
            actual = execute_case(case, postgres_dsn)
            actual["checks"] = assess_case(actual, expectations[case["id"]])
            actual["status"] = (
                "passed" if all(c["status"] == "passed" for c in actual["checks"]) else "failed"
            )
        except Exception as exc:
            # Do not export exception messages which may contain a DSN or credentials.
            actual = {
                "id": case["id"],
                "status": "error",
                "error_type": type(exc).__name__,
                "checks": [],
            }
        report["cases"].append(actual)
    report["counts"] = dict(Counter(c["status"] for c in report["cases"]))
    report["status"] = (
        "failed"
        if any(c["status"] in {"failed", "error"} for c in report["cases"])
        else "incomplete"
        if any(c["status"] == "not_run" for c in report["cases"])
        else "passed"
    )
    return report
