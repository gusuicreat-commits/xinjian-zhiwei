from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from shared_student_authorization import demo_student_actor
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import func, select
from test_diagnosis_workflow import _add_failure_log, _settings
from test_experiment_packages import PACKAGE_ROOT, _admin_headers

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
from app.experiment_packages.loader import load_experiment_package, package_documents
from app.knowledge.case_drafting import withdraw_case
from app.models import (
    AIExplanationCache,
    Device,
    DiagnosisResult,
    ExperimentSession,
    KnowledgeCase,
    MemoryEvent,
    MemoryUse,
    User,
)
from app.models.base import utc_now
from app.services.diagnosis_workflow import serialize_workflow, start_workflow
from app.services.experiment_packages import (
    import_experiment_package,
    transition_experiment_package,
)
from app.services.memory import (
    case_source,
    current_source,
    diagnosis_sources_available,
    digest,
    memory_context,
    record_uses,
)
from app.services.memory_governance import (
    MemoryConflict,
    cleanup_manifest,
    execute_cleanup,
    impact_page,
    plan_cleanup,
    process_stop_cache,
    review_impact,
)


@pytest.fixture
def memory_task(api_context):
    headers = _admin_headers(api_context)
    _add_failure_log(api_context)
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        workflow = start_workflow(
            db,
            build_diagnosis_graph(InMemorySaver()),
            device,
            _settings(),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
         student_actor=demo_student_actor(db, device))
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
        from app.services.auth import resolve_session

        actor = resolve_session(db, headers["Authorization"].removeprefix("Bearer "))
        authorize_write_fixture(db, actor, "formal_approver")
        case = KnowledgeCase(
            id="synthetic-reviewed-memory",
            experiment_type="dht11_temperature_humidity",
            error_type="SENSOR_READ_FAILED",
            symptom="合成验证案例",
            normal_state={},
            evidence=[],
            possible_causes=[],
            solution_steps=[],
            facts={},
            root_cause_status="confirmed",
            facts_locked=True,
            quality_check_passed=True,
            review_status="approved",
            source_ref="test://memory",
            version="1",
            is_test_data=True,
        )
        db.add(case)
        db.commit()
        yield db, actor, case, diagnosis, workflow, headers


def _refs(case):
    return [{"chunk_id": case.id, "source_version": case.version}]


def _use(db, case, diagnosis, workflow):
    record_uses(
        db,
        diagnosis,
        _refs(case),
        target_type="workflow",
        target_id=workflow.id,
        use_kind="matched",
    )
    db.commit()


def _stop(db, actor, case):
    return withdraw_case(
        db,
        case,
        actor,
        request_id=str(uuid4()),
        expected_version=case.version,
        reason="合成案例发现错误",
    )


def _cache(db, *, expired=True, fingerprint=None):
    row = AIExplanationCache(
        fingerprint=fingerprint or uuid4().hex * 2,
        explanation_json={"synthetic": True},
        prompt_version="test",
        schema_version="test",
        ruleset_version="test",
        expires_at=utc_now() + timedelta(hours=-1 if expired else 1),
    )
    db.add(row)
    db.commit()
    return row


def test_three_memories_do_not_promote_observations_or_write_on_read(memory_task):
    db, _, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    before = db.scalar(select(func.count()).select_from(MemoryUse))
    memory = memory_context(db, workflow)
    assert memory["facts"] == []  # no package configuration, never invent measured facts
    assert memory["experiences"][0]["root_cause_for_this_task"] == "not_confirmed"
    assert memory["working"]["session_id"] == workflow.experiment_session_id
    assert memory["working"]["evidence_ids"]
    assert db.scalar(select(func.count()).select_from(MemoryUse)) == before
    assert db.query(KnowledgeCase).count() == 1


def test_completed_session_stops_active_working_memory_without_deleting_history(memory_task):
    db, _, _, _, workflow, _ = memory_task
    session = db.get(ExperimentSession, workflow.experiment_session_id)
    session.status = "ended"
    db.commit()
    memory = memory_context(db, workflow)
    assert memory["working"]["active"] is False
    assert memory["working"]["evidence_ids"]


def test_relationship_insert_is_idempotent_and_content_change_invalidates(memory_task):
    db, _, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _use(db, case, diagnosis, workflow)
    assert db.query(MemoryUse).count() == 1
    assert diagnosis_sources_available(db, diagnosis)
    case.symptom = "同ID和版本但正文被非法改变"
    db.commit()
    assert not diagnosis_sources_available(db, diagnosis)


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("review_status", "pending"),
        ("root_cause_status", "unknown"),
        ("facts_locked", False),
        ("quality_check_passed", False),
    ],
)
def test_each_experience_gate_is_enforced(memory_task, attribute, value):
    db, _, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    setattr(case, attribute, value)
    db.commit()
    assert not diagnosis_sources_available(db, diagnosis)


def test_test_experience_cannot_enter_formal_task(memory_task):
    db, _, case, _, _, _ = memory_task
    assert not current_source(db, case_source(case), is_test_data=False)


def test_withdraw_stops_old_projection_and_preserves_original_result(memory_task):
    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    original = deepcopy(workflow.final_result)
    _stop(db, actor, case)
    event = db.query(MemoryEvent).one()
    assert event.source == case_source(case)
    response = serialize_workflow(workflow, audience="student")
    assert not response.teaching_available
    assert response.final_result is None and response.review_request is None
    assert response.memory_context.experiences == []
    assert response.memory_context.working.next_step == "contact_teacher"
    assert workflow.final_result == original
    impact = impact_page(db, actor, event)
    assert impact["items"][0]["basis"] == ["matched"]
    assert impact["untracked_history"] == "unknown"


def test_impact_review_conflict_and_retry_do_not_change_diagnosis(memory_task):
    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _stop(db, actor, case)
    event = db.query(MemoryEvent).one()
    original = deepcopy(diagnosis.matched_rules)
    first = review_impact(
        db,
        actor,
        event,
        diagnosis,
        expected_version=0,
        decision="verify_again",
        note="需补充独立测量",
    )
    repeated = review_impact(
        db,
        actor,
        event,
        diagnosis,
        expected_version=0,
        decision="verify_again",
        note="需补充独立测量",
    )
    assert repeated.id == first.id and repeated.version == 1
    with pytest.raises(MemoryConflict):
        review_impact(
            db, actor, event, diagnosis, expected_version=0, decision="no_change", note="并发旧版本"
        )
    assert diagnosis.matched_rules == original


def test_cache_invalidation_uses_exact_source_and_can_retry(memory_task):
    db, actor, case, diagnosis, workflow, _ = memory_task
    target, unrelated = _cache(db, expired=False), _cache(db, expired=False)
    record_uses(
        db,
        diagnosis,
        _refs(case),
        target_type="cache",
        target_id=target.fingerprint,
        use_kind="derived",
    )
    db.commit()
    _stop(db, actor, case)
    event = db.query(MemoryEvent).one()
    assert process_stop_cache(db, event)["deleted"] == 1
    assert process_stop_cache(db, event)["deleted"] == 0
    assert db.get(AIExplanationCache, unrelated.id) is not None
    assert db.get(DiagnosisResult, diagnosis.id) is not None


def test_cleanup_freezes_scope_rechecks_expiry_and_preserves_protected_stores(memory_task):
    db, actor, _, diagnosis, _, _ = memory_task
    expired, changed, live = _cache(db), _cache(db), _cache(db, expired=False)
    plan = plan_cleanup(db, actor)
    later = _cache(db)
    changed.expires_at = utc_now() + timedelta(days=1)
    db.commit()
    result = execute_cleanup(db, actor, plan, expected_hash=digest(plan.targets))
    assert result.status == "partial"
    assert db.get(AIExplanationCache, expired.id) is None
    assert all(db.get(AIExplanationCache, row.id) for row in [changed, live, later])
    assert db.get(DiagnosisResult, diagnosis.id)
    manifest = cleanup_manifest(result)
    assert {r["store"] for r in manifest["blocked_stores"]} >= {"evidence", "checkpoint", "backup"}
    assert not result.result["all_copies_deleted"]


def test_cleanup_hash_mismatch_cannot_delete(memory_task):
    db, actor, _, _, _, _ = memory_task
    row = _cache(db)
    plan = plan_cleanup(db, actor)
    with pytest.raises(MemoryConflict):
        execute_cleanup(db, actor, plan, expected_hash="0" * 64)
    assert db.get(AIExplanationCache, row.id)


def test_memory_management_api_enforces_auth_and_plan_ownership(api_context, memory_task):
    db, _, _, _, _, headers = memory_task
    client = api_context["client"]
    _cache(db)
    assert client.get("/api/v1/memory/events").status_code == 401
    response = client.post("/api/v1/memory/cleanup-plans", headers=headers)
    assert response.status_code == 201, response.text
    plan = response.json()
    response = client.post(
        f"/api/v1/memory/cleanup-plans/{plan['id']}/execute",
        headers=headers,
        json={"plan_hash": plan["plan_hash"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    repeat = client.post(
        f"/api/v1/memory/cleanup-plans/{plan['id']}/execute",
        headers=headers,
        json={"plan_hash": plan["plan_hash"]},
    )
    assert repeat.json()["result"] == response.json()["result"]


def test_package_configuration_is_not_measured_fact_and_revocation_is_separate(memory_task):
    db, actor, case, diagnosis, workflow, _ = memory_task
    authorize_write_fixture(db, actor)
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    experiment, version = import_experiment_package(
        db, actor, package_documents(bundle), is_test_data=True
    )
    for status in ["pending", "approved", "published"]:
        transition_experiment_package(db, actor, version, status)
    diagnosis.experiment_record_id = workflow.experiment_record_id = experiment.id
    diagnosis.experiment_version_id = workflow.experiment_version_id = version.id
    db.commit()
    _stop(db, actor, case)
    memory = memory_context(db, workflow)
    assert memory["available"]
    assert memory["facts"] and all(f["kind"] == "configuration" for f in memory["facts"])
    assert all(f["physical_verification"] == "not_asserted" for f in memory["facts"])
    transition_experiment_package(db, actor, version, "revoked")
    assert not memory_context(db, workflow)["available"]
    assert db.query(MemoryEvent).count() == 2


def test_missing_experience_fails_closed(memory_task):
    db, _, _, diagnosis, _, _ = memory_task
    from app.services.memory import references_available

    assert not references_available(
        db, diagnosis, [{"chunk_id": "nonexistent", "source_version": "1"}]
    )


def test_datetime_identity_survives_database_roundtrip(memory_task):
    db, _, case, _, _, _ = memory_task
    case.confirmed_at = utc_now()
    expected = case_source(case)
    db.commit()
    db.expire_all()
    assert case_source(case) == expected


def test_late_version_change_discards_model_output_without_free_retry(memory_task):
    from app.ai.clients import AICompletion
    from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
    from app.core.config import Settings
    from app.models import AIUsageReservation

    db, _, case, diagnosis, _, _ = memory_task

    class Provider:
        configured = True
        provider = model = "synthetic-memory"

        def complete_json(self, **kwargs):
            case.version = "2"
            db.commit()
            return AICompletion("{}", input_tokens=1, output_tokens=1)

    governor = GovernedAIInvocation(
        db,
        diagnosis,
        Settings(ai_enabled=True),
        call_stage="memory-test",
        knowledge_case_ids=(case.id,),
    )
    with pytest.raises(AIQuotaDenied, match="AI_KNOWLEDGE_CHANGED"):
        governor.complete_json(Provider(), system_prompt="synthetic", user_prompt="synthetic")
    assert db.query(AIUsageReservation).count() == 1
    assert db.query(AIUsageReservation).one().status == "succeeded"


def test_teacher_cannot_review_or_discover_another_class(memory_task):
    from app.services.memory_governance import event_page
    from app.services.rbac import assign_role, ensure_rbac_catalog

    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _stop(db, actor, case)
    roles = ensure_rbac_catalog(db)
    outsider = User(
        username="unrelated-teacher",
        display_name="合成外班教师",
        password_hash="not-used",
        is_test_data=True,
    )
    db.add(outsider)
    db.flush()
    assign_role(db, outsider, roles["teacher"])
    db.commit()
    event = db.query(MemoryEvent).one()
    assert event_page(db, outsider)["items"] == []
    assert impact_page(db, outsider, event)["items"] == []
    with pytest.raises(PermissionError):
        review_impact(
            db,
            outsider,
            event,
            diagnosis,
            expected_version=0,
            decision="no_change",
            note="不应有权限",
        )
    assert event_page(db, actor)["items"][0]["id"] == event.id


def test_reviewer_role_does_not_imply_classroom_history_access(memory_task):
    from app.services.memory_governance import event_page
    from app.services.rbac import assign_role, ensure_rbac_catalog

    db, _, _, _, _, _ = memory_task
    roles = ensure_rbac_catalog(db)
    reviewer = User(
        username="only-formal-reviewer",
        display_name="合成审核员",
        password_hash="not-used",
        is_test_data=True,
    )
    db.add(reviewer)
    db.flush()
    assign_role(db, reviewer, roles["formal_approver"])
    db.commit()
    with pytest.raises(PermissionError):
        event_page(db, reviewer)


def test_ordinary_teacher_sees_own_event_and_can_review(memory_task):
    from app.models import ExperimentAssignment, TeachingAssignment
    from app.services.memory_governance import event_page
    from app.services.rbac import assign_role, ensure_rbac_catalog

    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _stop(db, actor, case)
    roles = ensure_rbac_catalog(db)
    teacher = User(
        username="own-class-teacher",
        display_name="合成任课教师",
        password_hash="not-used",
        is_test_data=True,
    )
    db.add(teacher)
    db.flush()
    assign_role(db, teacher, roles["teacher"])
    assignment = db.get(ExperimentAssignment, workflow.experiment_session.experiment_assignment_id)
    db.add(TeachingAssignment(user_id=teacher.id, class_id=assignment.class_id))
    db.commit()
    event = db.query(MemoryEvent).one()
    assert event_page(db, teacher)["items"][0]["id"] == event.id
    assert impact_page(db, teacher, event)["items"][0]["diagnosis_result_id"] == diagnosis.id
    assert (
        review_impact(
            db,
            teacher,
            event,
            diagnosis,
            expected_version=0,
            decision="verify_again",
            note="安排独立核验",
        ).version
        == 1
    )


def test_restore_registry_stops_knowledge_again_without_deleting_history(memory_task):
    from app.services.memory_restore import export_registry, replay_registry

    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _stop(db, actor, case)
    registry = export_registry(db)
    case.review_status = "approved"  # Simulate an older restored business snapshot.
    cache = _cache(db, expired=False)
    db.commit()
    report = replay_registry(db, registry)
    assert report["applied"] == 1 and not report["serving_authorized"]
    db.refresh(case)
    db.refresh(cache)
    assert case.review_status == "withdrawn"
    assert not memory_context(db, workflow)["available"]
    assert db.get(DiagnosisResult, diagnosis.id)
    assert replay_registry(db, registry)["applied"] == 1
    assert db.query(MemoryEvent).count() == 1


def test_restore_registry_rejects_corruption_and_unknown_source(memory_task):
    from app.services.memory_restore import export_registry, replay_registry

    db, actor, case, _, _, _ = memory_task
    _stop(db, actor, case)
    manifest = export_registry(db)
    manifest["events"][0]["source"]["id"] = "unknown"
    with pytest.raises(ValueError, match="integrity"):
        replay_registry(db, manifest)
    manifest["sha256"] = digest({k: manifest[k] for k in ("version", "events")})
    with pytest.raises(ValueError, match="unresolved"):
        replay_registry(db, manifest)


def test_case_file_sync_cannot_overwrite_an_existing_version(memory_task):
    from app.cli.sync_knowledge_cases import sync_case_definitions
    from app.knowledge.loader import load_case_definitions

    db, _, _, _, _, _ = memory_task
    definition = load_case_definitions()[0]
    assert sync_case_definitions(db, [definition]) == 1
    assert sync_case_definitions(db, [definition]) == 0
    edited = definition.model_copy(update={"symptom": "不能静默覆盖历史"})
    with pytest.raises(ValueError, match="immutable"):
        sync_case_definitions(db, [edited])
    assert db.get(KnowledgeCase, definition.id).symptom == definition.symptom


def test_recorded_call_sources_remain_the_pre_call_snapshot(memory_task):
    from app.services.memory import sources_for_references

    db, _, case, diagnosis, workflow, _ = memory_task
    snapshot = sources_for_references(db, diagnosis, _refs(case))
    old_hash = snapshot[0]["hash"]
    case.version = "2"
    case.symptom = "调用期间发生的新版修订"
    db.commit()
    record_uses(
        db,
        diagnosis,
        _refs(case),
        target_type="ai_call",
        target_id="synthetic-call",
        use_kind="provided",
        sources=snapshot,
    )
    db.commit()
    row = db.scalar(select(MemoryUse).where(MemoryUse.target_id == "synthetic-call"))
    assert row.source["version"] == "1"
    assert row.source["hash"] == old_hash
    assert not diagnosis_sources_available(db, diagnosis)


def test_legacy_guidance_endpoints_cannot_bypass_stop_gate(api_context, memory_task):
    from app.models import GuidanceHistory

    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    original_count = db.query(GuidanceHistory).count()
    _stop(db, actor, case)
    client = api_context["client"]
    response = client.post(
        f"/api/v1/diagnosis/results/{diagnosis.id}/guidance", headers=api_context["headers"]
    )
    assert response.status_code == 201, response.text
    assert response.json()["items"] == []
    response = client.get(
        "/api/v1/diagnosis/devices/phase2-test-device/guidance", headers=api_context["headers"]
    )
    assert response.status_code == 200 and response.json() == []
    assert db.query(GuidanceHistory).count() == original_count
