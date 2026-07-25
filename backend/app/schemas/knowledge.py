import math
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    is_test_data: bool = False


class KnowledgeChunkResponse(StrictKnowledgeModel):
    id: str
    chunk_index: int
    content_hash: str
    char_count: int
    locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: Literal["pending", "approved", "rejected"]


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
    review_status: Literal["pending", "approved", "rejected"]
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    chunks: list[KnowledgeChunkResponse]
    idempotent_replay: bool = False


class KnowledgeReviewRequest(StrictKnowledgeModel):
    decision: Literal["approved", "rejected"]
    reviewer_ref: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=4000)


class KnowledgeReviewResponse(StrictKnowledgeModel):
    document_id: str
    decision: Literal["approved", "rejected"]
    reviewer_ref: str
    reviewed_at: datetime
    affected_chunks: int


class KnowledgeEmbeddingItem(StrictKnowledgeModel):
    chunk_id: str = Field(min_length=1, max_length=36)
    vector: list[float] = Field(min_length=1)

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: list[float]) -> list[float]:
        normalized = [float(item) for item in value]
        if not all(math.isfinite(item) for item in normalized):
            raise ValueError("embedding values must be finite")
        if not any(item != 0 for item in normalized):
            raise ValueError("embedding vector must not be all zero")
        return normalized


class KnowledgeEmbeddingUpsertRequest(StrictKnowledgeModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    items: list[KnowledgeEmbeddingItem] = Field(min_length=1, max_length=500)
    is_test_data: bool = False


class KnowledgeEmbeddingUpsertResponse(StrictKnowledgeModel):
    provider: str
    model: str
    dimensions: int
    stored_count: int


class KnowledgeSearchRequest(StrictKnowledgeModel):
    query_embedding: list[float] = Field(min_length=1)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=50)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    include_test_data: bool = False

    @field_validator("query_embedding")
    @classmethod
    def validate_query_embedding(cls, value: list[float]) -> list[float]:
        return KnowledgeEmbeddingItem(chunk_id="query", vector=value).vector


class KnowledgeSearchResult(StrictKnowledgeModel):
    chunk_id: str
    document_id: str
    document_title: str
    source_id: str
    source_key: str
    source_type: str
    source_title: str
    source_uri: Optional[str]
    source_version: Optional[str]
    content: str
    locator: dict[str, Any]
    similarity: float
    is_test_data: bool


class KnowledgeSearchResponse(StrictKnowledgeModel):
    results: list[KnowledgeSearchResult]
    notice: str


class KnowledgeStatusResponse(StrictKnowledgeModel):
    framework_ready: bool = True
    content_available: bool
    source_count: int
    document_count: int
    pending_review_count: int
    approved_chunk_count: int
    embedding_count: int
    embedding_provider_configured: bool
    configured_provider: Optional[str]
    configured_model: Optional[str]
    configured_dimensions: Optional[int]
    notice: str
