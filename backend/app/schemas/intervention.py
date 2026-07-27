from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class InterventionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "claim",
        "note",
        "transfer",
        "resolve",
        "mark_unconfirmed",
        "close",
    ]
    expected_version: int = Field(ge=1)
    note: Optional[str] = Field(default=None, max_length=4000)
    target_teacher_user_id: Optional[str] = None
    is_private: bool = True


class InterventionCaseResponse(BaseModel):
    id: str
    diagnosis_result_id: str
    class_id: Optional[str]
    assigned_teacher_user_id: Optional[str]
    status: str
    version_no: int
    resolution_summary: Optional[str]
    is_test_data: bool


class ClassroomMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: str
    message: str = Field(min_length=1, max_length=4000)
    audience: Literal["class", "affected_students"] = "class"
    is_test_data: bool = False


class ClassroomMessageResponse(BaseModel):
    id: str
    class_id: str
    message: str
    audience: str
    retracted: bool
    is_test_data: bool


class InterventionTimelineItem(BaseModel):
    action: str
    actor_user_id: str
    from_status: Optional[str]
    to_status: Optional[str]
    note: Optional[str]
    is_private: bool
    metadata: dict[str, Any]
    created_at: str
