"""Typed memory projections and lifecycle gates over existing business truth.

No model calls, implicit promotion, or destructive evidence retention policy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models import (
    AICallRecord,
    DiagnosisEvidence,
    DiagnosisFeedback,
    DiagnosisResult,
    ExperimentVersion,
    KnowledgeCase,
    MemoryEvent,
    MemoryUse,
)


def _json_default(value):
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError("unsupported memory identity value")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_json_default
        ).encode()
    ).hexdigest()


def package_source(version):
    return {
        "kind": "package",
        "id": version.id,
        "version": version.version,
        "hash": version.package_hash,
    }


def case_source(case):
    # Review state is mutable governance; content identity is independent of it.
    content = {
        name: getattr(case, name)
        for name in (
            "experiment_type",
            "error_type",
            "symptom",
            "normal_state",
            "evidence",
            "possible_causes",
            "solution_steps",
            "teacher_notes",
            "facts",
            "root_cause_value",
            "root_cause_status",
            "confirmed_by",
            "confirmed_at",
            "solution_record",
            "source_ref",
            "version",
            "is_test_data",
        )
    }
    return {"kind": "case", "id": case.id, "version": case.version, "hash": digest(content)}


def approved_case(case, *, is_test_data):
    return bool(
        case
        and case.review_status == "approved"
        and case.facts_locked
        and case.quality_check_passed
        and case.root_cause_status == "confirmed"
        and (is_test_data or not case.is_test_data)
    )


def current_source(db, source, *, is_test_data=True):
    """Lock the exact authority until the caller commits/delivers; no text matching."""
    if db.scalar(select(MemoryEvent.id).where(MemoryEvent.source_key == digest(source))):
        return False
    if source.get("kind") in {"package", "package_case"}:
        key = source.get("package_id") or source["id"]
        version = db.scalar(
            select(ExperimentVersion)
            .where(ExperimentVersion.id == key)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            version is None
            or version.status not in {"published", "superseded"}
            or (version.is_test_data and not is_test_data)
            or version.package_hash != source.get("hash")
        ):
            return False
        if source["kind"] == "package" and version.version != source.get("version"):
            return False
        return True
    if source.get("kind") == "case":
        case = db.scalar(
            select(KnowledgeCase)
            .where(KnowledgeCase.id == source["id"])
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return approved_case(case, is_test_data=is_test_data) and case_source(case) == source
    return False


def sources_for_references(db, diagnosis, references):
    sources = []
    version = (
        db.get(ExperimentVersion, diagnosis.experiment_version_id, populate_existing=True)
        if diagnosis.experiment_version_id
        else None
    )
    if version:
        sources.append(package_source(version))
    for ref in references:
        if hasattr(ref, "model_dump"):
            ref = ref.model_dump(mode="json")
        case_id = ref.get("case_id") or ref.get("chunk_id")
        source_version = ref.get("source_version") or (ref.get("metadata") or {}).get(
            "source_version"
        )
        if not case_id:
            continue
        if version:
            sources.append(
                {
                    "kind": "package_case",
                    "id": case_id,
                    "version": source_version,
                    "hash": version.package_hash,
                    "package_id": version.id,
                }
            )
        else:
            case = db.get(KnowledgeCase, case_id, populate_existing=True)
            if case and source_version == case.version:
                sources.append(case_source(case))
            else:
                # Unknown lineage must never be silently rebound to today's content.
                sources.append(
                    {
                        "kind": "unresolved_case",
                        "id": case_id,
                        "version": source_version,
                        "hash": None,
                    }
                )
    return sorted(sources, key=digest)


def record_uses(db, diagnosis, references, *, target_type, target_id, use_kind, sources=None):
    """Idempotent insert within the business transaction, including failed AI attempts."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    selected = sources if sources is not None else sources_for_references(db, diagnosis, references)
    for source in selected:
        key = digest(source)
        identity = digest([key, diagnosis.id, target_type, target_id, use_kind])
        db.execute(
            insert(MemoryUse)
            .values(
                id=identity,
                source_key=key,
                source=source,
                diagnosis_result_id=diagnosis.id,
                target_type=target_type,
                target_id=target_id,
                use_kind=use_kind,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )


def register_stop(db, source, actor, reason):
    """Called under the existing source write lock; transaction owned by caller."""
    key = digest(source)
    event = db.scalar(select(MemoryEvent).where(MemoryEvent.source_key == key))
    if event is None:
        event = MemoryEvent(
            source_key=key,
            source=source,
            actor_user_id=actor.id,
            reason=reason[:2000],
            cache_cleanup_status="pending",
        )
        db.add(event)
        db.flush()
    return event


def diagnosis_sources_available(db, diagnosis):
    uses = list(db.scalars(select(MemoryUse).where(MemoryUse.diagnosis_result_id == diagnosis.id)))
    for source in {row.source_key: row.source for row in uses}.values():
        if not current_source(db, source, is_test_data=diagnosis.is_test_data):
            return False
    # Legacy audits remain useful without inventing relationships or mutating on GET.
    if not uses and not diagnosis.experiment_version_id:
        for record in db.scalars(
            select(AICallRecord).where(AICallRecord.diagnosis_result_id == diagnosis.id)
        ):
            for source in sources_for_references(db, diagnosis, record.knowledge_references):
                if not current_source(db, source, is_test_data=diagnosis.is_test_data):
                    return False
    return True


def references_available(db, diagnosis, references):
    return all(
        current_source(db, source, is_test_data=diagnosis.is_test_data)
        for source in sources_for_references(db, diagnosis, references)
    )


def memory_context(db, workflow):
    """Read-only, bounded public projection. Call only after task authorization."""
    from app.services.experiment_packages import (
        load_experiment_package_runtime,
        teaching_available,
    )

    diagnosis = (
        db.get(DiagnosisResult, workflow.diagnosis_result_id)
        if (workflow.diagnosis_result_id)
        else None
    )
    available = bool(diagnosis and teaching_available(db, diagnosis))
    facts, experiences = [], []
    if available and diagnosis.experiment_version_id:
        runtime = load_experiment_package_runtime(db, diagnosis.experiment_version_id)
        source = package_source(runtime.version)
        # These statements describe the approved configuration, never physical observations.
        facts = [
            {
                "kind": "configuration",
                "subject": "experiment_package",
                "value": {"code": runtime.experiment.code, "version": runtime.version.version},
                "source": source,
                "physical_verification": "not_asserted",
                "is_test_data": runtime.version.is_test_data,
            }
        ]
        for interface in runtime.bundle.hardware.interfaces[:20]:
            facts.append(
                {
                    "kind": "configuration",
                    "subject": interface.id,
                    "value": {"pins": interface.pins},
                    "source": source,
                    "physical_verification": "not_asserted",
                    "is_test_data": runtime.version.is_test_data,
                }
            )
    if available:
        uses = db.scalars(
            select(MemoryUse)
            .where(MemoryUse.diagnosis_result_id == diagnosis.id)
            .order_by(MemoryUse.id)
        )
        seen = set()
        for use in uses:
            if use.source["kind"] in {"case", "package_case"} and use.source_key not in seen:
                seen.add(use.source_key)
                experiences.append(
                    {
                        "source": use.source,
                        "status": "approved_reference",
                        "root_cause_for_this_task": "not_confirmed",
                    }
                )
                if len(experiences) == 20:
                    break
    evidence = (
        list(
            db.scalars(
                select(DiagnosisEvidence.id)
                .where(DiagnosisEvidence.diagnosis_id == diagnosis.id)
                .order_by(DiagnosisEvidence.id)
                .limit(51)
            )
        )
        if diagnosis
        else []
    )
    feedback = (
        list(
            db.scalars(
                select(DiagnosisFeedback)
                .where(
                    DiagnosisFeedback.diagnosis_result_id == diagnosis.id,
                    DiagnosisFeedback.experiment_session_id == workflow.experiment_session_id,
                )
                .order_by(DiagnosisFeedback.created_at.desc(), DiagnosisFeedback.id.desc())
                .limit(21)
            )
        )
        if (diagnosis)
        else []
    )
    session = workflow.experiment_session
    active = session.status == "active" and workflow.status not in {
        "completed",
        "rejected",
        "failed",
    }
    return {
        "contract_version": "memory-v1",
        "available": available,
        "facts": facts,
        "experiences": experiences,
        "working": {
            "workflow_id": workflow.id,
            "session_id": workflow.experiment_session_id,
            "diagnosis_result_id": workflow.diagnosis_result_id,
            "package_version_id": workflow.experiment_version_id,
            "revision": workflow.state_revision,
            "active": active,
            "status": workflow.status,
            "evidence_ids": evidence[:50],
            "evidence_truncated": len(evidence) > 50,
            "feedback": [
                {
                    "id": f.id,
                    "episode_id": f.episode_id,
                    "action": f.action,
                    "source": "student_report",
                    "created_at": f.created_at.isoformat(),
                }
                for f in feedback[:20]
            ],
            "feedback_truncated": len(feedback) > 20,
            "next_step": "contact_teacher" if not available else workflow.current_node,
            "is_test_data": workflow.is_test_data,
        },
    }
