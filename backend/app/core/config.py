from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "芯鉴知微 API"
    app_version: str = "0.6.0"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080"
    database_url: str = (
        "postgresql+psycopg://xinjian_app:TODO_CHANGE_ME@localhost:5432/xinjian_zhiwei"
    )
    device_offline_after_seconds: int = 90
    review_access_token: Optional[str] = None

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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
