"""BR-SESSION: one device use at a time, immutable ownership and durable receipts."""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from threading import RLock

from sqlalchemy import or_, select

from app.models import (
    AuditEvent,
    Device,
    DeviceBinding,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentSessionCommand,
    User,
)
from app.models.base import utc_now
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    assert_student_assignment_access,
    assert_student_session_access,
    is_demo_device,
)
from app.services.experiment_packages import load_experiment_package_runtime

_LOCAL_COMMAND_LOCK = RLock()


@contextmanager
def _command_lock(db, actor):
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


def _replay(db, actor, request_id, digest):
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
    assert_student_session_access(db, actor, session, require_active=False)
    return receipt.result_json


def _record(db, actor, session, request_id, digest, action):
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
            details_json={"request_id": str(request_id), "version_no": session.version_no},
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
        assignment = db.get(ExperimentAssignment, assignment_id)
        assert_student_assignment_access(db, user, assignment)
        binding = db.scalar(
            select(DeviceBinding).where(
                DeviceBinding.device_id == device.id,
                DeviceBinding.class_id == assignment.class_id,
                DeviceBinding.student_user_id == user.id,
                DeviceBinding.is_active.is_(True),
                or_(
                    DeviceBinding.experiment_assignment_id == assignment.id,
                    DeviceBinding.experiment_assignment_id.is_(None),
                ),
            )
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
        test_data = bool(user.is_test_data or assignment.is_test_data or is_demo_device(device))
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
        assert_student_session_access(db, user, session, require_active=False)
        if session.version_no != expected_version or session.status != "active" or session.ended_at:
            raise ScopeConflict("session state changed; refresh before ending")
        session.status = reason
        session.ended_at = utc_now()
        session.version_no += 1
        return _record(db, user, session, request_id, digest, "experiment_session.end")
