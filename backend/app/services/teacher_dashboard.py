from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.schemas.teacher import (
    TeacherAnomalyItem,
    TeacherDashboardResponse,
    TeacherDeviceStatusSlice,
    TeacherErrorRankingItem,
    TeacherErrorTrendItem,
    TeacherInterventionItem,
    TeacherLogItem,
    TeacherMetricSummary,
    UnconfiguredDataset,
)
from app.services.device_ingest import calculate_device_status


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_teacher_dashboard(db: Session) -> TeacherDashboardResponse:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    devices = db.scalars(select(Device).order_by(Device.device_key)).all()
    diagnoses = db.scalars(
        select(DiagnosisResult).order_by(
            DiagnosisResult.created_at.desc(), DiagnosisResult.id.desc()
        )
    ).all()
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
            )
        )
    anomalies.sort(key=lambda item: item.evaluated_at, reverse=True)

    logs = db.scalars(
        select(DeviceLog).order_by(DeviceLog.occurred_at.desc(), DeviceLog.id.desc()).limit(80)
    ).all()
    interventions = db.scalars(
        select(GuidanceHistory)
        .where(GuidanceHistory.teacher_intervention_required.is_(True))
        .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
        .limit(30)
    ).all()

    return TeacherDashboardResponse(
        generated_at=now,
        data_notice=(
            "统计仅来自当前数据库中的设备、日志、诊断与故障树记录；测试数据保留标识。"
            "学生、班级、实验任务和知识案例尚未建模。"
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
            notice="尚未建立班级、学生与实验任务数据模型，无法计算实验完成率和班级进度。",
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
        interventions=[
            TeacherInterventionItem(
                device_id=record.device.device_key,
                diagnosis_result_id=record.diagnosis_result_id,
                tree_title=record.fault_tree_title,
                failure_count=record.failure_count,
                anomaly_duration_seconds=record.anomaly_duration_seconds,
                created_at=record.created_at,
                is_test_data=record.is_test_data,
            )
            for record in interventions
        ],
        knowledge_cases=UnconfiguredDataset(
            configured=False,
            notice="Phase 8 尚未开始：没有知识案例、Embedding 或 pgvector 知识记录可供审核。",
        ),
    )
