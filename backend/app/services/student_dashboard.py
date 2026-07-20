from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.models.sensor_reading import SensorReading
from app.schemas.student import (
    CurrentTaskSummary,
    StudentDashboardResponse,
    StudentDeviceStatus,
    StudentDiagnosisSummary,
    StudentFeedbackCreate,
    StudentFeedbackItem,
    StudentGuidanceItem,
    StudentLogItem,
    StudentReadingItem,
)
from app.services.device_ingest import calculate_device_status


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
    db.commit()
    db.refresh(record)
    return record
