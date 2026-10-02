"""One authorization boundary for every knowledge workspace command.

Lock order: source -> document -> current actor/session/roles -> source grant.
Grant mutations lock the source too; no locks survive file parsing or other I/O.
"""

from sqlalchemy import select

from app.models import AuditEvent, KnowledgeDocument, KnowledgeSource, User
from app.models.base import utc_now
from app.models.knowledge_access import KnowledgeSourceGrant
from app.services.auth import ActorContext, AuthorizationDenied, authorize_actor, user_access

CAPABILITIES = {
    "organize": ("knowledge.organize", "knowledge_organizer"),
    "review": ("knowledge.review.approve", "formal_approver"),
}


def workspace_actor(db, actor, capability):
    permission, role = CAPABILITIES[capability]
    user = authorize_actor(db, actor, permission)
    if role not in user_access(db, user.id)[0]:
        raise AuthorizationDenied()
    return user


def source_scope(db, actor, source_id, capability="organize", *, document_id=None):
    if not isinstance(actor, ActorContext):
        raise AuthorizationDenied(401)
    source = db.scalar(
        select(KnowledgeSource)
        .where(KnowledgeSource.id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if document_id is not None:
        document = db.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id, KnowledgeDocument.source_id == source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if document is None:
            raise AuthorizationDenied(404)
    if capability == "view":
        roles, permissions = user_access(db, actor.user_id)
        capabilities = [
            cap
            for cap, (permission, role) in CAPABILITIES.items()
            if permission in permissions and role in roles
        ]
        if not capabilities:
            workspace_actor(db, actor, "organize")
        for cap in capabilities:
            workspace_actor(db, actor, cap)
    else:
        workspace_actor(db, actor, capability)
        capabilities = [capability]
    grant = db.scalar(
        select(KnowledgeSourceGrant)
        .where(
            KnowledgeSourceGrant.source_id == source_id,
            KnowledgeSourceGrant.user_id == actor.user_id,
            KnowledgeSourceGrant.capability.in_(capabilities),
        )
        .with_for_update(read=True)
    )
    if source is None or grant is None:
        raise AuthorizationDenied(404)
    return source


def document_scope(db, actor, document_id, capability="organize"):
    if not isinstance(actor, ActorContext):
        raise AuthorizationDenied(401)
    source_id = db.scalar(
        select(KnowledgeDocument.source_id).where(KnowledgeDocument.id == document_id)
    )
    if source_id is None:
        raise AuthorizationDenied(404)
    source_scope(db, actor, source_id, capability, document_id=document_id)


def visible_sources(db, actor):
    if not isinstance(actor, ActorContext):
        raise AuthorizationDenied(401)
    roles, permissions = user_access(db, actor.user_id)
    capabilities = [
        cap
        for cap, (permission, role) in CAPABILITIES.items()
        if permission in permissions and role in roles
    ]
    if not capabilities:
        # Recheck session first, maintaining 401 vs 403.
        authorize_actor(db, actor, "knowledge.organize")
        raise AuthorizationDenied()
    for capability in capabilities:
        workspace_actor(db, actor, capability)
    return select(KnowledgeSourceGrant.source_id).where(
        KnowledgeSourceGrant.user_id == actor.user_id,
        KnowledgeSourceGrant.capability.in_(capabilities),
    )


def audit_workspace(
    db, actor, action, resource_type, resource_id, *, details=None, is_test_data=False
):
    db.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            action="knowledge." + action,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=details or {},
            is_test_data=is_test_data,
            created_at=utc_now(),
        )
    )


def set_source_grant(db, actor, source_id, user_id, capability, enabled):
    if capability not in CAPABILITIES:
        raise AuthorizationDenied()
    source = db.scalar(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id).with_for_update()
    )
    admin = authorize_actor(db, actor, "user.manage")
    if "admin" not in user_access(db, admin.id)[0]:
        raise AuthorizationDenied()
    if source is None or db.get(User, user_id) is None:
        raise AuthorizationDenied(404)
    permission, role = CAPABILITIES[capability]
    roles, permissions = user_access(db, user_id)
    if enabled and (role not in roles or permission not in permissions):
        raise AuthorizationDenied()
    row = db.scalar(
        select(KnowledgeSourceGrant)
        .where(
            KnowledgeSourceGrant.source_id == source_id,
            KnowledgeSourceGrant.user_id == user_id,
            KnowledgeSourceGrant.capability == capability,
        )
        .with_for_update()
    )
    if enabled and row is None:
        db.add(KnowledgeSourceGrant(source_id=source_id, user_id=user_id, capability=capability))
    elif not enabled and row is not None:
        db.delete(row)
    else:
        db.commit()
        return
    audit_workspace(
        db,
        actor,
        "source_grant",
        "knowledge_source",
        source_id,
        details={"target_user_id": user_id, "capability": capability, "enabled": enabled},
        is_test_data=source.is_test_data,
    )
    db.commit()
