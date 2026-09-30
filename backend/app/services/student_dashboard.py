from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.diagnosis.lightweight_schemas import DeviceStateExplanation
from app.knowledge.case_drafting import CaseDraftError, build_case_draft
from app.models.ai_call_record import AICallRecord
from app.models.classroom import ExperimentAssignment, ExperimentSession
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowRun
from app.models.guidance_history import GuidanceHistory
from app.models.intervention import InterventionCase
from app.models.sensor_reading import SensorReading
from app.schemas.student import (
    CurrentTaskSummary,
    StudentDashboardResponse,
    StudentDeviceStatus,
    StudentDiagnosisSummary,
    StudentFeedbackCreate,
    StudentFeedbackItem,
    StudentGuidanceItem,
    StudentInterventionSummary,
    StudentLogItem,
    StudentReadingItem,
)
from app.services.ai_diagnosis import get_ai_status, serialize_ai_call
from app.services.current_advice import bound_explanation_call, project_current_advice
from app.services.data_scope import (
    diagnosis_session,
    find_active_experiment_session,
    resolve_experiment_session,
)
from app.services.device_ingest import calculate_device_status
from app.services.device_state_explanation import build_device_state_explanation
from app.services.diagnosis_episode import apply_episode_feedback, diagnosis_issues, issue_links
from app.services.experiment_packages import teaching_available
from app.services.interventions import ensure_intervention_case, public_resolution_summary


def build_student_dashboard(
    db: Session, device: Device, experiment_session_id: str | None = None
) -> StudentDashboardResponse:
    session = (
        resolve_experiment_session(db, device, experiment_session_id)
        if experiment_session_id is not None
        else find_active_experiment_session(db, device)
    )
    session_id = session.id if session else None
    logs = db.scalars(
        select(DeviceLog)
        .where(DeviceLog.device_id == device.id, DeviceLog.experiment_session_id == session_id)
        .order_by(DeviceLog.occurred_at.desc(), DeviceLog.id.desc())
        .limit(100)
    ).all()
    recent_readings = db.scalars(
        select(SensorReading)
        .where(
            SensorReading.device_id == device.id, SensorReading.experiment_session_id == session_id
        )
        .order_by(SensorReading.observed_at.desc(), SensorReading.id.desc())
        .limit(500)
    ).all()
    readings = list(reversed(recent_readings))
    if session is None:
        logs, readings = [], []
    diagnosis = None
    if session is not None:
        for candidate in db.scalars(
            select(DiagnosisResult)
            .where(DiagnosisResult.device_id == device.id)
            .order_by(DiagnosisResult.created_at.desc(), DiagnosisResult.id.desc())
        ):
            owner = diagnosis_session(db, candidate)
            if owner is not None and owner.id == session.id:
                diagnosis = candidate
                break
    guidance = []
    feedback = None
    ai_call = None
    episode = None
    intervention = None
    if diagnosis is not None:
        guidance = db.scalars(
            select(GuidanceHistory)
            .where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
            .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
        ).all()
        feedback = db.scalar(
            select(DiagnosisFeedback)
            .where(
                DiagnosisFeedback.diagnosis_result_id == diagnosis.id,
                DiagnosisFeedback.experiment_session_id == session_id,
            )
            .order_by(DiagnosisFeedback.created_at.desc(), DiagnosisFeedback.id.desc())
            .limit(1)
        )
        episode = db.scalar(
            select(DiagnosisEpisode)
            .where(DiagnosisEpisode.id == diagnosis.episode_id)
            .order_by(DiagnosisEpisode.updated_at.desc())
            .limit(1)
        )
        intervention = db.scalar(
            select(InterventionCase)
            .where(
                or_(
                    InterventionCase.episode_id == diagnosis.episode_id
                    if diagnosis.episode_id
                    else False,
                    (InterventionCase.diagnosis_result_id == diagnosis.id)
                    & InterventionCase.episode_id.is_(None),
                ),
                InterventionCase.class_id
                == db.get(ExperimentAssignment, session.experiment_assignment_id).class_id,
            )
            .order_by(InterventionCase.updated_at.desc())
            .limit(1)
        )
    interventions = []
    if diagnosis is not None:
        target_ids = [link.episode_id for link in issue_links(db, diagnosis)]
        interventions = list(
            db.scalars(
                select(InterventionCase)
                .where(
                    InterventionCase.episode_id.in_(target_ids),
                    InterventionCase.class_id
                    == db.get(ExperimentAssignment, session.experiment_assignment_id).class_id,
                )
                .order_by(InterventionCase.updated_at.desc(), InterventionCase.id.desc())
            )
        )
    settings = get_settings()
    teaching_ready = diagnosis is None or teaching_available(db, diagnosis)
    if not teaching_ready:
        guidance, ai_call = [], None
    current_output = None
    if diagnosis is not None and teaching_ready:
        workflow = db.scalar(select(DiagnosisWorkflowRun).where(
            DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id,
        ))
        if workflow is not None:
            frozen = workflow.final_result or workflow.review_request
            ai_call = bound_explanation_call(db, workflow, frozen)
            final, request = project_current_advice(db, workflow)
            if final is not None and ai_call is not None:
                current_output = final
            elif request is not None and ai_call is not None:
                # Deliver the validated projection, never a later mutable call.
                current_output = request.get("ai_result")
            if current_output and current_output.get("context_policy_status"):
                current_output = None
                ai_call = None
        else:
            call_id = (diagnosis.ai_enhancement or {}).get("call_record_id")
            ai_call = db.scalar(select(AICallRecord).where(
                AICallRecord.id == call_id,
                AICallRecord.diagnosis_result_id == diagnosis.id,
                AICallRecord.workflow_run_id.is_(None),
                AICallRecord.call_stage.like("explanation%"),
            )) if isinstance(call_id, str) else None
        if workflow is None and ai_call is not None:
            response = serialize_ai_call(ai_call, settings)
            current_output = response.explanation.model_dump() if response.explanation else None
    device_status = calculate_device_status(device, settings.device_offline_after_seconds)
    device_state_explanation = build_device_state_explanation(
        device=device,
        device_status=device_status,
        diagnosis=diagnosis,
        guidance=list(guidance),
        logs=list(reversed(logs)),
        readings=readings,
        ai_output=current_output,
    )
    if not teaching_ready:
        device_state_explanation = DeviceStateExplanation(
            status_title="实验教学建议已暂停",
            status_summary="参考资料已停用、发生变更或无法核验。",
            meaning="历史观察继续保留，旧教学建议不能继续使用。",
            next_step="请保留现场并联系教师，不自动切换到其他实验版本。",
            source="rule",
        )
    return StudentDashboardResponse(
        issues=diagnosis_issues(db, diagnosis) if diagnosis else [],
        generated_at=datetime.now(timezone.utc),
        task=CurrentTaskSummary(
            configured=session is not None,
            title=(
                db.get(ExperimentAssignment, session.experiment_assignment_id).title
                if session
                else None
            ),
            notice=(
                "当前为明确标记的测试实验。"
                if session and session.is_test_data
                else "正在查看当前实验会话。"
                if session
                else "当前没有有效实验会话，尚无可显示的实验数据。"
            ),
        ),
        device=StudentDeviceStatus(
            device_id=device.device_key,
            display_name=device.display_name,
            status=device_status,
            last_seen_at=device.last_seen_at,
            firmware_version=device.firmware_version,
            is_test_fixture=device.device_type in {"test-fixture", "generic-test-fixture"},
        ),
        logs=[
            StudentLogItem(
                id=item.id,
                level=item.level,
                message=item.message,
                event_code=item.event_code,
                occurred_at=item.occurred_at,
                is_test_data=item.is_test_data,
            )
            for item in logs
        ],
        readings=[
            StudentReadingItem(
                id=item.id,
                sensor_type=item.sensor_type,
                metric_key=item.metric_key,
                value=item.value,
                unit=item.unit,
                observed_at=item.observed_at,
                is_test_data=item.is_test_data,
            )
            for item in readings
        ],
        diagnosis=(
            StudentDiagnosisSummary(
                id=diagnosis.id,
                evaluated_at=diagnosis.evaluated_at,
                matches=diagnosis.matched_rules,
                evidence=diagnosis.evidence,
                is_test_data=diagnosis.is_test_data,
                deterministic_result=diagnosis.deterministic_core if teaching_ready else None,
                explanation=diagnosis.deterministic_explanation if teaching_ready else None,
                ai_enhancement=diagnosis.ai_enhancement if teaching_ready else None,
            )
            if diagnosis is not None
            else None
        ),
        guidance=[
            StudentGuidanceItem(
                id=item.id,
                episode_id=item.episode_id,
                tree_id=item.fault_tree_id,
                tree_title=item.fault_tree_title,
                tree_status=item.fault_tree_status,
                hint_level=item.hint_level,
                failure_count=item.failure_count,
                teacher_intervention_required=item.teacher_intervention_required,
                ranked_causes=item.ranked_causes,
                hints=item.hints,
                is_test_data=item.is_test_data,
            )
            for item in guidance
        ],
        feedback=(
            StudentFeedbackItem(
                id=feedback.id,
                episode_id=feedback.episode_id,
                action=feedback.action,
                note=feedback.note,
                is_test_data=feedback.is_test_data,
                created_at=feedback.created_at,
            )
            if feedback is not None
            else None
        ),
        interventions=[
            StudentInterventionSummary(
                id=item.id,
                episode_id=item.episode_id,
                status=item.status,
                version_no=item.version_no,
                assigned_teacher_user_id=item.assigned_teacher_user_id,
                resolution_summary=public_resolution_summary(db, item),
                updated_at=item.updated_at,
            )
            for item in interventions
        ],
        intervention=(
            StudentInterventionSummary(
                id=intervention.id,
                episode_id=intervention.episode_id,
                status=intervention.status,
                version_no=intervention.version_no,
                assigned_teacher_user_id=intervention.assigned_teacher_user_id,
                resolution_summary=public_resolution_summary(db, intervention),
                updated_at=intervention.updated_at,
            )
            if intervention is not None
            else None
        ),
        ai_status=get_ai_status(settings),
        ai_explanation=serialize_ai_call(ai_call, settings) if ai_call is not None else None,
        episode=(
            {
                "id": episode.id,
                "status": episode.status,
                "primary_error_code": episode.primary_error_code,
                "started_at": episode.started_at,
                "last_seen_at": episode.last_seen_at,
                "failure_count": episode.failure_count,
                "current_hint_level": episode.current_hint_level,
                "ai_call_count": episode.ai_call_count,
            }
            if episode is not None
            else None
        ),
        device_state_explanation=device_state_explanation,
    )


def save_student_feedback(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    payload: StudentFeedbackCreate,
    *,
    experiment_session_id: str,
    processing_status: str = "pending",
) -> DiagnosisFeedback:
    record = DiagnosisFeedback(
        device_id=device.id,
        diagnosis_result_id=diagnosis.id,
        episode_id=str(payload.episode_id) if payload.episode_id else None,
        action=payload.action,
        note=payload.note,
        request_id=str(payload.request_id),
        experiment_session_id=experiment_session_id,
        processing_status=processing_status,
        is_test_data=diagnosis.is_test_data,
    )
    db.add(record)
    db.flush()
    apply_episode_feedback(db, diagnosis, record)
    if payload.action == "request_teacher_help":
        session = db.get(ExperimentSession, experiment_session_id)
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        case = ensure_intervention_case(
            db,
            diagnosis,
            class_id=assignment.class_id,
            actor_user_id=session.student_user_id,
            source="student_device_feedback",
            episode_id=record.episode_id,
        )
        if case.class_id != assignment.class_id:
            from app.services.data_scope import ScopeConflict

            raise ScopeConflict("intervention recorded scope conflicts")
    if payload.action == "resolved" and record.episode_id:
        from app.models.intervention import InterventionEvent

        session = db.get(ExperimentSession, experiment_session_id)
        for case in db.scalars(
            select(InterventionCase).where(
                InterventionCase.episode_id == record.episode_id,
                InterventionCase.status.in_(["claimed", "unconfirmed"]),
                InterventionCase.assigned_teacher_user_id.is_not(None),
            )
        ):
            db.add(
                InterventionEvent(
                    case_id=case.id,
                    actor_user_id=session.student_user_id,
                    action="student_reported_resolved",
                    from_status=case.status,
                    to_status=case.status,
                    note="学生报告问题已解决；尚未等同复测恢复。",
                    is_private=False,
                    metadata_json={
                        "feedback_id": record.id,
                        "episode_id": record.episode_id,
                        "recipient_user_id": case.assigned_teacher_user_id,
                    },
                )
            )
    if payload.action == "resolved" and len(issue_links(db, diagnosis)) <= 1:
        guidance = list(
            db.scalars(
                select(GuidanceHistory)
                .where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
                .order_by(GuidanceHistory.fault_tree_id)
            )
        )
        try:
            build_case_draft(
                db,
                diagnosis,
                record,
                guidance,
                commit=False,
            )
        except CaseDraftError:
            # Feedback remains valid even when the diagnosis lacks enough verified
            # facts to create a knowledge draft.
            pass
    db.commit()
    db.refresh(record)
    return record
