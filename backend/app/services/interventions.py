from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.classroom import User
from app.models.intervention import InterventionCase, InterventionEvent

TRANSITIONS = {
    ("open", "claim"): "claimed",
    ("claimed", "transfer"): "claimed",
    ("claimed", "resolve"): "resolved",
    ("claimed", "mark_unconfirmed"): "unconfirmed",
    ("unconfirmed", "transfer"): "claimed",
    ("unconfirmed", "close"): "closed",
    ("resolved", "close"): "closed",
}


class InterventionConflict(ValueError):
    pass


def apply_action(
    db: Session,
    case: InterventionCase,
    actor: User,
    *,
    action: str,
    expected_version: int,
    note: Optional[str],
    target_teacher_user_id: Optional[str],
    is_private: bool,
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
            resolution = note
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
            metadata_json={"target_teacher_user_id": target_teacher_user_id},
            created_at=utc_now(),
        )
    )
    db.commit()
    updated = db.get(InterventionCase, case.id)
    if updated is None:
        raise RuntimeError("updated intervention disappeared")
    return updated


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
