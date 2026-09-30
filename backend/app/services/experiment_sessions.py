"""BR-SESSION: one device use at a time, immutable ownership and durable receipts."""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from threading import RLock

from sqlalchemy import or_, select

from app.models import (
    AuditEvent,
    Classroom,
    Device,
    DeviceBinding,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentSessionCommand,
    TeachingAssignment,
    User,
)
from app.models.base import utc_now
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    assert_student_assignment_access,
    assert_student_session_access,
    authorize_teacher_class,
    is_demo_device,
    protect_student_scope,
)
from app.services.experiment_packages import load_experiment_package_runtime

_LOCAL_COMMAND_LOCK = RLock()


@contextmanager
def _command_lock(db, actor, permission="assignment.read"):
    # All session commands take actor then device row locks in the same order.
    # PostgreSQL holds them until the command + audit + receipt commit together.
    with _LOCAL_COMMAND_LOCK if db.get_bind().dialect.name == "sqlite" else nullcontext():
        user = db.scalar(
            select(User)
            .where(User.id == actor.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None or not user.is_active:
            raise ScopeViolation("account is no longer active")
        from app.services.auth import authorize_actor, current_actor

        user = authorize_actor(db, current_actor(actor), permission)
        yield user


def session_summary(db, session):
    device = db.get(Device, session.device_id)
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    return {
        "id": session.id,
        "device_id": device.device_key,
        "display_name": device.display_name,
        "assignment_title": assignment.title,
        "experiment_assignment_id": assignment.id,
        "experiment_version_id": session.experiment_version_id,
        "status": session.status,
        "version_no": session.version_no,
        "is_test_data": session.is_test_data,
    }


def _replay(db, actor, request_id, digest, *, managed=False):
    receipt = db.scalar(
        select(ExperimentSessionCommand).where(
            ExperimentSessionCommand.actor_user_id == actor.id,
            ExperimentSessionCommand.request_id == str(request_id),
        )
    )
    if receipt is None:
        return None
    if receipt.payload_hash != digest:
        raise ScopeConflict("request_id already used with different content")
    session = db.get(ExperimentSession, receipt.session_id)
    if managed:
        assert_session_management(db, actor, session)
    else:
        assert_student_session_access(db, actor, session, require_active=False)
    return receipt.result_json


def _record(db, actor, session, request_id, digest, action, *, details=None):
    result = session_summary(db, session)
    db.add(
        ExperimentSessionCommand(
            actor_user_id=actor.id,
            session_id=session.id,
            request_id=str(request_id),
            payload_hash=digest,
            result_json=result,
        )
    )
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action=action,
            resource_type="experiment_session",
            resource_id=session.id,
            details_json={
                "request_id": str(request_id),
                "version_no": session.version_no,
                **(details or {}),
            },
            is_test_data=session.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    return result


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def start_session(db, actor, *, request_id, device_key, assignment_id):
    digest = _digest({"action": "start", "device_key": device_key, "assignment_id": assignment_id})
    with _command_lock(db, actor) as user:
        replay = _replay(db, user, request_id, digest)
        if replay is not None:
            db.commit()
            return replay
        device = db.scalar(
            select(Device)
            .where(Device.device_key == device_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if device is None or not device.is_active:
            raise ScopeViolation("device is not available")
        assignment = db.scalar(
            select(ExperimentAssignment)
            .where(ExperimentAssignment.id == assignment_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if assignment is not None:
            from app.models import Enrollment

            db.scalar(
                select(Classroom)
                .where(Classroom.id == assignment.class_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            db.scalar(
                select(Enrollment)
                .where(Enrollment.class_id == assignment.class_id, Enrollment.user_id == user.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        assert_student_assignment_access(db, user, assignment)
        binding = db.scalar(
            select(DeviceBinding)
            .where(
                DeviceBinding.device_id == device.id,
                DeviceBinding.class_id == assignment.class_id,
                DeviceBinding.student_user_id == user.id,
                DeviceBinding.is_active.is_(True),
                or_(
                    DeviceBinding.experiment_assignment_id == assignment.id,
                    DeviceBinding.experiment_assignment_id.is_(None),
                ),
            )
            .with_for_update(read=True)
        )
        if binding is None:
            raise ScopeViolation("device is not assigned to this student and task")
        if db.scalar(
            select(ExperimentSession.id).where(
                ExperimentSession.device_id == device.id,
                ExperimentSession.status == "active",
                ExperimentSession.ended_at.is_(None),
            )
        ):
            raise ScopeConflict("device already has an active experiment session")
        from app.services.provenance import derive_test_flag

        test_data = derive_test_flag(
            user.is_test_data,
            assignment.is_test_data,
            is_demo_device(device),
            db.get(Classroom, assignment.class_id).is_test_data,
        )
        if assignment.experiment_version_id:
            runtime = load_experiment_package_runtime(db, assignment.experiment_version_id)
            if not assignment.is_test_data and runtime.version.is_test_data:
                raise ScopeConflict("test package cannot start a formal assignment")
            test_data = test_data or runtime.version.is_test_data
        elif not assignment.is_test_data:
            raise ScopeConflict("formal assignment requires a published experiment package")
        session = ExperimentSession(
            experiment_assignment_id=assignment.id,
            student_user_id=user.id,
            device_id=device.id,
            experiment_version_id=assignment.experiment_version_id,
            status="active",
            started_at=utc_now(),
            is_test_data=test_data,
            version_no=1,
        )
        db.add(session)
        db.flush()
        return _record(db, user, session, request_id, digest, "experiment_session.start")


def end_session(db, actor, *, session_id, request_id, expected_version, reason):
    digest = _digest(
        {
            "action": "end",
            "session_id": session_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    with _command_lock(db, actor) as user:
        replay = _replay(db, user, request_id, digest)
        if replay is not None:
            db.commit()
            return replay
        session = db.get(ExperimentSession, session_id)
        if session is None:
            raise ScopeViolation("session is not available")
        db.scalar(select(Device).where(Device.id == session.device_id).with_for_update())
        db.refresh(session)
        # Students can end their own work after a deadline, but cannot access a
        # revoked enrollment or modify an already closed session.
        protect_student_scope(db, user, session)
        if session.version_no != expected_version or session.status != "active" or session.ended_at:
            raise ScopeConflict("session state changed; refresh before ending")
        session.status = reason
        session.ended_at = utc_now()
        session.version_no += 1
        return _record(db, user, session, request_id, digest, "experiment_session.end")


def _management_roles(db, actor):
    from app.services.auth import user_access

    roles, permissions = user_access(db, actor.id)
    if (
        not actor.is_active
        or not {"teacher", "admin"}.intersection(roles)
        or "assignment.manage" not in permissions
    ):
        raise ScopeViolation("experiment session management is not authorized")
    return roles


def assert_session_management(db, actor, session):
    roles = _management_roles(db, actor)
    if session is None:
        raise ScopeViolation("experiment session is not accessible")
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    if assignment is None:
        raise ScopeViolation("experiment session recorded class is unknown")
    if (
        "admin" not in roles
        and db.scalar(
            select(TeachingAssignment.id).where(
                TeachingAssignment.user_id == actor.id,
                TeachingAssignment.class_id == assignment.class_id,
            )
        )
        is None
    ):
        raise ScopeViolation("experiment session recorded class is not accessible")


def list_managed_sessions(db, actor):
    roles = _management_roles(db, actor)
    query = (
        select(ExperimentSession)
        .join(ExperimentAssignment)
        .where(ExperimentSession.status == "active", ExperimentSession.ended_at.is_(None))
    )
    if "admin" not in roles:
        query = query.where(
            select(TeachingAssignment.id)
            .where(
                TeachingAssignment.user_id == actor.id,
                TeachingAssignment.class_id == ExperimentAssignment.class_id,
            )
            .exists()
        )
    result = []
    for session in db.scalars(query.order_by(ExperimentSession.started_at, ExperimentSession.id)):
        result.append(managed_session_summary(db, session))
    return result


def release_session(db, actor, *, session_id, request_id, expected_version, reason):
    reason = reason.strip()
    if not reason or len(reason) > 1000:
        raise ValueError("release reason must contain 1 to 1000 characters")
    digest = _digest(
        {
            "action": "release",
            "session_id": session_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    with _command_lock(db, actor, "assignment.manage") as user:
        replay = _replay(db, user, request_id, digest, managed=True)
        if replay is not None:
            db.commit()
            return replay
        session = db.get(ExperimentSession, session_id)
        assert_session_management(db, user, session)
        db.scalar(select(Device).where(Device.id == session.device_id).with_for_update())
        db.refresh(session)
        # Recheck authority after waiting; ownership never comes from today's binding.
        assert_session_management(db, user, session)
        from app.services.auth import current_actor

        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        authorize_teacher_class(db, current_actor(user), assignment.class_id, "assignment.manage")
        if session.version_no != expected_version or session.status != "active" or session.ended_at:
            raise ScopeConflict("session state changed; refresh before releasing")
        old_version = session.version_no
        session.status = "cancelled"
        session.ended_at = utc_now()
        session.version_no += 1
        return _record(
            db,
            user,
            session,
            request_id,
            digest,
            "experiment_session.release",
            details={
                "reason": reason,
                "previous_status": "active",
                "previous_version": old_version,
                "status": "cancelled",
            },
        )


def managed_session_summary(db, session):
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    student = db.get(User, session.student_user_id)
    classroom = db.get(Classroom, assignment.class_id)
    return {
        **session_summary(db, session),
        "student_name": student.display_name,
        "class_name": classroom.name,
        "started_at": session.started_at.isoformat(),
    }
