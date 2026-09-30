"""Explicit authenticated fixture actors for protected write service tests."""
from datetime import timedelta
from uuid import uuid4

from app.models.base import utc_now
from app.models.classroom import AuthSession
from app.services.auth import ActorContext
from app.services.rbac import assign_role, ensure_rbac_catalog


def authorize_write_fixture(db, actor, role='admin'):
    db.flush()
    assign_role(db, actor, ensure_rbac_catalog(db)[role])
    auth = AuthSession(user_id=actor.id, token_hash=uuid4().hex,
                       expires_at=utc_now() + timedelta(hours=1))
    db.add(auth)
    db.commit()
    actor._actor_context = ActorContext(actor.id, auth.id)
    return actor
