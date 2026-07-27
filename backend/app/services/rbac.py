from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models.classroom import (
    Permission,
    Role,
    User,
    role_permissions,
    user_roles,
)

ROLE_PERMISSIONS = {
    "student": {"dashboard.read", "feedback.create", "assignment.read"},
    "teacher": {
        "dashboard.read",
        "class.read",
        "assignment.manage",
        "intervention.manage",
    },
    "teaching_assistant": {
        "dashboard.read",
        "class.read",
        "assignment.read",
        "intervention.manage",
    },
    "admin": {
        "dashboard.read",
        "class.read",
        "class.manage",
        "assignment.manage",
        "intervention.manage",
        "user.manage",
    },
    "knowledge_organizer": {"knowledge.organize"},
    "technical_reviewer": {"knowledge.review.technical"},
    "formal_approver": {"knowledge.review.approve"},
}


def ensure_rbac_catalog(db: Session) -> dict[str, Role]:
    permission_codes = sorted(
        {code for values in ROLE_PERMISSIONS.values() for code in values}
    )
    permissions: dict[str, Permission] = {}
    for code in permission_codes:
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=f"RBAC permission: {code}")
            db.add(permission)
            db.flush()
        permissions[code] = permission

    roles: dict[str, Role] = {}
    for role_code, permission_codes_for_role in ROLE_PERMISSIONS.items():
        role = db.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            role = Role(code=role_code, name=role_code.replace("_", " ").title())
            db.add(role)
            db.flush()
        roles[role_code] = role
        for permission_code in permission_codes_for_role:
            relation = db.execute(
                select(role_permissions).where(
                    role_permissions.c.role_id == role.id,
                    role_permissions.c.permission_id == permissions[permission_code].id,
                )
            ).first()
            if relation is None:
                db.execute(
                    insert(role_permissions).values(
                        role_id=role.id,
                        permission_id=permissions[permission_code].id,
                    )
                )
    return roles


def assign_role(db: Session, user: User, role: Role) -> None:
    relation = db.execute(
        select(user_roles).where(
            user_roles.c.user_id == user.id,
            user_roles.c.role_id == role.id,
        )
    ).first()
    if relation is None:
        db.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )
