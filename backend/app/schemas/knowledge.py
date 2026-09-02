from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

KnowledgeReviewStatus = Literal[
    "draft",
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    "superseded",
]
KnowledgeReviewerRole = Literal[
    "organizer",
    "formal_approver",
]


class StrictKnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeSourceCreate(StrictKnowledgeModel):
    source_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    source_type: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=300)
    source_uri: Optional[str] = Field(default=None, max_length=1000)
    version: Optional[str] = Field(default=None, max_length=100)
    license_name: Optional[str] = Field(default=None, max_length=200)
    authorization_scope: Optional[str] = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_test_data: bool = False


class KnowledgeSourceResponse(StrictKnowledgeModel):
    id: str
    source_key: str
    source_type: str
    title: str
    source_uri: Optional[str]
    version: Optional[str]
    license_name: Optional[str]
    authorization_scope: Optional[str]
    metadata: dict[str, Any]
    is_test_data: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeTextImportRequest(StrictKnowledgeModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    media_type: str = Field(default="text/plain", min_length=1, max_length=100)
    language: Optional[str] = Field(default=None, max_length=30)
    storage_uri: Optional[str] = Field(default=None, max_length=1000)
    parser_name: str = Field(default="plain-text", min_length=1, max_length=100)
    parser_version: str = Field(default="1", min_length=1, max_length=50)
    locator_prefix: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    organizer_ref: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content_origin: Literal["human", "ai_generated"] = "human"
    is_test_data: bool = False


class KnowledgeFileImportRequest(StrictKnowledgeModel):
    filename: str = Field(min_length=1, max_length=300)
    content_base64: str = Field(min_length=1)
    media_type: str = Field(min_length=1, max_length=150)
    language: Optional[str] = Field(default=None, max_length=30)
    storage_uri: Optional[str] = Field(default=None, max_length=1000)
    locator_prefix: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    organizer_ref: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content_origin: Literal["human", "ai_generated"] = "human"
    is_test_data: bool = False


class KnowledgeChunkWorkspaceItem(StrictKnowledgeModel):
    id: str
    chunk_index: int
    content: str
    content_hash: str
    char_count: int
    locator: dict[str, Any]
    metadata: dict[str, Any]
    review_status: KnowledgeReviewStatus


class KnowledgeWorkspaceResponse(StrictKnowledgeModel):
    document_id: str
    title: str
    review_status: KnowledgeReviewStatus
    chunks: list[KnowledgeChunkWorkspaceItem]


class KnowledgeChunkUpdate(StrictKnowledgeModel):
    content: Optional[str] = Field(default=None, min_length=1)
    metadata: Optional[dict[str, Any]] = None


class KnowledgeChunkSplitRequest(StrictKnowledgeModel):
    offset: int = Field(ge=1)


class KnowledgeChunkMergeRequest(StrictKnowledgeModel):
    chunk_ids: list[str] = Field(min_length=2, max_length=20)


class KnowledgeChunkResponse(StrictKnowledgeModel):
    id: str
    chunk_index: int
    content_hash: str
    char_count: int
    locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: KnowledgeReviewStatus


class KnowledgeDocumentResponse(StrictKnowledgeModel):
    id: str
    source_id: str
    title: str
    media_type: str
    language: Optional[str]
    storage_uri: Optional[str]
    content_hash: str
    parser_name: str
    parser_version: str
    review_status: KnowledgeReviewStatus
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    chunks: list[KnowledgeChunkResponse]
    idempotent_replay: bool = False


class KnowledgeReviewRequest(StrictKnowledgeModel):
    decision: KnowledgeReviewStatus
    reviewer_role: KnowledgeReviewerRole
    reviewer_ref: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=4000)


class KnowledgeReviewResponse(StrictKnowledgeModel):
    document_id: str
    decision: KnowledgeReviewStatus
    reviewer_role: KnowledgeReviewerRole
    reviewer_ref: str
    reviewed_at: datetime
    affected_chunks: int


class KnowledgeStatusResponse(StrictKnowledgeModel):
    framework_ready: bool = True
    content_available: bool
    source_count: int
    document_count: int
    pending_review_count: int
    approved_chunk_count: int
    case_count: int = 0
    approved_case_count: int = 0
    matching_mode: Literal["structured"] = "structured"
    notice: str
