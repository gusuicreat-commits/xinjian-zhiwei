from functools import lru_cache
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "芯鉴知微 API"
    app_version: str = "0.8.0"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080"
    database_url: str = (
        "postgresql+psycopg://xinjian_app:TODO_CHANGE_ME@localhost:5432/xinjian_zhiwei"
    )
    device_offline_after_seconds: int = 90
    review_access_token: Optional[str] = None
    knowledge_chunk_size_chars: int = 1200
    knowledge_chunk_overlap_chars: int = 150
    knowledge_max_document_chars: int = 500_000
    knowledge_embedding_provider: Optional[str] = None
    knowledge_embedding_model: Optional[str] = None
    knowledge_embedding_dimensions: Optional[int] = None

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("device_offline_after_seconds")
    @classmethod
    def validate_offline_threshold(cls, value: int) -> int:
        if value < 1:
            raise ValueError("device_offline_after_seconds must be positive")
        return value

    @field_validator("knowledge_chunk_size_chars", "knowledge_max_document_chars")
    @classmethod
    def validate_positive_knowledge_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("knowledge size limits must be positive")
        return value

    @field_validator("knowledge_chunk_overlap_chars")
    @classmethod
    def validate_non_negative_overlap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("knowledge_chunk_overlap_chars must not be negative")
        return value

    @field_validator("knowledge_embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("knowledge_embedding_dimensions must be positive")
        return value

    @field_validator("knowledge_embedding_dimensions", mode="before")
    @classmethod
    def normalize_optional_dimensions(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("knowledge_embedding_provider", "knowledge_embedding_model", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def knowledge_embedding_configured(self) -> bool:
        return bool(
            self.knowledge_embedding_provider
            and self.knowledge_embedding_model
            and self.knowledge_embedding_dimensions
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
