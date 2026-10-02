"""Scoped impact review and fixed, retryable cache cleanup plans."""

from datetime import timezone

from sqlalchemy import exists, select

from app.models import (
    AICallRecord,
    AIExplanationCache,
    AuditEvent,
    DiagnosisResult,
    ExperimentAssignment,
    ExperimentSession,
    MemoryCleanupPlan,
    MemoryEvent,
    MemoryImpactReview,
    MemoryUse,
)
from app.models.base import utc_now
from app.services.auth import AuthorizationDenied, authorize_actor, current_actor, user_access
from app.services.data_scope import authorize_workflow_review
from app.services.memory import digest


class MemoryConflict(ValueError):
    pass


def require_manager(db, actor):
    actor = authorize_actor(db, current_actor(actor), "user.manage")
    roles, _ = user_access(db, actor.id)
    if "admin" not in roles:
        raise AuthorizationDenied()


def can_review_diagnosis(db, actor, diagnosis):
    from app.models import DiagnosisWorkflowRun

    actor = authorize_actor(db, current_actor(actor), "intervention.manage")
    roles, _ = user_access(db, actor.id)
    if "admin" in roles:
        return True
    workflow = db.scalar(
        select(DiagnosisWorkflowRun).where(
            DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id,
            DiagnosisWorkflowRun.device_id == diagnosis.device_id,
        )
    )
    if workflow is None:
        return False
    authorize_workflow_review(db, current_actor(actor), workflow)
    return True


def _scoped_diagnoses(db, actor):
    from app.models import DiagnosisWorkflowRun, TeachingAssignment

    actor = authorize_actor(db, current_actor(actor), "intervention.manage")
    roles, permissions = user_access(db, actor.id)
    if not actor.is_active or not {"teacher", "admin"}.intersection(roles):
        raise PermissionError("classroom review authority is required")
    query = select(DiagnosisResult)
    if "admin" in roles:
        return query
    if "intervention.manage" not in permissions:
        raise PermissionError("classroom review permission is required")
    # Only the recorded workflow/session relationship, never the current device binding.
    return query.where(
        exists(
            select(DiagnosisWorkflowRun.id)
            .join(
                ExperimentSession,
                ExperimentSession.id == DiagnosisWorkflowRun.experiment_session_id,
            )
            .join(
                ExperimentAssignment,
                ExperimentAssignment.id == ExperimentSession.experiment_assignment_id,
            )
            .join(TeachingAssignment, TeachingAssignment.class_id == ExperimentAssignment.class_id)
            .where(
                DiagnosisWorkflowRun.diagnosis_result_id == DiagnosisResult.id,
                DiagnosisWorkflowRun.device_id == DiagnosisResult.device_id,
                ExperimentSession.device_id == DiagnosisResult.device_id,
                ExperimentSession.student_user_id == DiagnosisWorkflowRun.student_user_id,
                TeachingAssignment.user_id == actor.id,
            )
        )
    )


def impact_basis(db, event, diagnosis):
    if event.source["kind"] == "package":
        if diagnosis.experiment_version_id == event.source["id"]:
            return ["bound_package"]
        return []
    # Package snapshots are independent of the legacy global case.
    if diagnosis.experiment_version_id:
        return []
    uses = list(
        db.scalars(
            select(MemoryUse).where(
                MemoryUse.source_key == event.source_key,
                MemoryUse.diagnosis_result_id == diagnosis.id,
            )
        )
    )
    if uses:
        return sorted({item.use_kind for item in uses})
    for call in db.scalars(
        select(AICallRecord).where(AICallRecord.diagnosis_result_id == diagnosis.id)
    ):
        if any(
            (ref.get("case_id") or ref.get("chunk_id")) == event.source["id"]
            and ref.get("source_version") == event.source["version"]
            for ref in call.knowledge_references
        ):
            return ["legacy_version_reference_hash_unknown"]
    return []


def impact_page(db, actor, event, *, after_id="", limit=50):
    # Cursor advances across scanned authorized diagnoses; no hidden cross-class totals.
    rows = list(
        db.scalars(
            _scoped_diagnoses(db, actor)
            .where(DiagnosisResult.id > after_id)
            .order_by(DiagnosisResult.id)
            .limit(limit + 1)
        )
    )
    items = []
    for diagnosis in rows[:limit]:
        basis = impact_basis(db, event, diagnosis)
        if not basis:
            continue
        review = db.scalar(
            select(MemoryImpactReview).where(
                MemoryImpactReview.event_id == event.id,
                MemoryImpactReview.diagnosis_result_id == diagnosis.id,
            )
        )
        items.append(
            {
                "diagnosis_result_id": diagnosis.id,
                "basis": basis,
                "is_test_data": diagnosis.is_test_data,
                "review": None
                if review is None
                else {
                    "id": review.id,
                    "version": review.version,
                    "decision": review.decision,
                    "note": review.note,
                    "reviewer_user_id": review.reviewer_user_id,
                },
            }
        )
    return {
        "items": items,
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "coverage": "explicit_relationships_only",
        "untracked_history": "unknown",
        "delivery_acknowledgement": "not_inferred_from_generation",
        "scope": "current_authorized_classes",
        "package_copies": "require_separate_package_review"
        if event.source["kind"] == "case"
        else "this_exact_package_version",
    }


def review_impact(db, actor, event, diagnosis, *, expected_version, decision, note):
    event = db.scalar(select(MemoryEvent).where(MemoryEvent.id == event.id).with_for_update())
    if not can_review_diagnosis(db, actor, diagnosis):
        raise PermissionError("diagnosis is outside current classroom scope")
    if not impact_basis(db, event, diagnosis):
        raise MemoryConflict("no explicit relationship to this source")
    review = db.scalar(
        select(MemoryImpactReview)
        .where(
            MemoryImpactReview.event_id == event.id,
            MemoryImpactReview.diagnosis_result_id == diagnosis.id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        review
        and review.decision == decision
        and review.note == note
        and (review.reviewer_user_id == actor.id and review.version == expected_version + 1)
    ):
        return review
    if (review.version if review else 0) != expected_version:
        raise MemoryConflict("impact review changed; reload before updating")
    if review is None:
        review = MemoryImpactReview(event_id=event.id, diagnosis_result_id=diagnosis.id, version=0)
        db.add(review)
    review.reviewer_user_id = actor.id
    review.decision = decision
    review.note = note
    review.version += 1
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="memory.impact_review",
            resource_type="diagnosis_result",
            resource_id=diagnosis.id,
            details_json={
                "event_id": event.id,
                "decision": decision,
                "review_version": review.version,
            },
            is_test_data=diagnosis.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    return review


def clear_event_caches(db, actor, event):
    return process_stop_cache(db, event, actor=actor)


def process_stop_cache(db, event, *, actor):
    """Retryable outbox work. Read gates already block use while this is pending."""
    event = db.scalar(
        select(MemoryEvent)
        .where(MemoryEvent.id == event.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    keys = list(
        db.scalars(
            select(MemoryUse.target_id).where(
                MemoryUse.source_key == event.source_key, MemoryUse.target_type == "cache"
            )
        )
    )
    count = 0
    rows = list(
        db.scalars(
            select(AIExplanationCache)
            .where(AIExplanationCache.fingerprint.in_(keys))
            .order_by(AIExplanationCache.id)
            .with_for_update()
        )
    )
    require_manager(db, actor)
    for row in rows:
        db.delete(row)
        count += 1
    # Old cache rows lack exact scope. Source gates protect them; do not guess ID substrings.
    event.cache_cleanup_status = "tracked_caches_cleared"
    db.commit()
    return {
        "deleted": count,
        "status": event.cache_cleanup_status,
        "untracked_copies": "not_confirmed",
        "historical_records_deleted": 0,
    }


def plan_cleanup(db, actor, *, limit=100):
    require_manager(db, actor)
    now = utc_now()
    rows = list(
        db.scalars(
            select(AIExplanationCache)
            .where(AIExplanationCache.expires_at <= now)
            .order_by(AIExplanationCache.expires_at, AIExplanationCache.id)
            .limit(limit)
        )
    )
    targets = [
        {
            "id": row.id,
            "fingerprint": row.fingerprint,
            "expires_at": _utc(row.expires_at).isoformat(),
        }
        for row in rows
    ]
    plan = MemoryCleanupPlan(
        actor_user_id=actor.id, cutoff=now, targets=targets, status="planned", result={}
    )
    db.add(plan)
    db.commit()
    return plan


def _utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def cleanup_manifest(plan):
    return {
        "id": plan.id,
        "status": plan.status,
        "cutoff": plan.cutoff,
        "targets": plan.targets,
        "plan_hash": digest(plan.targets),
        "result": plan.result,
        "blocked_stores": [
            {"store": name, "reason": "retention_policy_not_configured"}
            for name in [
                "evidence",
                "diagnosis",
                "knowledge",
                "guidance",
                "ai_audit",
                "checkpoint",
                "backup",
                "export",
                "external_provider",
            ]
        ],
    }


def execute_cleanup(db, actor, plan, *, expected_hash):
    plan = db.scalar(
        select(MemoryCleanupPlan)
        .where(MemoryCleanupPlan.id == plan.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Acquire all domain locks before the final authorization boundary.
    rows = {
        row.id: row
        for row in db.scalars(
            select(AIExplanationCache)
            .where(AIExplanationCache.id.in_([t["id"] for t in plan.targets]))
            .order_by(AIExplanationCache.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    require_manager(db, actor)
    if plan.actor_user_id != actor.id:
        raise PermissionError("cleanup plan belongs to another operator")
    if digest(plan.targets) != expected_hash:
        raise MemoryConflict("cleanup manifest changed")
    if plan.status == "completed":
        return plan
    results = []
    for target in plan.targets:
        row = rows.get(target["id"])
        result = "already_absent"
        if row is not None:
            if (
                row.fingerprint != target["fingerprint"]
                or _utc(row.expires_at).isoformat() != target["expires_at"]
                or _utc(row.expires_at) > _utc(plan.cutoff)
            ):
                result = "skipped_changed"
            else:
                db.delete(row)
                result = "deleted"
        results.append({"id": target["id"], "result": result})
    db.flush()
    deleted_ids = [r["id"] for r in results if r["result"] == "deleted"]
    if deleted_ids and db.scalar(
        select(AIExplanationCache.id).where(AIExplanationCache.id.in_(deleted_ids)).limit(1)
    ):
        raise MemoryConflict("cache deletion verification failed")
    plan.status = (
        "completed" if not any(r["result"] == "skipped_changed" for r in results) else "partial"
    )
    plan.result = {
        "scope": "expired_online_explanation_cache",
        "items": results,
        "historical_records_deleted": 0,
        "all_copies_deleted": False,
    }
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="memory.cache_cleanup",
            resource_type="memory_cleanup_plan",
            resource_id=plan.id,
            details_json={"plan_hash": expected_hash, "status": plan.status},
            is_test_data=False,
            created_at=utc_now(),
        )
    )
    db.commit()
    return plan


def package_candidates(db, actor, event, *, after_id="", limit=50):
    from app.models import ExperimentVersion

    require_manager(db, actor)
    rows = list(
        db.scalars(
            select(ExperimentVersion)
            .where(ExperimentVersion.id > after_id)
            .order_by(ExperimentVersion.id)
            .limit(limit + 1)
        )
    )
    items = []
    for version in rows[:limit]:
        cases = (version.package_content.get("knowledge/cases.yaml") or {}).get("cases", [])
        from app.experiment_packages.registry import derived_case_matches

        same_case = event.source["kind"] == "case" and any(
            case.get("id") == event.source["id"] and case.get("version") == event.source["version"]
            for case in cases
        )
        derived_case = derived_case_matches(version.package_content, event.source)
        if same_case or derived_case:
            items.append(
                {
                    "version_id": version.id,
                    "version": version.version,
                    "package_hash": version.package_hash,
                    "status": version.status,
                    "basis": (
                        "explicit_derived_source_identity_requires_review"
                        if derived_case
                        else "same_case_id_and_version_origin_requires_review"
                    ),
                    "action": "explicit_package_revocation_required",
                    "is_test_data": version.is_test_data,
                }
            )
    return {
        "items": items,
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "coverage": "explicit_case_identity_and_registered_derivation_candidates_only",
        "renamed_or_unlinked_copies": "unknown",
    }


def event_page(db, actor, *, after_id="", limit=30):
    from sqlalchemy import or_

    scope = _scoped_diagnoses(db, actor)
    roles, _ = user_access(db, actor.id)
    query = select(MemoryEvent).where(MemoryEvent.id > after_id)
    if "admin" not in roles:
        ids = scope.with_only_columns(DiagnosisResult.id)
        used = exists(
            select(MemoryUse.id).where(
                MemoryUse.source_key == MemoryEvent.source_key,
                MemoryUse.diagnosis_result_id.in_(ids),
            )
        )
        bound = exists(
            select(DiagnosisResult.id).where(
                DiagnosisResult.id.in_(ids),
                MemoryEvent.source["kind"].as_string() == "package",
                DiagnosisResult.experiment_version_id == MemoryEvent.source["id"].as_string(),
            )
        )
        query = query.where(or_(used, bound))
    rows = list(db.scalars(query.order_by(MemoryEvent.id).limit(limit + 1)))
    return {
        "items": [
            {
                "id": e.id,
                "source": e.source,
                "reason": e.reason if "admin" in roles else "参考资料已停用，请复核相关诊断。",
                "cache_cleanup_status": e.cache_cleanup_status,
                "created_at": e.created_at,
            }
            for e in rows[:limit]
        ],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "coverage": "explicit_relationships_only",
    }
