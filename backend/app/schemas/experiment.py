from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    version: str = Field(min_length=1, max_length=50)
    content: dict[str, Any]
    is_test_data: bool = False


class TemplateContentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]


class TemplateVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=50)
    content: dict[str, Any]


class TemplateStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "pending",
        "approved",
        "published",
        "revoked",
        "deactivated",
        "superseded",
    ]


class TemplateVersionResponse(BaseModel):
    id: str
    template_id: str
    code: str
    title: str
    version: str
    status: str
    content: dict[str, Any]
    content_hash: str
    missing_fields: list[str]
    is_test_data: bool


class ExperimentPackageImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: dict[str, dict[str, Any]]
    is_test_data: bool = False


class ExperimentPackageStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "approved", "published", "revoked", "superseded"]


class ExperimentPackageVersionResponse(BaseModel):
    id: str
    experiment_id: str
    experiment_code: str
    experiment_name: str
    version: str
    schema_version: str
    engine_compatibility: str
    package_hash: str
    status: str
    is_current: bool
    validation_report: dict[str, Any]
    is_test_data: bool
