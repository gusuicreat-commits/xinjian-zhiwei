from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictTeacherModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeacherMetricSummary(StrictTeacherModel):
    online_devices: int
    offline_devices: int
    never_seen_devices: int
    abnormal_devices: int
    experiment_completion_rate: Optional[float]


class TeacherDeviceStatusSlice(StrictTeacherModel):
    status: Literal["online", "offline", "never_seen", "abnormal"]
    count: int


class TeacherErrorRankingItem(StrictTeacherModel):
    error_code: str
    count: int
    test_data_only: bool


class TeacherErrorTrendItem(StrictTeacherModel):
    day: date
    count: int


class UnconfiguredDataset(StrictTeacherModel):
    configured: bool
    notice: str


class TeacherKnowledgeSummary(UnconfiguredDataset):
    framework_ready: bool
    source_count: int
    document_count: int
    pending_review_count: int
    approved_chunk_count: int
    case_count: int = 0
    approved_case_count: int = 0


class TeacherAnomalyItem(StrictTeacherModel):
    device_id: str
    device_name: Optional[str]
    device_status: Literal["online", "offline", "never_seen"]
    latest_error_code: str
    latest_summary: str
    evaluated_at: datetime
    is_test_data: bool
    student_identity_configured: bool = False


class TeacherLogItem(StrictTeacherModel):
    id: str
    device_id: str
    level: str
    message: str
    event_code: Optional[str]
    occurred_at: datetime
    is_test_data: bool


class TeacherInterventionItem(StrictTeacherModel):
    case_id: Optional[str] = None
    source: Literal["student_request", "manual_request", "automatic_guidance"]
    status: Literal[
        "open",
        "claimed",
        "resolved",
        "unconfirmed",
        "closed",
        "recommended",
    ]
    version_no: Optional[int] = None
    assigned_teacher_user_id: Optional[str] = None
    resolution_summary: Optional[str] = None
    device_id: str
    diagnosis_result_id: str
    tree_title: str
    failure_count: int
    anomaly_duration_seconds: int
    created_at: datetime
    is_test_data: bool
    student_identity_configured: bool = False


class TeacherDashboardResponse(StrictTeacherModel):
    generated_at: datetime
    data_notice: str
    metrics: TeacherMetricSummary
    device_status: list[TeacherDeviceStatusSlice]
    error_ranking: list[TeacherErrorRankingItem]
    error_trend: list[TeacherErrorTrendItem]
    class_progress: UnconfiguredDataset
    anomalies: list[TeacherAnomalyItem]
    recent_logs: list[TeacherLogItem]
    interventions: list[TeacherInterventionItem]
    knowledge_cases: TeacherKnowledgeSummary
