from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictStudentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentSessionResponse(StrictStudentModel):
    device_id: str
    display_name: Optional[str]
    auth_mode: Literal["device_credential_placeholder"]
    notice: str


class CurrentTaskSummary(StrictStudentModel):
    configured: bool
    title: Optional[str] = None
    template_id: Optional[str] = None
    notice: str


class StudentDeviceStatus(StrictStudentModel):
    device_id: str
    display_name: Optional[str]
    status: Literal["online", "offline", "never_seen"]
    last_seen_at: Optional[datetime]
    firmware_version: Optional[str]
    is_test_fixture: bool


class StudentLogItem(StrictStudentModel):
    id: str
    level: str
    message: str
    event_code: Optional[str]
    occurred_at: datetime
    is_test_data: bool


class StudentReadingItem(StrictStudentModel):
    id: str
    sensor_type: str
    metric_key: str
    value: float
    unit: Optional[str]
    observed_at: datetime
    is_test_data: bool


class StudentDiagnosisSummary(StrictStudentModel):
    id: str
    evaluated_at: datetime
    matches: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    is_test_data: bool


class StudentGuidanceItem(StrictStudentModel):
    id: str
    tree_id: str
    tree_title: str
    tree_status: str
    hint_level: int
    failure_count: int
    teacher_intervention_required: bool
    ranked_causes: list[dict[str, Any]]
    hints: list[dict[str, Any]]
    is_test_data: bool


class StudentFeedbackItem(StrictStudentModel):
    id: str
    action: Literal["resolved", "unresolved", "request_teacher_help"]
    note: Optional[str]
    is_test_data: bool
    created_at: datetime


class StudentDashboardResponse(StrictStudentModel):
    generated_at: datetime
    task: CurrentTaskSummary
    device: StudentDeviceStatus
    logs: list[StudentLogItem]
    readings: list[StudentReadingItem]
    diagnosis: Optional[StudentDiagnosisSummary]
    guidance: list[StudentGuidanceItem]
    feedback: Optional[StudentFeedbackItem]


class StudentFeedbackCreate(StrictStudentModel):
    action: Literal["resolved", "unresolved", "request_teacher_help"]
    note: Optional[str] = Field(default=None, max_length=1000)
