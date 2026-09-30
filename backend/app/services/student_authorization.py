"""Runtime student identity references; never persist these in graph checkpoints."""
from dataclasses import dataclass

from sqlalchemy import select

from app.models.classroom import Classroom, ExperimentAssignment, ExperimentSession, User
from app.models.device import Device
from app.services.auth import ActorContext, AuthorizationDenied, authorize_actor
from app.services.data_scope import is_demo_device, is_demo_session, protect_student_scope


@dataclass(frozen=True)
class StudentActorContext:
    device_id: str
    session_id: str
    account: ActorContext | None = None
    demo_device_hash: str | None = None


def authorize_student_actor(
    db, identity, device_id, session_id, *, require_active=True, permission="dashboard.read",
):
    """Lock user then device then session/scope, matching session commands.

    A device credential authorizes only the explicit synthetic demonstration scope.
    Call before source-device locks and commit before any provider invocation.
    """
    if not isinstance(identity, StudentActorContext) or (
        identity.device_id != device_id or identity.session_id != session_id
    ):
        raise AuthorizationDenied(401)
    user = None
    if identity.account is not None:
        user = authorize_actor(db, identity.account, permission)
    elif not identity.demo_device_hash:
        raise AuthorizationDenied(401)
    else:
        recorded = db.get(ExperimentSession, session_id)
        if recorded is None:
            raise AuthorizationDenied(403)
        user = db.scalar(select(User).where(User.id == recorded.student_user_id)
                         .with_for_update(read=True).execution_options(populate_existing=True))
        if user is None or not user.is_active:
            raise AuthorizationDenied(403)
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update()
                       .execution_options(populate_existing=True))
    session = db.scalar(select(ExperimentSession).where(ExperimentSession.id == session_id)
                        .with_for_update(read=True).execution_options(populate_existing=True))
    if device is None or not device.is_active or session is None or session.device_id != device_id:
        raise AuthorizationDenied(403)
    if require_active and (session.status != 'active' or session.ended_at is not None):
        raise AuthorizationDenied(403)
    if identity.account is not None:
        protect_student_scope(db, user, session)
    else:
        if device.token_hash != identity.demo_device_hash or not is_demo_device(device):
            raise AuthorizationDenied(401)
        # Protect the provenance/active rows underlying the demo exception.
        student = user
        if session.student_user_id != student.id:
            raise AuthorizationDenied(403)
        assignment = db.scalar(select(ExperimentAssignment).where(
            ExperimentAssignment.id == session.experiment_assignment_id
        ).with_for_update(read=True).execution_options(populate_existing=True))
        classroom = None
        if assignment is not None:
            classroom = db.scalar(select(Classroom).where(
                Classroom.id == assignment.class_id
            ).with_for_update(read=True).execution_options(populate_existing=True))
        if student is None or not student.is_active or classroom is None or not classroom.is_active:
            raise AuthorizationDenied(403)
        if not is_demo_session(db, session):
            raise AuthorizationDenied(401)
    return session
