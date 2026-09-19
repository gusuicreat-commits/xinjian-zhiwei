from datetime import timedelta
from uuid import uuid4

from app.knowledge.case_drafting import approve_case_draft, withdraw_case
from app.models import DiagnosisResult, User
from app.models.base import utc_now

pytest_plugins = ["test_knowledge_case_drafting"]


def test_outside_candidate_confirmation_is_preserved_pending_a_new_package(persisted_draft):
    db, draft = persisted_draft
    original = db.get(DiagnosisResult, draft.diagnosis_result_id)
    now = utc_now() + timedelta(seconds=1)
    recovery = DiagnosisResult(
        device_id=original.device_id,
        evaluated_at=now,
        ruleset_version=original.ruleset_version,
        ruleset_hash=original.ruleset_hash,
        input_fingerprint="3" * 64,
        experiment_id=original.experiment_id,
        matched_rules=[],
        evidence=[],
        is_test_data=True,
        context_snapshot={
            **original.context_snapshot,
            "normal_assessment": {"status": "normal", "checks": [{"status": "satisfied"}]},
            "observations": [{"id": "fresh-observation", "observed_at": now.isoformat()}],
        },
    )
    db.add(recovery)
    draft.status = "pending_review"
    db.commit()
    actor = db.query(User).first()
    case = approve_case_draft(
        db,
        draft,
        case_id="new-cause-case",
        reviewer_ref=actor.id,
        confirmed_root_cause="new-teacher-observed-cause",
        final_solution_steps=["合成修复动作"],
        confirmation_note="合成教师核验材料",
        confirmation_material={
            "method": "controlled_test",
            "finding": "合成对照显示新的原因",
            "recovery_diagnosis_id": recovery.id,
            "applicability_limits": "仅限合成环境",
        },
    )
    assert case.review_status == "pending"
    assert case.solution_record["requires_new_package"]
    assert case.root_cause_value == "new-teacher-observed-cause"
    assert case.is_test_data and case.source_type == "controlled_test"
    request_id = str(uuid4())
    first = withdraw_case(
        db, case, actor, request_id=request_id, expected_version=case.version, reason="撤回合成材料"
    )
    assert (
        withdraw_case(
            db,
            case,
            actor,
            request_id=request_id,
            expected_version=case.version,
            reason="撤回合成材料",
        )
        == first
    )
    assert case.review_status == "withdrawn"
    assert case.root_cause_value == "new-teacher-observed-cause"
