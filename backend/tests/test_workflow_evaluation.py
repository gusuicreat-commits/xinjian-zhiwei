"""Acceptance fails on regressions; neither known failures nor missing coverage is green."""

import copy
import json
import os

import pytest

from app.evaluation.workflow_runner import DATA, assess_case, execute_case, run_workflow_evaluation

INPUTS = json.loads((DATA / "workflow_inputs.json").read_text())
EXPECTED = json.loads((DATA / "workflow_expectations.json").read_text())


@pytest.fixture(scope="module")
def workflow_report():
    return run_workflow_evaluation()


@pytest.mark.parametrize(
    "case_id",
    [c["id"] for c in INPUTS if "restart" not in c["actions"]],
)
def test_workflow_acceptance(workflow_report, case_id):
    case = next(c for c in workflow_report["cases"] if c["id"] == case_id)
    assert case["status"] == "passed", [c for c in case["checks"] if c["status"] != "passed"]


def test_missing_postgres_coverage_does_not_become_a_green_report(workflow_report):
    assert workflow_report["status"] == "incomplete"
    assert not [c for c in workflow_report["cases"] if c["status"] in {"failed", "error"}]
    assert {c["id"] for c in workflow_report["cases"] if c["status"] == "not_run"} == {
        c["id"] for c in INPUTS if "restart" in c["actions"]
    }
    assert workflow_report["real_provider_calls"] == 0
    assert workflow_report["semantic_review"] == "not_run"


@pytest.mark.parametrize(
    "mutation,failed_requirement",
    [
        ("foreign_evidence", "snapshot_0.evidence_references"),
        ("extra_error", "rule_errors_exact"),
        ("unlisted_step", "snapshot_0.explanation_steps_allowed"),
        ("wrong_package", "snapshot_0.package_hash"),
        ("automatic_approval", "snapshot_0.no_automatic_knowledge_approval"),
        ("unrelated_evidence", "snapshot_0.reasoning_uses_candidate_evidence"),
    ],
)
def test_workflow_evaluator_rejects_mutated_outputs(workflow_report, mutation, failed_requirement):
    case = copy.deepcopy(next(c for c in workflow_report["cases"] if c["id"] == "dht-valid"))
    s = case["snapshots"][0]
    if mutation == "foreign_evidence":
        s["state"]["reasoned_causes"][0]["used_evidence_ids"] = ["not-this-diagnosis"]
    elif mutation == "extra_error":
        s["errors"].append("FABRICATED_ERROR")
    elif mutation == "unlisted_step":
        s["state"]["ai_result"]["steps"] = ["invented step"]
    elif mutation == "wrong_package":
        s["package_hash"] = "other-package"
    elif mutation == "automatic_approval":
        s["approved_knowledge_ids"] = ["unreviewed-case"]
    else:
        cause = s["state"]["reasoned_causes"][0]
        linked = next(
            c["evidence_refs"]
            for c in s["state"]["fault_tree_candidates"]
            if c["cause_id"] == cause["cause_id"]
        )
        cause["used_evidence_ids"] = [next(e["id"] for e in s["evidence"] if e["id"] not in linked)]
    checks = assess_case(case, EXPECTED["dht-valid"])
    assert next(c for c in checks if c["requirement"] == failed_requirement)["status"] == "failed"


def test_report_does_not_export_auth_credentials(workflow_report):
    from app.evaluation.workflow_environment import DEVICE_TOKEN, LOGIN_PASSWORD

    serialized = json.dumps(workflow_report)
    assert DEVICE_TOKEN not in serialized
    assert LOGIN_PASSWORD not in serialized
    assert '"access_token"' not in serialized


@pytest.mark.parametrize(
    "case_id,mutation,requirement",
    [
        ("duplicate-feedback", "provider_call", "no_side_effects.provider_calls"),
        ("duplicate-feedback", "replay_response", "feedback_replay.response"),
        ("foreign-session-feedback", "accepted", "action_http_statuses"),
    ],
)
def test_feedback_regression_cannot_become_a_green_report(
    workflow_report, tmp_path, monkeypatch, case_id, mutation, requirement
):
    from app.evaluation import workflow_runner

    actual = copy.deepcopy(next(c for c in workflow_report["cases"] if c["id"] == case_id))
    if mutation == "provider_call":
        actual["snapshots"][-1]["provider_calls"] += 1
    elif mutation == "replay_response":
        actual["events"][-1]["response"] = {"invented": "different replay response"}
    else:
        actual["action_results"][-1]["status_code"] = 201
    (tmp_path / "workflow_inputs.json").write_text(json.dumps([actual["input"]]))
    (tmp_path / "workflow_expectations.json").write_text(json.dumps({case_id: EXPECTED[case_id]}))
    monkeypatch.setattr(workflow_runner, "DATA", tmp_path)
    monkeypatch.setattr(workflow_runner, "execute_case", lambda *_: actual)
    report = workflow_runner.run_workflow_evaluation()
    assert report["status"] == "failed"
    assert report["cases"][0]["status"] == "failed"
    assert (
        next(c for c in report["cases"][0]["checks"] if c["requirement"] == requirement)["status"]
        == "failed"
    )


@pytest.mark.parametrize("case_id", [c["id"] for c in INPUTS if "restart" in c["actions"]])
def test_actual_workflow_restores_from_postgres_connections(case_id):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN is not configured; actual workflow restart not run")
    case = next(c for c in INPUTS if c["id"] == case_id)
    actual = execute_case(case, postgres_dsn=dsn)
    checks = assess_case(actual, EXPECTED[case["id"]])
    assert all(c["status"] == "passed" for c in checks), checks
