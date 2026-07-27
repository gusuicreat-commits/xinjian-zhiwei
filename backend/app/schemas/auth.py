from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user_id: str
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    is_test_data: bool


class CurrentUserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    is_test_data: bool


class ClassroomSummary(BaseModel):
    id: str
    course_code: str
    course_title: str
    code: str
    name: str
    term: Optional[str]
    access_role: str
    is_test_data: bool


class DeviceAccessSummary(BaseModel):
    device_id: str
    display_name: Optional[str]
    device_type: Optional[str]
    is_test_data: bool
