"""One durable command, one frozen input, deterministic before/after comparison."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.schemas import DiagnosisContext
from app.models import (
    Device,
    DiagnosisCheck,
    DiagnosisEpisode,
    DiagnosisResult,
    DiagnosisWorkflowRun,
)
from app.services.data_scope import diagnosis_session, resolve_experiment_session
from app.services.diagnosis import build_diagnosis_context, diagnose
from app.services.diagnosis_episode import issue_links
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    WorkflowScopeViolation,
    start_workflow,
    validate_workflow_start,
)
from app.services.experiment_packages import teaching_available


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def sources(context, scope=None):
    rows = {}
    for item in [*context.observations, *context.events]:
        if scope:
            field = "component_id" if scope.get("kind") == "component" else "interface_id"
            if scope.get("kind") not in {"component", "interface"}:
                continue
            if getattr(item, field) not in scope.get("keys", []):
                continue
        if getattr(item, "type", None) == "device_heartbeat":
            continue
        key = f"{item.source}:{item.source_ref}"
        rows[key] = item.model_dump(mode="json")
    # Unmapped error logs still matter, but ordinary heartbeat traffic does not.
    if scope is None:
        for item in context.logs:
            if item.level.upper() in {"ERROR", "CRITICAL"}:
                rows[f"device_log:{item.id}"] = item.model_dump(mode="json")
    return rows


def signature(context):
    outcome = diagnose(context)
    assessment = context.normal_assessment or {}
    return digest(
        {
            "package": context.experiment_package_hash,
            "definition": context.experiment_definition_hash,
            "template": context.experiment_template.model_dump()
            if context.experiment_template
            else None,
            "sources": sources(context),
            "rules": [(m.rule_id, m.error_type) for m in outcome.matches],
            "health": [
                (c.get("check"), c.get("status"), c.get("component_id"), c.get("metric"))
                for c in assessment.get("checks", [])
            ],
        }
    )


def freeze(db, device, session, payload):
    # Separate short repeatable-read transaction: no provider waits or raw context in checkpoints.
    with Session(db.get_bind(), expire_on_commit=False) as snapshot_db:
        if snapshot_db.get_bind().dialect.name == "postgresql":
            snapshot_db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        frozen_device = snapshot_db.get(Device, device.id)
        context = build_diagnosis_context(
            snapshot_db,
            frozen_device,
            evaluated_at=datetime.now(timezone.utc),
            lookback_seconds=payload.lookback_seconds,
            experiment_template=payload.experiment_template,
            experiment_id=payload.experiment_id,
            experiment_version=payload.experiment_version,
            experiment_version_id=payload.experiment_version_id,
            experiment_session_id=session.id,
        )
        context.feedback_scope = {
            "experiment_session_id": session.id,
            "student_user_id": session.student_user_id,
            "device_id": device.id,
        }
        return context


def latest_check(db, session_id):
    return db.scalar(
        select(DiagnosisCheck)
        .where(DiagnosisCheck.session_id == session_id)
        .order_by(DiagnosisCheck.created_at.desc(), DiagnosisCheck.id.desc())
        .limit(1)
    )


def receipt(check):
    return {
        "request_id": check.request_id,
        "status": check.status,
        "baseline_id": check.baseline_id,
        "workflow_id": check.workflow_id,
        "checked_at": check.created_at.isoformat(),
        **(check.result or {}),
        "request_payload": (
            {**check.request_payload, "request_id": check.request_id}
            if check.status == "pending"
            else None
        ),
    }


def comparison(db, check, diagnosis):
    context = DiagnosisContext.model_validate(check.context_snapshot)
    baseline = db.get(DiagnosisResult, check.baseline_id) if check.baseline_id else None
    old = DiagnosisContext.model_validate(baseline.context_snapshot) if baseline else None
    added = set(sources(context)) - (set(sources(old)) if old else set())
    items = []
    summaries = {
        match["error_type"]: match.get("summary", match["error_type"])
        for row in [baseline, diagnosis]
        if row
        for match in row.matched_rules
        if "error_type" in match
    }
    new_links = issue_links(db, diagnosis)
    by_key = {i.issue_key: i for i in new_links}
    for link in issue_links(db, baseline) if baseline else []:
        delta = set(sources(context, link.scope)) - set(sources(old, link.scope))
        state = (
            "verified_recovery"
            if link.episode.resolution_source == "deterministic_recovery"
            and link.episode.resolved_at is not None
            and link.episode.resolved_at.replace(tzinfo=timezone.utc)
            == context.evaluated_at.replace(tzinfo=timezone.utc)
            else "closed_previous_incident"
            if link.issue_key in by_key and by_key[link.issue_key].episode_id != link.episode_id
            else "late_or_unverified"
            if link.issue_key in by_key
            and by_key[link.issue_key].observation_state == "late_or_unverified"
            else "still_detected"
            if link.issue_key in by_key
            and delta
            and set(by_key[link.issue_key].evidence_keys) - set(link.evidence_keys)
            else "prior_evidence_still_matches"
            if link.issue_key in by_key and delta
            else "not_detected_unverified"
            if delta
            else "no_new_related_data"
        )
        items.append(
            {
                "episode_id": link.episode_id,
                "error_type": link.error_type,
                "label": summaries.get(link.error_type, link.error_type),
                "scope": link.scope,
                "observation": state,
                "new_records": len(delta),
                "resolution_source": link.episode.resolution_source,
                "handling_status": link.episode.status,
            }
        )
    old_episodes = {i.episode_id for i in issue_links(db, baseline)} if baseline else set()
    for link in new_links:
        if link.episode_id not in old_episodes:
            items.append(
                {
                    "episode_id": link.episode_id,
                    "error_type": link.error_type,
                    "label": summaries.get(link.error_type, link.error_type),
                    "scope": link.scope,
                    "observation": "newly_detected",
                    "handling_status": link.episode.status,
                    "resolution_source": link.episode.resolution_source,
                }
            )
    times = [
        utc(r.get("observed_at") or r.get("occurred_at")).isoformat()
        for r in sources(context).values()
    ]
    return {
        "diagnosis_result_id": diagnosis.id,
        "new_records": len(added),
        "data_change": "new_records" if added else "monitoring_only",
        "data_window": {
            "earliest": min(times) if times else None,
            "latest": max(times) if times else None,
        },
        "time_notice": "记录时间可能来自设备或服务端回退；不证明发生在修复之后。",
        "normal_assessment": context.normal_assessment,
        "issues": items,
        "is_test_data": diagnosis.is_test_data,
    }


def reused_result(db, previous, baseline_id, diagnosis_id):
    """Reuse evidence conclusions, snapshot handling afresh for this new command."""
    result = deepcopy(previous.result or {})
    # One SELECT reads current state, bypassing any earlier ORM identity snapshot.
    # IDs come from this session's server-owned prior receipt, never from the
    # device's current binding. Keep closed incidents from earlier comparisons.
    states = {
        row.id: (row.status, row.resolution_source)
        for row in db.execute(
            select(
                DiagnosisEpisode.id, DiagnosisEpisode.status, DiagnosisEpisode.resolution_source
            ).where(
                DiagnosisEpisode.id.in_([item["episode_id"] for item in result.get("issues", [])]),
                DiagnosisEpisode.device_id == previous.device_id,
            )
        )
    }
    for item in result.get("issues", []):
        state = states.get(item["episode_id"])
        if state is None:
            raise WorkflowConflict("recorded problem scope changed; refresh before checking again")
        item["handling_status"], item["resolution_source"] = state
        if baseline_id == diagnosis_id:
            item.update(observation="no_new_related_data", new_records=0)
    if baseline_id == diagnosis_id:
        result.update(new_records=0, data_change="none")
    return result


def run_check(db, graph, device, settings, payload, session):
    from app.services.student_feedback import feedback_lock

    # Session-level advisory mutex survives business commits, but holds no row transaction
    # while a provider runs. PostgreSQL releases it if this process/connection dies.
    with feedback_lock(db, "check:" + session.id):
        session_id = session.id
        db.expire_all()
        session = resolve_experiment_session(db, device, session_id)
        canonical = payload.model_dump(mode="json", exclude={"request_id"})
        payload_hash = digest(canonical)
        request_id = str(payload.request_id or uuid4())
        command = db.scalar(
            select(DiagnosisCheck).where(
                DiagnosisCheck.session_id == session.id, DiagnosisCheck.request_id == request_id
            )
        )
        if command:
            if command.payload_hash != payload_hash:
                raise WorkflowConflict("check request identity has different input")
            if command.status in {"completed", "no_new_data"}:
                result = db.get(DiagnosisWorkflowRun, command.workflow_id)
                if result and result.diagnosis_result_id:
                    if not teaching_available(
                        db, db.get(DiagnosisResult, result.diagnosis_result_id)
                    ):
                        raise WorkflowConflict("experiment package is no longer available")
                return result, command
        else:
            previous = latest_check(db, session.id)
            if previous and previous.status == "pending":
                raise WorkflowConflict("confirm the pending check before starting another")
            # The legacy deterministic endpoint also creates legitimate diagnoses.
            # Compare against the newest owned result, not merely the newest graph run.
            latest_diagnosis = next(
                (
                    row
                    for row in db.scalars(
                        select(DiagnosisResult)
                        .where(DiagnosisResult.device_id == device.id)
                        .order_by(DiagnosisResult.created_at.desc(), DiagnosisResult.id.desc())
                    )
                    if (owner := diagnosis_session(db, row)) and owner.id == session.id
                ),
                None,
            )
            baseline_id = payload.baseline_id or (latest_diagnosis.id if latest_diagnosis else None)
            baseline = db.get(DiagnosisResult, baseline_id) if baseline_id else None
            if baseline:
                owner = diagnosis_session(db, baseline)
                if owner is None or owner.id != session.id:
                    raise WorkflowScopeViolation("comparison baseline is outside this session")
            elif baseline_id:
                raise WorkflowScopeViolation("comparison baseline does not exist")
            if payload.target_episode_id and (
                baseline is None
                or payload.target_episode_id
                not in {link.episode_id for link in issue_links(db, baseline)}
            ):
                raise WorkflowScopeViolation("target problem is outside this baseline")
            validate_workflow_start(db, device, payload, session)
            frozen = freeze(db, device, session, payload)
            input_signature = signature(frozen)
            if baseline:
                old_context = DiagnosisContext.model_validate(baseline.context_snapshot)
                links = issue_links(db, baseline)
                from app.services.recovery_evidence import fresh_related_evidence

                frozen.recheck_recovery_allowed = fresh_related_evidence(
                    frozen.model_dump(mode="json"),
                    baseline.context_snapshot,
                    [link.scope for link in links],
                    old_context.evaluated_at,
                    frozen.evaluated_at,
                )
            if (
                previous
                and previous.input_signature == input_signature
                and previous.workflow_id
                and latest_diagnosis
                and latest_diagnosis.id == (previous.result or {}).get("diagnosis_result_id")
                and baseline_id in {previous.baseline_id, latest_diagnosis.id}
            ):
                # Two tabs can refer to the same earlier baseline. Reuse only identical input.
                command = DiagnosisCheck(
                    session_id=session.id,
                    student_user_id=session.student_user_id,
                    device_id=device.id,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    request_payload=canonical,
                    baseline_id=baseline_id,
                    workflow_id=previous.workflow_id,
                    status=(
                        "no_new_data"
                        if baseline_id == (previous.result or {}).get("diagnosis_result_id")
                        else "completed"
                    ),
                    input_signature=input_signature,
                    context_snapshot=frozen.model_dump(mode="json"),
                    result=reused_result(db, previous, baseline_id, latest_diagnosis.id),
                )
                db.add(command)
                db.commit()
                return db.get(DiagnosisWorkflowRun, previous.workflow_id), command
            if (
                payload.baseline_id
                and latest_diagnosis
                and (payload.baseline_id != latest_diagnosis.id)
            ):
                raise WorkflowConflict("baseline changed; refresh before checking again")
            command = DiagnosisCheck(
                session_id=session.id,
                student_user_id=session.student_user_id,
                device_id=device.id,
                request_id=request_id,
                payload_hash=payload_hash,
                request_payload=canonical,
                baseline_id=baseline_id,
                status="pending",
                input_signature=input_signature,
                context_snapshot=frozen.model_dump(mode="json"),
            )
            db.add(command)
            db.commit()
        frozen = DiagnosisContext.model_validate(command.context_snapshot)
        # Waiting for teacher does not block collecting new facts or close their work order.
        awaiting_teacher = db.scalar(
            select(DiagnosisWorkflowRun.id)
            .where(
                DiagnosisWorkflowRun.experiment_session_id == session.id,
                DiagnosisWorkflowRun.status == "waiting_teacher",
            )
            .limit(1)
        )
        effective_settings = (
            settings.model_copy(update={"ai_enabled": False}) if awaiting_teacher else settings
        )
        workflow = start_workflow(
            db,
            graph,
            device,
            effective_settings,
            payload,
            session,
            check=command,
            frozen_context=frozen,
        )
        db.refresh(command)
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
        command.result = comparison(db, command, diagnosis)
        command.status = "completed"
        db.commit()
        return workflow, command
