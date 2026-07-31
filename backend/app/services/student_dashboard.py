from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai_call_record import AICallRecord
from app.models.classroom import DeviceBinding
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
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
from app.services.device_ingest import calculate_device_status
from app.services.interventions import ensure_intervention_case


def build_student_dashboard(db: Session, device: Device) -> StudentDashboardResponse:
    logs = db.scalars(
        select(DeviceLog)
        .where(DeviceLog.device_id == device.id)
        .order_by(DeviceLog.occurred_at.desc(), DeviceLog.id.desc())
        .limit(100)
    ).all()
    recent_readings = db.scalars(
        select(SensorReading)
        .where(SensorReading.device_id == device.id)
        .order_by(SensorReading.observed_at.desc(), SensorReading.id.desc())
        .limit(500)
    ).all()
    readings = list(reversed(recent_readings))
    diagnosis = db.scalar(
        select(DiagnosisResult)
        .where(DiagnosisResult.device_id == device.id)
        .order_by(DiagnosisResult.created_at.desc(), DiagnosisResult.id.desc())
        .limit(1)
    )
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
            .where(DiagnosisFeedback.diagnosis_result_id == diagnosis.id)
            .order_by(DiagnosisFeedback.created_at.desc(), DiagnosisFeedback.id.desc())
            .limit(1)
        )
        ai_call = db.scalar(
            select(AICallRecord)
            .where(AICallRecord.diagnosis_result_id == diagnosis.id)
            .order_by(AICallRecord.created_at.desc(), AICallRecord.id.desc())
            .limit(1)
        )
        episode = db.scalar(
            select(DiagnosisEpisode)
            .where(DiagnosisEpisode.last_diagnosis_result_id == diagnosis.id)
            .order_by(DiagnosisEpisode.updated_at.desc())
            .limit(1)
        )
        intervention = db.scalar(
            select(InterventionCase)
            .where(InterventionCase.diagnosis_result_id == diagnosis.id)
            .order_by(InterventionCase.updated_at.desc())
            .limit(1)
        )
    settings = get_settings()
    return StudentDashboardResponse(
        generated_at=datetime.now(timezone.utc),
        task=CurrentTaskSummary(
            configured=False,
            notice="尚未配置真实学生账号和实验任务；当前仅展示设备测试数据。",
        ),
        device=StudentDeviceStatus(
            device_id=device.device_key,
            display_name=device.display_name,
            status=calculate_device_status(device, settings.device_offline_after_seconds),
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
                deterministic_result=diagnosis.deterministic_core,
                explanation=diagnosis.deterministic_explanation,
                ai_enhancement=diagnosis.ai_enhancement,
            )
            if diagnosis is not None
            else None
        ),
        guidance=[
            StudentGuidanceItem(
                id=item.id,
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
                action=feedback.action,
                note=feedback.note,
                is_test_data=feedback.is_test_data,
                created_at=feedback.created_at,
            )
            if feedback is not None
            else None
        ),
        intervention=(
            StudentInterventionSummary(
                id=intervention.id,
                status=intervention.status,
                version_no=intervention.version_no,
                assigned_teacher_user_id=intervention.assigned_teacher_user_id,
                resolution_summary=intervention.resolution_summary,
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
    )


def save_student_feedback(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    payload: StudentFeedbackCreate,
) -> DiagnosisFeedback:
    record = DiagnosisFeedback(
        device_id=device.id,
        diagnosis_result_id=diagnosis.id,
        action=payload.action,
        note=payload.note,
        is_test_data=diagnosis.is_test_data,
    )
    db.add(record)
    episode = db.scalar(
        select(DiagnosisEpisode)
        .where(
            DiagnosisEpisode.device_id == device.id,
            DiagnosisEpisode.last_diagnosis_result_id == diagnosis.id,
            DiagnosisEpisode.status.in_(("open", "escalated")),
        )
        .order_by(DiagnosisEpisode.updated_at.desc())
        .limit(1)
    )
    if episode is not None:
        if payload.action == "resolved":
            episode.status = "resolved"
            episode.resolved_at = datetime.now(timezone.utc)
            episode.resolution_source = "student_feedback"
        elif payload.action == "request_teacher_help":
            episode.status = "escalated"
            episode.current_hint_level = 4
    if payload.action == "request_teacher_help":
        binding = db.scalar(
            select(DeviceBinding)
            .where(
                DeviceBinding.device_id == device.id,
                DeviceBinding.is_active.is_(True),
                DeviceBinding.student_user_id.is_not(None),
            )
            .order_by(DeviceBinding.created_at)
            .limit(1)
        )
        if binding is not None and binding.student_user_id is not None:
            ensure_intervention_case(
                db,
                diagnosis,
                class_id=binding.class_id,
                actor_user_id=binding.student_user_id,
                source="student_device_feedback",
            )
    db.commit()
    db.refresh(record)
    return record
