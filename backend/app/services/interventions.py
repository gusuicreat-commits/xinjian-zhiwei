from contextlib import nullcontext
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models.base import utc_now
from app.models.classroom import Classroom, User
from app.models.diagnosis_result import DiagnosisResult
from app.models.intervention import InterventionCase, InterventionEvent
from app.services.diagnosis_episode import issue_links, lifecycle_lock
from app.services.provenance import derive_test_flag

TRANSITIONS = {
    ("open", "claim"): "claimed",
    ("claimed", "transfer"): "claimed",
    ("claimed", "resolve"): "resolved",
    ("claimed", "mark_unconfirmed"): "unconfirmed",
    ("unconfirmed", "transfer"): "claimed",
    ("unconfirmed", "close"): "closed",
    ("resolved", "close"): "closed",
}


class InterventionConflict(ConflictError):
    pass


def ensure_intervention_case(
    db: Session,
    diagnosis: DiagnosisResult,
    *,
    class_id: str,
    actor_user_id: str,
    source: str,
    episode_id: str | None = None,
    actor=None,
) -> InterventionCase:
    if source == "authenticated_user_request" or actor is not None:
        # Shared diagnosis lock permits competing creates (the unique constraint
        # still selects the winner), while refreshing the recorded owner first.
        diagnosis = db.scalar(
            select(DiagnosisResult)
            .where(DiagnosisResult.id == diagnosis.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        _authorize_intervention_request(db, actor, diagnosis, class_id, actor_user_id)
    links = issue_links(db, diagnosis)
    if links:
        if episode_id is None and len(links) == 1:
            episode_id = links[0].episode_id
        if not any(link.episode_id == episode_id for link in links):
            raise InterventionConflict("select one recorded problem for this intervention")
        original = db.scalar(
            select(InterventionCase)
            .where(
                InterventionCase.diagnosis_result_id == diagnosis.id,
                InterventionCase.episode_id == episode_id,
            )
            .order_by(InterventionCase.created_at)
        )
        if original is not None:
            return original
        query = select(InterventionCase).where(
            InterventionCase.episode_id == episode_id,
            InterventionCase.status.in_(["open", "claimed", "unconfirmed"]),
        )
    else:
        if episode_id is not None:
            raise InterventionConflict("historical diagnosis has no recorded problem association")
        query = select(InterventionCase).where(InterventionCase.diagnosis_result_id == diagnosis.id)
    existing = db.scalar(query)
    if existing is not None:
        return existing
    case = InterventionCase(
        diagnosis_result_id=diagnosis.id,
        episode_id=episode_id,
        class_id=class_id,
        status="open",
        version_no=1,
        is_test_data=derive_test_flag(
            diagnosis.is_test_data,
            getattr(db.get(User, actor_user_id), "is_test_data", None),
            getattr(db.get(Classroom, class_id), "is_test_data", None),
        ),
    )
    db.add(case)
    db.flush()
    db.add(
        InterventionEvent(
            case_id=case.id,
            actor_user_id=actor_user_id,
            action="request_help",
            from_status=None,
            to_status="open",
            note=None,
            is_private=False,
            metadata_json={
                "diagnosis_result_id": diagnosis.id,
                "source": source,
            },
            created_at=utc_now(),
        )
    )
    return case


def _authorize_intervention_request(db, identity, diagnosis, class_id, actor_user_id):
    from app.models.classroom import ExperimentAssignment, ExperimentSession
    from app.services.auth import AuthorizationDenied, authorize_actor, user_access
    from app.services.data_scope import (
        ScopeConflict,
        ScopeViolation,
        assert_student_session_access,
        authorize_teacher_class,
        diagnosis_session,
        protect_student_scope,
        teacher_has_class_access,
    )

    if identity is None or identity.user_id != actor_user_id or diagnosis is None:
        raise AuthorizationDenied(401)
    owner = diagnosis_session(db, diagnosis)
    if owner is None:
        raise AuthorizationDenied()
    # This entry historically allows an admin without a capability check.
    # Lock/revalidate all identity and grant rows before choosing the same branch.
    candidate = authorize_actor(db, identity, None)
    roles, _ = user_access(db, candidate.id)
    teacher_access = teacher_has_class_access(db, candidate, class_id)
    if teacher_access and "admin" not in roles:
        authorize_teacher_class(db, identity, class_id)
    elif not teacher_access:
        user = authorize_actor(db, identity, "assignment.read")
    owner = db.scalar(
        select(ExperimentSession)
        .where(ExperimentSession.id == owner.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if owner is None:
        raise AuthorizationDenied()
    if not teacher_access:
        try:
            protect_student_scope(db, user, owner)
            assert_student_session_access(db, user, owner)
        except (ScopeConflict, ScopeViolation) as exc:
            raise AuthorizationDenied() from exc
    assignment = db.scalar(
        select(ExperimentAssignment)
        .where(ExperimentAssignment.id == owner.experiment_assignment_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if assignment is None or assignment.class_id != class_id:
        raise AuthorizationDenied()


def apply_action(db, case, actor, *, request_id=None, recheck_access=None, **kwargs):
    diagnosis = db.get(DiagnosisResult, case.diagnosis_result_id)
    with lifecycle_lock(db, diagnosis) if diagnosis is not None else nullcontext():
        db.refresh(case)
        from app.services.auth import current_actor
        from app.services.data_scope import authorize_teacher_class

        actor = authorize_teacher_class(db, current_actor(actor), case.class_id)
        if recheck_access is not None:
            recheck_access()
        payload = {"case_id": case.id, **kwargs}
        if request_id:
            for event in db.scalars(
                select(InterventionEvent).where(
                    InterventionEvent.case_id == case.id,
                    InterventionEvent.actor_user_id == actor.id,
                )
            ):
                if event.metadata_json.get("request_id") == request_id:
                    if event.metadata_json.get("payload") != payload:
                        raise InterventionConflict(
                            "request identity already used with different content"
                        )
                    return InterventionCase(**event.metadata_json["result"])
        return _apply_action(db, case, actor, request_id=request_id, payload=payload, **kwargs)


def _apply_action(
    db: Session,
    case: InterventionCase,
    actor: User,
    *,
    action: str,
    expected_version: int,
    note: Optional[str],
    target_teacher_user_id: Optional[str],
    is_private: bool,
    request_id=None,
    payload=None,
) -> InterventionCase:
    if case.version_no != expected_version:
        raise InterventionConflict("intervention version conflict")
    from_status = case.status
    to_status = from_status
    assigned_teacher = case.assigned_teacher_user_id
    resolution = case.resolution_summary
    if action == "note":
        if not note:
            raise ValueError("note action requires note")
    else:
        to_status = TRANSITIONS.get((from_status, action))
        if to_status is None:
            raise ValueError(f"invalid intervention action {action} from {from_status}")
        if action == "claim":
            assigned_teacher = actor.id
        elif action == "transfer":
            if not target_teacher_user_id:
                raise ValueError("transfer requires target_teacher_user_id")
            assigned_teacher = target_teacher_user_id
        elif action == "resolve":
            if not note:
                raise ValueError("resolve requires a resolution note")
            resolution = None if is_private else note
    result = db.execute(
        update(InterventionCase)
        .where(
            InterventionCase.id == case.id,
            InterventionCase.version_no == expected_version,
        )
        .values(
            status=to_status,
            assigned_teacher_user_id=assigned_teacher,
            resolution_summary=resolution,
            version_no=expected_version + 1,
            updated_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise InterventionConflict("intervention version conflict")
    db.add(
        InterventionEvent(
            case_id=case.id,
            actor_user_id=actor.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            note=note,
            is_private=is_private,
            metadata_json={
                "target_teacher_user_id": target_teacher_user_id,
                "request_id": request_id,
                "payload": payload,
                "result": {
                    key: getattr(case, key)
                    for key in (
                        "id",
                        "diagnosis_result_id",
                        "episode_id",
                        "class_id",
                        "assigned_teacher_user_id",
                        "status",
                        "version_no",
                        "resolution_summary",
                        "is_test_data",
                    )
                },
            },
            created_at=utc_now(),
        )
    )
    # Work completion is not physical recovery. Explicit problem transitions
    # belong to the lifecycle service and require their own evidence revision.
    db.commit()
    updated = db.get(InterventionCase, case.id)
    if updated is None:
        raise RuntimeError("updated intervention disappeared")
    return updated


def public_resolution_summary(db: Session, case: InterventionCase) -> Optional[str]:
    """Project only an explicitly public resolution, including for legacy cases."""

    event = db.scalar(
        select(InterventionEvent)
        .where(InterventionEvent.case_id == case.id, InterventionEvent.action == "resolve")
        .order_by(InterventionEvent.created_at.desc(), InterventionEvent.id.desc())
        .limit(1)
    )
    if event is None or event.is_private:
        return None
    return event.note


def apply_problem_resolution(
    db,
    case,
    actor,
    *,
    request_id,
    expected_revision,
    recovery_diagnosis_id=None,
    recheck_access=None,
):
    """Explicit teacher report; verified recovery additionally needs fresh rule evidence."""
    from app.models.diagnosis_episode import DiagnosisEpisode
    from app.services.diagnosis_episode import (
        EpisodeFeedbackConflict,
        finish_problem,
        lifecycle_lock,
    )

    if not case.episode_id:
        raise InterventionConflict("historical work order has no recorded problem target")
    diagnosis = db.get(DiagnosisResult, case.diagnosis_result_id)
    with lifecycle_lock(db, diagnosis):
        db.refresh(case)
        from app.services.auth import current_actor
        from app.services.data_scope import authorize_teacher_class

        actor = authorize_teacher_class(db, current_actor(actor), case.class_id)
        if recheck_access is not None:
            recheck_access()
        payload = {
            "case_id": case.id,
            "expected_revision": expected_revision,
            "recovery_diagnosis_id": recovery_diagnosis_id,
        }
        events = db.scalars(
            select(InterventionEvent).where(
                InterventionEvent.case_id == case.id,
                InterventionEvent.actor_user_id == actor.id,
                InterventionEvent.action == "problem_resolved",
            )
        )
        for event in events:
            if event.metadata_json.get("request_id") == request_id:
                if event.metadata_json.get("payload") != payload:
                    raise InterventionConflict(
                        "request identity already used with different content"
                    )
                return event.metadata_json["result"]
        episode = db.get(DiagnosisEpisode, case.episode_id, populate_existing=True)
        if episode is None or episode.status not in {"open", "escalated"}:
            raise InterventionConflict("problem is no longer active")
        recovery = db.get(DiagnosisResult, recovery_diagnosis_id) if recovery_diagnosis_id else None
        source = "teacher_verified_recovery" if recovery_diagnosis_id else "teacher_report"
        try:
            finish_problem(episode, expected_revision, source, recovery=recovery)
        except EpisodeFeedbackConflict as exc:
            raise InterventionConflict(str(exc)) from exc
        result = {
            "episode_id": episode.id,
            "status": episode.status,
            "resolution_source": episode.resolution_source,
        }
        db.add(
            InterventionEvent(
                case_id=case.id,
                actor_user_id=actor.id,
                action="problem_resolved",
                from_status=case.status,
                to_status=case.status,
                is_private=False,
                note="教师已明确结束此问题。" if not recovery else "已核对新的规则恢复证据。",
                metadata_json={
                    "episode_id": episode.id,
                    "evidence_revision": expected_revision,
                    "request_id": request_id,
                    "payload": payload,
                    "result": result,
                    "recovery_diagnosis_id": recovery_diagnosis_id,
                    "resolution_source": episode.resolution_source,
                },
                created_at=utc_now(),
            )
        )
        db.commit()
        return result


def timeline(
    db: Session,
    case_id: str,
    *,
    include_private: bool,
) -> list[InterventionEvent]:
    query = (
        select(InterventionEvent)
        .where(InterventionEvent.case_id == case_id)
        .order_by(InterventionEvent.created_at, InterventionEvent.id)
    )
    if not include_private:
        query = query.where(InterventionEvent.is_private.is_(False))
    return list(db.scalars(query))
