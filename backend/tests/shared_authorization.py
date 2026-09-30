"""Create real grants and a real session for service-level test actors."""

from datetime import timedelta
from uuid import uuid4

from app.models.base import utc_now
from app.models.classroom import (
    AuthSession,
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
)
from app.services.auth import ActorContext
from app.services.rbac import assign_role, ensure_rbac_catalog


def authorize_review_fixture(db, teacher, workflow):
    roles = ensure_rbac_catalog(db)
    assign_role(db, teacher, roles["teacher"])
    session = db.get(ExperimentSession, workflow.experiment_session_id)
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    db.add(TeachingAssignment(class_id=assignment.class_id, user_id=teacher.id))
    auth = AuthSession(
        user_id=teacher.id, token_hash=uuid4().hex, expires_at=utc_now() + timedelta(hours=1)
    )
    db.add(auth)
    db.commit()
    teacher._actor_context = ActorContext(teacher.id, auth.id)
    return teacher._actor_context


def session_actor_fixture(db, user):
    """Authenticate existing grants without adding or expanding permissions."""
    auth = AuthSession(
        user_id=user.id, token_hash=uuid4().hex, expires_at=utc_now() + timedelta(hours=1)
    )
    db.add(auth)
    db.commit()
    user._actor_context = ActorContext(user.id, auth.id)
    return user
