from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.classroom import DeviceBinding
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.models.intervention import InterventionCase, InterventionEvent
from app.schemas.teacher import (
    TeacherAnomalyItem,
    TeacherDashboardResponse,
    TeacherDeviceStatusSlice,
    TeacherErrorRankingItem,
    TeacherErrorTrendItem,
    TeacherInterventionItem,
    TeacherKnowledgeSummary,
    TeacherLogItem,
    TeacherMetricSummary,
    UnconfiguredDataset,
)
from app.services.device_ingest import calculate_device_status
from app.services.knowledge import get_knowledge_status


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_teacher_dashboard(
    db: Session,
    *,
    allowed_device_ids: Optional[set[str]] = None,
) -> TeacherDashboardResponse:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    knowledge_status = get_knowledge_status(db, settings)
    device_query = select(Device).order_by(Device.device_key)
    diagnosis_query = select(DiagnosisResult).order_by(
        DiagnosisResult.created_at.desc(), DiagnosisResult.id.desc()
    )
    log_query = select(DeviceLog).order_by(DeviceLog.occurred_at.desc(), DeviceLog.id.desc())
    intervention_query = (
        select(GuidanceHistory)
        .where(GuidanceHistory.teacher_intervention_required.is_(True))
        .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
    )
    intervention_case_query = select(InterventionCase).order_by(
        InterventionCase.created_at.desc(), InterventionCase.id.desc()
    )
    if allowed_device_ids is not None:
        device_query = device_query.where(Device.id.in_(allowed_device_ids))
        diagnosis_query = diagnosis_query.where(DiagnosisResult.device_id.in_(allowed_device_ids))
        log_query = log_query.where(DeviceLog.device_id.in_(allowed_device_ids))
        intervention_query = intervention_query.where(
            GuidanceHistory.device_id.in_(allowed_device_ids)
        )
        intervention_case_query = intervention_case_query.join(
            DiagnosisResult,
            DiagnosisResult.id == InterventionCase.diagnosis_result_id,
        ).where(DiagnosisResult.device_id.in_(allowed_device_ids))
    devices = db.scalars(device_query).all()
    diagnoses = db.scalars(diagnosis_query).all()
    latest_diagnoses: dict[str, DiagnosisResult] = {}
    for diagnosis in diagnoses:
        latest_diagnoses.setdefault(diagnosis.device_id, diagnosis)
    statuses = {
        device.id: calculate_device_status(device, settings.device_offline_after_seconds, now=now)
        for device in devices
    }
    status_counts = Counter(statuses.values())

    anomalous = {
        device_id: diagnosis
        for device_id, diagnosis in latest_diagnoses.items()
        if diagnosis.matched_rules
    }
    error_counts: Counter[str] = Counter()
    error_test_flags: dict[str, list[bool]] = {}
    trend_counts: Counter = Counter()
    trend_start_day = now.date() - timedelta(days=6)
    for diagnosis in diagnoses:
        for match in diagnosis.matched_rules:
            code = str(match.get("error_type") or match.get("rule_id") or "UNKNOWN")
            error_counts[code] += 1
            error_test_flags.setdefault(code, []).append(diagnosis.is_test_data)
            evaluated_at = _as_utc(diagnosis.evaluated_at)
            if evaluated_at.date() >= trend_start_day:
                trend_counts[evaluated_at.date()] += 1

    device_by_id = {device.id: device for device in devices}
    student_bound_device_ids = set(
        db.scalars(
            select(DeviceBinding.device_id).where(
                DeviceBinding.is_active.is_(True),
                DeviceBinding.student_user_id.is_not(None),
            )
        )
    )
    anomalies: list[TeacherAnomalyItem] = []
    for device_id, diagnosis in anomalous.items():
        device = device_by_id.get(device_id)
        if device is None:
            continue
        top_match = sorted(
            diagnosis.matched_rules,
            key=lambda item: int(item.get("priority", 0)),
            reverse=True,
        )[0]
        anomalies.append(
            TeacherAnomalyItem(
                device_id=device.device_key,
                device_name=device.display_name,
                device_status=statuses[device.id],
                latest_error_code=str(
                    top_match.get("error_type") or top_match.get("rule_id") or "UNKNOWN"
                ),
                latest_summary=str(top_match.get("summary") or "规则命中，摘要缺失"),
                evaluated_at=diagnosis.evaluated_at,
                is_test_data=diagnosis.is_test_data,
                student_identity_configured=device.id in student_bound_device_ids,
            )
        )
    anomalies.sort(key=lambda item: item.evaluated_at, reverse=True)

    logs = db.scalars(log_query.limit(80)).all()
    guidance_interventions = db.scalars(intervention_query.limit(30)).all()
    intervention_cases = db.scalars(intervention_case_query.limit(30)).all()
    case_diagnosis_ids = {case.diagnosis_result_id for case in intervention_cases}
    intervention_items: list[TeacherInterventionItem] = []
    for case in intervention_cases:
        diagnosis = db.get(DiagnosisResult, case.diagnosis_result_id)
        if diagnosis is None:
            continue
        device = device_by_id.get(diagnosis.device_id)
        if device is None:
            continue
        guidance = db.scalar(
            select(GuidanceHistory)
            .where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
            .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
            .limit(1)
        )
        request_event = db.scalar(
            select(InterventionEvent)
            .where(
                InterventionEvent.case_id == case.id,
                InterventionEvent.action == "request_help",
            )
            .order_by(InterventionEvent.created_at, InterventionEvent.id)
            .limit(1)
        )
        request_source = (
            request_event.metadata_json.get("source") if request_event is not None else None
        )
        fallback_match = diagnosis.matched_rules[0] if diagnosis.matched_rules else {}
        fallback_title = str(
            (diagnosis.deterministic_explanation or {}).get("title")
            or fallback_match.get("summary")
            or "教师协助请求"
        )
        intervention_items.append(
            TeacherInterventionItem(
                case_id=case.id,
                source=(
                    "student_request"
                    if request_source == "student_device_feedback"
                    else "manual_request"
                ),
                status=case.status,
                version_no=case.version_no,
                assigned_teacher_user_id=case.assigned_teacher_user_id,
                resolution_summary=case.resolution_summary,
                device_id=device.device_key,
                diagnosis_result_id=diagnosis.id,
                tree_title=guidance.fault_tree_title if guidance else fallback_title,
                failure_count=guidance.failure_count if guidance else 1,
                anomaly_duration_seconds=(guidance.anomaly_duration_seconds if guidance else 0),
                created_at=case.created_at,
                is_test_data=case.is_test_data,
                student_identity_configured=diagnosis.device_id in student_bound_device_ids,
            )
        )
    for record in guidance_interventions:
        if record.diagnosis_result_id in case_diagnosis_ids:
            continue
        intervention_items.append(
            TeacherInterventionItem(
                source="automatic_guidance",
                status="recommended",
                device_id=record.device.device_key,
                diagnosis_result_id=record.diagnosis_result_id,
                tree_title=record.fault_tree_title,
                failure_count=record.failure_count,
                anomaly_duration_seconds=record.anomaly_duration_seconds,
                created_at=record.created_at,
                is_test_data=record.is_test_data,
                student_identity_configured=record.device_id in student_bound_device_ids,
            )
        )
    intervention_items.sort(key=lambda item: item.created_at, reverse=True)
    intervention_items = intervention_items[:30]

    return TeacherDashboardResponse(
        generated_at=now,
        data_notice=(
            "统计仅来自当前账号可访问范围内的设备、日志、诊断与故障树记录；"
            "测试数据保留标识。实验完成率尚缺正式任务结果数据；"
            "知识库只展示已登记和审核的数据。"
        ),
        metrics=TeacherMetricSummary(
            online_devices=status_counts["online"],
            offline_devices=status_counts["offline"],
            never_seen_devices=status_counts["never_seen"],
            abnormal_devices=len(anomalous),
            experiment_completion_rate=None,
        ),
        device_status=[
            TeacherDeviceStatusSlice(
                status="online",
                count=sum(
                    1
                    for device in devices
                    if statuses[device.id] == "online" and device.id not in anomalous
                ),
            ),
            TeacherDeviceStatusSlice(
                status="offline",
                count=sum(
                    1
                    for device in devices
                    if statuses[device.id] == "offline" and device.id not in anomalous
                ),
            ),
            TeacherDeviceStatusSlice(
                status="never_seen",
                count=sum(
                    1
                    for device in devices
                    if statuses[device.id] == "never_seen" and device.id not in anomalous
                ),
            ),
            TeacherDeviceStatusSlice(status="abnormal", count=len(anomalous)),
        ],
        error_ranking=[
            TeacherErrorRankingItem(
                error_code=code,
                count=count,
                test_data_only=all(error_test_flags[code]),
            )
            for code, count in error_counts.most_common(8)
        ],
        error_trend=[
            TeacherErrorTrendItem(
                day=trend_start_day + timedelta(days=offset),
                count=trend_counts[trend_start_day + timedelta(days=offset)],
            )
            for offset in range(7)
        ],
        class_progress=UnconfiguredDataset(
            configured=False,
            notice="班级与设备授权范围已建立，但尚无正式实验任务结果，无法计算完成率。",
        ),
        anomalies=anomalies,
        recent_logs=[
            TeacherLogItem(
                id=log.id,
                device_id=log.device.device_key,
                level=log.level,
                message=log.message,
                event_code=log.event_code,
                occurred_at=log.occurred_at,
                is_test_data=log.is_test_data,
            )
            for log in logs
        ],
        interventions=intervention_items,
        knowledge_cases=TeacherKnowledgeSummary(
            configured=knowledge_status.content_available,
            framework_ready=knowledge_status.framework_ready,
            source_count=knowledge_status.source_count,
            document_count=knowledge_status.document_count,
            pending_review_count=knowledge_status.pending_review_count,
            approved_chunk_count=knowledge_status.approved_chunk_count,
            embedding_count=knowledge_status.embedding_count,
            embedding_provider_configured=knowledge_status.embedding_provider_configured,
            notice=knowledge_status.notice,
        ),
    )
