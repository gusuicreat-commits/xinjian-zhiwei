from datetime import datetime, timezone
from uuid import uuid4

from test_episode_lifecycle_r2 import feedback, log, run

from app.models import DiagnosisEpisode, DiagnosisResult


def two_issues(ctx):
    log(ctx)
    response = ctx["client"].post(
        "/api/v1/device/readings",
        headers=ctx["headers"],
        json={
            "sensor_type": "synthetic",
            "metric_key": "temperature",
            "value": 99,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "is_test_data": True,
        },
    )
    assert response.status_code == 201
    return run(
        ctx,
        experiment_template={
            "template_id": "business-issues",
            "metric_ranges": {"temperature": {"minimum": 0, "maximum": 50}},
        },
    )


def test_two_anomalies_have_independent_targets_and_ambiguous_feedback_conflicts(api_context):
    result = two_issues(api_context)
    assert len(result["issues"]) == 2
    assert feedback(api_context, result, "resolved").status_code == 409
    target = result["issues"][0]["id"]
    response = api_context["client"].post(
        f"/api/v1/student/diagnoses/{result['id']}/feedback",
        headers=api_context["headers"],
        json={
            "request_id": str(uuid4()),
            "action": "resolved",
            "episode_id": target,
        },
    )
    assert response.status_code == 201, response.text
    with api_context["session_factory"]() as db:
        assert db.get(DiagnosisEpisode, target).status == "resolved"
        other = next(i for i in result["issues"] if i["id"] != target)
        assert db.get(DiagnosisEpisode, other["id"]).status == "open"


def test_rule_order_is_not_problem_identity(api_context):
    from app.core.config import Settings
    from app.models import Device
    from app.services.diagnosis_episode import diagnosis_issues, upsert_episode

    result = two_issues(api_context)
    with api_context["session_factory"]() as db:
        original = db.get(DiagnosisResult, result["id"])
        copy = DiagnosisResult(
            device_id=original.device_id,
            evaluated_at=original.evaluated_at,
            ruleset_version=original.ruleset_version,
            ruleset_hash=original.ruleset_hash,
            input_fingerprint=original.input_fingerprint,
            matched_rules=list(reversed(original.matched_rules)),
            evidence=original.evidence,
            context_snapshot=original.context_snapshot,
            is_test_data=True,
        )
        db.add(copy)
        db.commit()
        upsert_episode(db, db.get(Device, copy.device_id), copy, [], Settings())
        assert {i["id"] for i in diagnosis_issues(db, copy)} == {i["id"] for i in result["issues"]}
        assert all(i["failure_count"] == 1 for i in diagnosis_issues(db, copy))


def test_teacher_work_completion_and_explicit_problem_resolution_are_separate(api_context):
    from app.models import ExperimentAssignment, ExperimentSession, User
    from app.services.interventions import (
        apply_action,
        apply_problem_resolution,
        ensure_intervention_case,
    )

    log(api_context)
    result = run(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, result["id"])
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        actor = db.get(
            User, session.student_user_id
        )  # service test with explicit current teacher grants
        classroom = db.get(ExperimentAssignment, session.experiment_assignment_id).class_id
        from shared_authorization import session_actor_fixture

        from app.models import TeachingAssignment
        from app.services.rbac import assign_role, ensure_rbac_catalog

        assign_role(db, actor, ensure_rbac_catalog(db)["teacher"])
        db.add(TeachingAssignment(class_id=classroom, user_id=actor.id))
        session_actor_fixture(db, actor)
        case = ensure_intervention_case(
            db, diagnosis, class_id=classroom, actor_user_id=actor.id, source="synthetic"
        )
        db.commit()
        claim_request = str(uuid4())
        for action, version, note in [("claim", 1, None), ("resolve", 2, "已完成教师工作")]:
            case = apply_action(
                db,
                case,
                actor,
                action=action,
                request_id=claim_request if action == "claim" else str(uuid4()),
                expected_version=version,
                note=note,
                target_teacher_user_id=None,
                is_private=False,
            )
        replay = apply_action(
            db,
            case,
            actor,
            request_id=claim_request,
            action="claim",
            expected_version=1,
            note=None,
            target_teacher_user_id=None,
            is_private=False,
        )
        assert replay.version_no == 2 and replay.status == "claimed"
        db.refresh(case)
        assert case.version_no == 3 and case.status == "resolved"
        episode = db.get(DiagnosisEpisode, diagnosis.episode_id)
        assert episode.status == "open"
        assert episode.resolution_source is None
        request = str(uuid4())
        kwargs = {"request_id": request, "expected_revision": episode.evidence_revision}
        first = apply_problem_resolution(db, case, actor, **kwargs)
        assert apply_problem_resolution(db, case, actor, **kwargs) == first
        assert first["resolution_source"] == "teacher_report"


def test_preclosure_sample_delivered_late_does_not_reopen_problem(api_context):
    from datetime import timedelta

    log(api_context)
    first = run(api_context)
    assert feedback(api_context, first, "resolved").status_code == 201
    log(api_context, occurred_at=datetime.now(timezone.utc) - timedelta(seconds=2))
    later = run(api_context)
    assert later["episode"]["id"] == first["episode"]["id"]
    assert later["episode"]["status"] == "resolved"


def test_new_normalized_uuid_does_not_make_the_same_source_new_evidence():
    from types import SimpleNamespace

    from app.services.diagnosis_episode import failure_evidence_keys

    def view(event_id):
        return SimpleNamespace(
            context_snapshot={},
            matched_rules=[
                {
                    "rule_id": "read-failure",
                    "error_type": "SENSOR_READ_FAILED",
                    "evidence": [
                        {
                            "details": [
                                {
                                    "event_id": event_id,
                                    "source": "device_log",
                                    "source_ref": "one-physical-log",
                                }
                            ]
                        }
                    ],
                }
            ],
        )

    assert failure_evidence_keys(view("normalization-1")) == failure_evidence_keys(
        view("normalization-2")
    )


def test_same_error_in_two_components_has_separate_guidance(api_context):
    from copy import deepcopy

    from app.models import Device
    from app.services.guidance import _build_guidance_records as generate_guidance

    log(api_context)
    result = run(api_context)
    with api_context["session_factory"]() as db:
        original = db.get(DiagnosisResult, result["id"])
        matches = []
        for component in ("sensor-a", "sensor-b"):
            match = deepcopy(original.matched_rules[0])
            match["scope"] = {"kind": "component", "keys": [component]}
            matches.append(match)
        copy = DiagnosisResult(
            device_id=original.device_id,
            evaluated_at=original.evaluated_at,
            ruleset_version=original.ruleset_version,
            ruleset_hash=original.ruleset_hash,
            input_fingerprint=original.input_fingerprint,
            matched_rules=matches,
            evidence=original.evidence,
            context_snapshot=original.context_snapshot,
            is_test_data=True,
        )
        db.add(copy)
        db.commit()
        guidance = generate_guidance(db, db.get(Device, copy.device_id), copy)
        assert len(guidance) == 2
        assert len({item.episode_id for item in guidance}) == 2
        assert all(item.episode_id and item.failure_count == 1 for item in guidance)
