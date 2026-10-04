from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from shared_student_authorization import demo_student_actor
from sqlalchemy import func, select
from test_diagnosis_workflow import _add_failure_log, _settings

from app.ai.context_contract import (
    APPLICABILITY_PROJECTION_VERSION,
    CONTEXT_CONTRACT_VERSION,
    CONTEXT_POLICY_VERSION,
)
from app.ai.diagnosis_graph import build_diagnosis_graph
from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
from app.models import AICallRecord, Device, DiagnosisResult
from app.services.diagnosis_workflow import serialize_workflow, start_workflow


def policy_snapshot(current):
    return {"context_manifest": {
        "contract_version": CONTEXT_CONTRACT_VERSION,
        "policy_version": CONTEXT_POLICY_VERSION if current else "whole-unit-v1",
        "applicability_projection_version": APPLICABILITY_PROJECTION_VERSION if current else None,
        "required_complete": True,
    }}


@pytest.fixture
def advice_task(api_context, monkeypatch):
    _add_failure_log(api_context)
    with api_context["session_factory"]() as db:
        workflow = start_workflow(
            db, build_diagnosis_graph(InMemorySaver()), db.scalar(select(Device)), _settings(),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
         student_actor=demo_student_actor(db, db.scalar(select(Device))))
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)

        def forbid_provider(*args, **kwargs):
            raise AssertionError("read-only current advice must never construct a provider")

        monkeypatch.setattr("app.ai.clients.build_ai_client", forbid_provider)
        yield db, diagnosis, workflow


def add_call(db, diagnosis, workflow, stage="explanation", *, current=False):
    record = db.scalar(select(AICallRecord).where(
        AICallRecord.workflow_run_id == workflow.id, AICallRecord.call_stage == stage,
    ))
    if record is None:
        record = AICallRecord(
            diagnosis_result_id=diagnosis.id, workflow_run_id=workflow.id, call_stage=stage,
            transport="mock", prompt_version="fixture", prompt_hash="a" * 64,
            status="succeeded", attempt_count=1, duration_ms=1, input_snapshot={},
            is_test_data=True,
        )
        db.add(record)
    record.status = "succeeded"
    record.input_snapshot = policy_snapshot(current)
    record.output_json = {"summary": "model explanation"}
    if current and stage.startswith("reasoning"):
        record.output_json = {"error_type": "SENSOR_READ_FAILED", "conclusion": "unknown",
                              "ranked_causes": [], "summary": "model reasoning"}
    if current and stage.startswith("explanation"):
        from app.ai.output_contract import OUTPUT_CONTRACT_VERSION
        record.output_json = {
            "summary": "model explanation", "error_type": "SENSOR_READ_FAILED",
            "evidence": [], "possible_causes": [], "steps": ["检查供电"],
            "hint_level": 1, "need_teacher_help": False, "limitations": [],
        }
        record.input_snapshot = {
            **record.input_snapshot,
            "output_contract": {"version": OUTPUT_CONTRACT_VERSION,
                                "summary": "server summary", "limitations": [],
                                "allowed_causes": [],
                                "allowed_steps": ["检查供电"]},
        }
    db.flush()
    return record


def make_ai_result(db, diagnosis, workflow, *, current=False, suffix="", reasoning=True):
    record = add_call(db, diagnosis, workflow, "explanation" + suffix, current=current)
    if reasoning:
        add_call(db, diagnosis, workflow, "reasoning" + suffix, current=current)
    diagnosis.ai_enhancement = {"status": "cloud_success", "call_record_id": record.id}
    workflow.final_result = {
        "summary": "OLD MODEL PRIVATE RESULT", "error_type": "SENSOR_READ_FAILED",
        "possible_causes": [{"cause": "OLD MODEL PRIVATE CAUSE"}],
        "steps": ["OLD MODEL PRIVATE ACTION"], "limitations": [],
        "ai_reasoning": {"mode": "ai" if reasoning else "deterministic_fallback",
                         "summary": "OLD MODEL PRIVATE REASONING"},
        "knowledge_references": [{"case_id": "old-unproven-case"}],
        "candidate_causes": [{"cause_id": "OLD MODEL PRIVATE CANDIDATE"}],
        "rule_hits": deepcopy(diagnosis.matched_rules), "rules_preserved": True,
        "evidence": deepcopy(diagnosis.evidence), "evidence_score": workflow.evidence_score,
        "hint_level": workflow.guidance_level, "guidance_level": workflow.guidance_level,
        "need_teacher_help": workflow.needs_teacher, "teacher_reviewed": False,
        "context_delivery": {"explanation_call_id": record.id},
    }
    workflow.review_request = None
    db.commit()
    return record


def test_legacy_current_result_falls_back_without_mutating_history(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    old_result, old_core = deepcopy(workflow.final_result), deepcopy(diagnosis.deterministic_core)
    call_count = db.scalar(select(func.count(AICallRecord.id)))
    response = serialize_workflow(workflow, audience="student")
    assert "OLD MODEL" not in str(response.final_result)
    assert response.final_result["context_policy_status"] == "legacy_enhancement_not_revalidated"
    assert response.final_result["rule_hits"] == diagnosis.matched_rules
    assert response.final_result["hint_level"] == workflow.guidance_level
    assert response.status == workflow.status
    assert workflow.final_result == old_result
    assert diagnosis.deterministic_core == old_core
    assert not db.dirty
    assert db.scalar(select(func.count(AICallRecord.id))) == call_count
    db.expire_all()
    assert workflow.final_result == old_result


def test_waiting_feedback_does_not_resurface_old_ai_interrupt(advice_task):
    db, diagnosis, workflow = advice_task
    request = deepcopy(workflow.review_request)
    make_ai_result(db, diagnosis, workflow)
    request.update(ai_result=deepcopy(workflow.final_result),
                   next_verification_action="OLD MODEL PRIVATE ACTION")
    workflow.final_result = None
    workflow.review_request = request
    db.commit()
    response = serialize_workflow(workflow, audience="student")
    assert response.review_request["ai_result"] is None
    assert response.review_request["next_verification_action"] is None
    assert response.review_request["deterministic_result"]
    assert "OLD MODEL" not in str(response.review_request)
    assert workflow.review_request == request
    assert not db.dirty


def test_current_bound_calls_keep_current_result(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    original = deepcopy(workflow.final_result)
    current = serialize_workflow(workflow, audience="student").final_result
    assert current["summary"] == "server summary"
    assert current["ai_reasoning"]["summary"] != "OLD MODEL PRIVATE REASONING"
    assert current["steps"] == original["steps"]
    assert workflow.final_result == original
    assert not db.dirty


def test_pure_rules_without_successful_ai_are_preserved(advice_task):
    db, diagnosis, workflow = advice_task
    original = deepcopy(workflow.review_request)
    assert serialize_workflow(workflow, audience="student").review_request == original
    assert not db.dirty


def test_new_feedback_pair_does_not_get_blocked_by_old_initial_calls(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    make_ai_result(db, diagnosis, workflow, current=True, suffix=":feedback:unresolved-one")
    # A later resolved feedback does not generate another provider stage.
    workflow.final_result = {**workflow.final_result,
                             "student_feedback": {"id": "resolved-later", "action": "resolved"}}
    db.commit()
    original = deepcopy(workflow.final_result)
    current = serialize_workflow(workflow, audience="student").final_result
    assert current["summary"] == "server summary"
    assert current["ai_reasoning"]["summary"] != "OLD MODEL PRIVATE REASONING"
    assert current["steps"] == original["steps"]
    assert workflow.final_result == original


def test_unrelated_current_feedback_record_cannot_revalidate_old_bound_output(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    add_call(db, diagnosis, workflow, "explanation:feedback:other", current=True)
    add_call(db, diagnosis, workflow, "reasoning:feedback:other", current=True)
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)


@pytest.mark.parametrize("mutation", ["missing", "different_workflow", "wrong_stage", "incomplete"])
def test_unverifiable_explanation_binding_falls_back(advice_task, mutation):
    db, diagnosis, workflow = advice_task
    call = make_ai_result(db, diagnosis, workflow, current=True)
    if mutation == "missing":
        workflow.final_result = {
            **workflow.final_result, "context_delivery": {"explanation_call_id": "not-recorded"},
        }
    elif mutation == "different_workflow":
        call.workflow_run_id = None
    elif mutation == "wrong_stage":
        call.call_stage = "case_polish"
    else:
        snapshot = deepcopy(call.input_snapshot)
        snapshot["context_manifest"]["required_complete"] = False
        call.input_snapshot = snapshot
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)


def test_current_explanation_does_not_hide_old_paired_reasoning(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    add_call(db, diagnosis, workflow, "reasoning", current=False)
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)


def test_missing_success_records_with_ai_marker_fail_closed(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    for call in db.scalars(select(AICallRecord).where(AICallRecord.workflow_run_id == workflow.id)):
        db.delete(call)
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)


def test_pure_deterministic_teacher_edit_is_preserved(advice_task):
    db, diagnosis, workflow = advice_task
    workflow.final_result = {
        **deepcopy(diagnosis.deterministic_explanation),
        "summary": "教师依据确定性资料编辑的说明", "teacher_reviewed": True,
        "ai_reasoning": {"mode": "deterministic_fallback"},
    }
    workflow.review_request = None
    db.commit()
    current = serialize_workflow(workflow).final_result
    assert current["summary"] == workflow.final_result["summary"]
    assert current["teacher_reviewed"] is True
    assert current["ai_reasoning"]["mode"] == "deterministic_fallback"


def test_legacy_ai_teacher_edit_remains_history_not_new_review(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    workflow.final_result = {**workflow.final_result, "teacher_reviewed": True}
    db.commit()
    response = serialize_workflow(workflow)
    assert response.final_result["historical_teacher_reviewed"] is True
    assert response.final_result["teacher_reviewed"] is False
    assert workflow.final_result["teacher_reviewed"] is True


def test_student_latest_http_uses_current_projection(advice_task, api_context):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    response = api_context["client"].get(
        f"/api/v1/diagnosis-workflows/devices/{workflow.device.device_key}/latest",
        headers=api_context["headers"],
    )
    assert response.status_code == 200
    assert "OLD MODEL" not in str(response.json()["final_result"])
    db.expire_all()
    assert "OLD MODEL" in str(workflow.final_result)


def test_new_feedback_commit_does_not_rebind_old_frozen_workflow_result(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow)
    original = deepcopy(workflow.final_result)
    later = add_call(db, diagnosis, workflow, "explanation:feedback:later", current=True)
    add_call(db, diagnosis, workflow, "reasoning:feedback:later", current=True)
    diagnosis.ai_enhancement = {"status": "cloud_success", "call_record_id": later.id}
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)
    assert workflow.final_result == original


def test_missing_frozen_binding_cannot_use_current_diagnosis_latest(advice_task):
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    original = deepcopy(workflow.final_result)
    original.pop("context_delivery")
    workflow.final_result = original
    db.commit()
    assert "OLD MODEL" not in str(serialize_workflow(workflow, audience="student").final_result)
    assert workflow.final_result == original


def test_current_waiting_snapshot_uses_its_frozen_binding(advice_task):
    db, diagnosis, workflow = advice_task
    request = deepcopy(workflow.review_request)
    call = make_ai_result(db, diagnosis, workflow, current=True)
    request.update(ai_result=deepcopy(workflow.final_result),
                   context_delivery={"explanation_call_id": call.id})
    workflow.final_result = None
    workflow.review_request = request
    diagnosis.ai_enhancement = {"status": "failed_fallback", "call_record_id": "later-missing"}
    db.commit()
    current = serialize_workflow(workflow, audience="student").review_request
    assert current["ai_result"]["summary"] == "server summary"
    assert current["ai_result"]["steps"] == request["ai_result"]["steps"]
    assert workflow.review_request == request


def test_result_and_interrupt_bindings_are_checked_independently(advice_task):
    db, diagnosis, workflow = advice_task
    request = deepcopy(workflow.review_request)
    old = make_ai_result(db, diagnosis, workflow)
    request.update(ai_result=deepcopy(workflow.final_result),
                   context_delivery={"explanation_call_id": old.id})
    make_ai_result(db, diagnosis, workflow, current=True, suffix=":feedback:later")
    workflow.review_request = request
    db.commit()
    response = serialize_workflow(workflow, audience="student")
    assert response.final_result["summary"] == "server summary"
    assert response.final_result["steps"] == workflow.final_result["steps"]
    assert workflow.final_result["summary"] == "OLD MODEL PRIVATE RESULT"
    assert response.review_request["ai_result"] is None


def test_current_projection_preserves_persisted_teacher_edit(advice_task):
    from app.models.base import utc_now
    from app.models.classroom import User
    from app.models.diagnosis_workflow import DiagnosisWorkflowReview
    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    workflow.final_result = {**workflow.final_result, 'summary': '教师已核对的编辑意见',
                             'teacher_reviewed': True}
    db.add(DiagnosisWorkflowReview(workflow_run_id=workflow.id,
           reviewer_user_id=db.scalar(select(User.id)), action='edit',
           edited_result={'summary': '教师已核对的编辑意见'}, created_at=utc_now()))
    db.commit()
    original = deepcopy(workflow.final_result)
    current = serialize_workflow(workflow, audience='student').final_result
    assert current['summary'] == '教师已核对的编辑意见'
    assert current['ai_reasoning']['summary'] != 'OLD MODEL PRIVATE REASONING'
    assert workflow.final_result == original
    assert not db.dirty


def test_skipped_explanation_keeps_paired_licensed_reasoning_action(advice_task):
    from app.services.current_advice import project_current_advice

    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    anchor = db.scalar(select(AICallRecord).where(
        AICallRecord.workflow_run_id == workflow.id, AICallRecord.call_stage == 'explanation',
    ))
    anchor.status = 'skipped'
    anchor.output_json = None
    anchor.error_code = 'INPUT_TOKEN_LIMIT'
    paired = db.scalar(select(AICallRecord).where(
        AICallRecord.workflow_run_id == workflow.id, AICallRecord.call_stage == 'reasoning',
    ))
    paired.input_snapshot = {**paired.input_snapshot,
                             'allowed_verification_actions': [{'text': '核对配置记录'}]}
    workflow.final_result = {**workflow.final_result,
                             'provenance': 'rules_and_reviewed_knowledge',
                             'ai_reasoning': {'mode': 'ai', 'status': 'unknown',
                                              'next_verification_action': '核对配置记录'}}
    db.commit()
    original = deepcopy(workflow.final_result)
    for _ in range(2):
        final, _ = project_current_advice(db, workflow)
        assert final['ai_reasoning']['next_verification_action'] == '核对配置记录'
        assert final['ai_reasoning']['verification_requests'][0]['source'] == 'rules'
        assert final['ai_reasoning']['reported_evidence']
        assert workflow.final_result == original


def test_waiting_workflow_exposes_source_reports_without_final_result(advice_task):
    db, diagnosis, workflow = advice_task
    workflow.final_result = None
    db.commit()
    response = serialize_workflow(workflow, audience='student')
    assert response.final_result is None
    assert response.reported_evidence
    ids = {row['id'] for row in response.reported_evidence}
    from app.models import DiagnosisEvidence
    expected_ids = set(db.scalars(select(DiagnosisEvidence.id).where(
        DiagnosisEvidence.diagnosis_id == diagnosis.id)))
    assert ids == expected_ids
