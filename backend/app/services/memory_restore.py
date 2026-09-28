"""Explicit stop registry for offline restore preparation; never a serving switch."""

from copy import deepcopy

from sqlalchemy import select

from app.models import AIExplanationCache, ExperimentVersion, KnowledgeCase, MemoryEvent, User
from app.services.memory import case_source, digest, package_source, register_stop


def export_registry(db):
    events = [
        {
            "source": deepcopy(row.source),
            "actor_user_id": row.actor_user_id,
            "reason": "restored_stop_registry",
        }
        for row in db.scalars(select(MemoryEvent).order_by(MemoryEvent.id))
    ]
    payload = {"version": "memory-stop-registry-v1", "events": events}
    return {**payload, "sha256": digest(payload)}


def replay_registry(db, manifest):
    """Apply exact known stops atomically in an isolated restored database.

    Hash verifies integrity, not origin: the operator must supply the latest trusted registry.
    Missing/mismatched subjects block completion instead of guessing or deleting history.
    """
    payload = {key: manifest.get(key) for key in ("version", "events")}
    if payload["version"] != "memory-stop-registry-v1" or digest(payload) != manifest.get("sha256"):
        raise ValueError("stop registry format or integrity mismatch")
    if not isinstance(payload["events"], list):
        raise ValueError("stop registry events must be a list")
    checked = []
    for item in payload["events"]:
        source = item["source"]
        actor = db.get(User, item["actor_user_id"])
        model = {"package": ExperimentVersion, "case": KnowledgeCase}.get(source.get("kind"))
        if model is None or actor is None:
            raise ValueError("restore has an unresolved governance subject or actor")
        row = db.scalar(select(model).where(model.id == source["id"]).with_for_update())
        if row is None:
            raise ValueError("restore has an unresolved governance subject")
        actual = package_source(row) if model is ExperimentVersion else case_source(row)
        if actual != source:
            raise ValueError("restore source identity differs from the stop registry")
        checked.append((row, deepcopy(source), actor))
    for row, source, actor in checked:
        if source["kind"] == "package":
            row.status, row.is_current = "revoked", False
        else:
            row.review_status = "withdrawn"
        register_stop(db, source, actor, "restored_stop_registry")
    # A restored cache may predate provenance; expire all rebuildable entries conservatively.
    # No evidence, audit, guidance snapshot or checkpoint is deleted.
    from sqlalchemy import update

    from app.models.base import utc_now

    if checked:
        db.execute(update(AIExplanationCache).values(expires_at=utc_now()))
    db.commit()
    return {
        "applied": len(checked),
        "historical_records_deleted": 0,
        "serving_authorized": False,
        "remaining": [
            "verify latest registry externally",
            "verify checkpoint restore",
            "verify runtime read gates before serving",
        ],
    }
