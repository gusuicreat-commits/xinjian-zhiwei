from functools import lru_cache
from typing import Any, Literal, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "芯鉴知微 API"
    app_version: str = "0.9.5"
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
    knowledge_embedding_transport: Literal["disabled", "openai-compatible"] = "disabled"
    knowledge_embedding_base_url: Optional[str] = None
    knowledge_embedding_api_key: Optional[str] = None
    ai_transport: Literal["disabled", "openai-compatible"] = "openai-compatible"
    ai_provider: Optional[str] = "deepseek"
    ai_base_url: Optional[str] = "https://api.deepseek.com"
    ai_model: Optional[str] = "deepseek-v4-flash"
    ai_api_key: Optional[str] = None
    ai_thinking_enabled: bool = False
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 1
    ai_prompt_version: str = "phase9.5-v1"
    ai_require_knowledge: bool = True
    ai_knowledge_limit: int = 5
    ai_max_context_items: int = 50
    ai_max_log_items: int = 6
    ai_knowledge_content_max_chars: int = 1000
    diagnosis_episode_window_seconds: int = 300
    ai_enabled: bool = False
    ai_local_enabled: bool = False
    ai_cloud_enabled: bool = False
    ai_local_provider: Optional[str] = None
    ai_local_base_url: Optional[str] = None
    ai_local_model: Optional[str] = None
    ai_local_api_key: Optional[str] = None
    ai_cloud_provider: Optional[str] = None
    ai_cloud_base_url: Optional[str] = None
    ai_cloud_model: Optional[str] = None
    ai_cloud_api_key: Optional[str] = None
    ai_calls_per_episode: int = 2
    ai_calls_per_device_hour: int = 4
    ai_daily_budget: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices(
            "AI_DAILY_BUDGET_CNY",
            "AI_DAILY_BUDGET",
            "ai_daily_budget",
        ),
    )
    ai_input_token_limit: int = Field(
        default=4000,
        validation_alias=AliasChoices(
            "AI_MAX_INPUT_TOKENS",
            "AI_INPUT_TOKEN_LIMIT",
            "ai_input_token_limit",
        ),
    )
    ai_output_token_limit: int = Field(
        default=1000,
        validation_alias=AliasChoices(
            "AI_MAX_OUTPUT_TOKENS",
            "AI_OUTPUT_TOKEN_LIMIT",
            "ai_output_token_limit",
        ),
    )
    ai_output_language: str = "zh-CN"
    ai_max_cost_per_call: Optional[float] = None
    ai_low_confidence_threshold: float = 0.65
    ai_input_cost_per_1k_tokens: Optional[float] = None
    ai_output_cost_per_1k_tokens: Optional[float] = None
    ai_cache_ttl_seconds: int = 86400
    ai_schema_version: str = "phase9-light-v1"
    rag_lexical_top_n: int = 10
    rag_vector_top_n: int = 10
    rag_fused_top_k: int = 5
    rag_rrf_k: int = 60

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

    @field_validator("ai_timeout_seconds")
    @classmethod
    def validate_ai_timeout(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("ai_timeout_seconds must be greater than 0 and at most 120")
        return value

    @field_validator("ai_max_retries")
    @classmethod
    def validate_ai_retries(cls, value: int) -> int:
        if value < 0 or value > 3:
            raise ValueError("ai_max_retries must be between 0 and 3")
        return value

    @field_validator("ai_knowledge_limit")
    @classmethod
    def validate_ai_knowledge_limit(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("ai_knowledge_limit must be between 1 and 20")
        return value

    @field_validator("ai_max_context_items")
    @classmethod
    def validate_ai_context_limit(cls, value: int) -> int:
        if value < 1 or value > 500:
            raise ValueError("ai_max_context_items must be between 1 and 500")
        return value

    @field_validator(
        "diagnosis_episode_window_seconds",
        "ai_calls_per_episode",
        "ai_calls_per_device_hour",
        "ai_input_token_limit",
        "ai_output_token_limit",
        "ai_max_log_items",
        "ai_knowledge_content_max_chars",
        "ai_cache_ttl_seconds",
        "rag_lexical_top_n",
        "rag_vector_top_n",
        "rag_fused_top_k",
        "rag_rrf_k",
    )
    @classmethod
    def validate_positive_phase9_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Phase 9 limits must be positive")
        return value

    @field_validator("ai_max_log_items")
    @classmethod
    def validate_ai_log_limit(cls, value: int) -> int:
        if value < 3 or value > 10:
            raise ValueError("ai_max_log_items must be between 3 and 10")
        return value

    @field_validator("ai_low_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("ai_low_confidence_threshold must be between 0 and 1")
        return value

    @field_validator(
        "ai_daily_budget",
        "ai_max_cost_per_call",
        "ai_input_cost_per_1k_tokens",
        "ai_output_cost_per_1k_tokens",
    )
    @classmethod
    def validate_ai_cost(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("AI cost and budget values must not be negative")
        return value

    @field_validator(
        "knowledge_embedding_dimensions",
        "ai_daily_budget",
        "ai_max_cost_per_call",
        "ai_input_cost_per_1k_tokens",
        "ai_output_cost_per_1k_tokens",
        mode="before",
    )
    @classmethod
    def normalize_optional_numbers(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator(
        "knowledge_embedding_provider",
        "knowledge_embedding_model",
        "knowledge_embedding_base_url",
        "knowledge_embedding_api_key",
        "ai_provider",
        "ai_base_url",
        "ai_model",
        "ai_api_key",
        "ai_local_provider",
        "ai_local_base_url",
        "ai_local_model",
        "ai_local_api_key",
        "ai_cloud_provider",
        "ai_cloud_base_url",
        "ai_cloud_model",
        "ai_cloud_api_key",
        "ai_output_language",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_deepseek_profile(self) -> "Settings":
        if self.ai_provider != "deepseek":
            return self
        if self.ai_base_url != "https://api.deepseek.com":
            raise ValueError(
                "DeepSeek production base URL must be https://api.deepseek.com"
            )
        if self.ai_model != "deepseek-v4-flash":
            raise ValueError(
                "Phase 9.5 production model must be deepseek-v4-flash"
            )
        if self.ai_thinking_enabled:
            raise ValueError("Phase 9.5 DeepSeek profile requires non-thinking mode")
        if self.ai_transport != "openai-compatible":
            raise ValueError(
                "DeepSeek production profile requires openai-compatible transport"
            )
        return self

    @property
    def knowledge_embedding_configured(self) -> bool:
        return bool(
            self.knowledge_embedding_provider
            and self.knowledge_embedding_model
            and self.knowledge_embedding_dimensions
        )

    @property
    def knowledge_embedding_client_configured(self) -> bool:
        return bool(
            self.knowledge_embedding_configured
            and self.knowledge_embedding_transport != "disabled"
            and self.knowledge_embedding_base_url
            and self.knowledge_embedding_api_key
        )

    @property
    def ai_configured(self) -> bool:
        if not self.ai_enabled:
            return False
        return bool(
            self.production_ai_configured
            or self.local_ai_configured
            or self.cloud_ai_configured
        )

    @property
    def production_ai_configured(self) -> bool:
        return bool(
            self.ai_enabled
            and self.ai_transport != "disabled"
            and self.ai_provider
            and self.ai_base_url
            and self.ai_model
            and self.ai_api_key
        )

    @property
    def local_ai_configured(self) -> bool:
        return bool(
            self.ai_enabled
            and self.ai_local_enabled
            and self.ai_local_provider
            and self.ai_local_base_url
            and self.ai_local_model
        )

    @property
    def cloud_ai_configured(self) -> bool:
        return bool(
            self.ai_enabled
            and self.ai_cloud_enabled
            and self.ai_cloud_provider
            and self.ai_cloud_base_url
            and self.ai_cloud_model
            and self.ai_cloud_api_key
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
