from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_env() -> None:
    """Load only this project's .env; never walk into a parent project."""
    load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "KIP_DATABASE_URL",
            "postgresql://knowledge:knowledge@localhost:55432/knowledge_ingestion",
        )
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv("KIP_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    )
    embedding_model_path: str = field(
        default_factory=lambda: os.getenv("KIP_EMBEDDING_MODEL_PATH", "")
    )
    embedding_device: str = field(default_factory=lambda: os.getenv("KIP_EMBEDDING_DEVICE", "auto"))
    embedding_batch_size: int = field(default_factory=lambda: _int("KIP_EMBEDDING_BATCH_SIZE", 16))
    embedding_dimension: int = field(default_factory=lambda: _int("KIP_EMBEDDING_DIMENSION", 1024))
    chunk_size: int = field(default_factory=lambda: _int("KIP_CHUNK_SIZE", 1000))
    chunk_overlap: int = field(default_factory=lambda: _int("KIP_CHUNK_OVERLAP", 120))
    query_top_k: int = field(default_factory=lambda: _int("KIP_QUERY_TOP_K", 5))
    pdf_ocr_min_chars_per_page: int = field(
        default_factory=lambda: _int("KIP_PDF_OCR_MIN_CHARS_PER_PAGE", 30)
    )
    pdf_primary_engine: str = field(
        default_factory=lambda: os.getenv("KIP_PDF_PRIMARY_ENGINE", "pdfium")
    )
    pdf_quality_threshold: float = field(
        default_factory=lambda: _float("KIP_PDF_QUALITY_THRESHOLD", 0.65)
    )

    @property
    def model_source(self) -> str:
        return self.embedding_model_path or self.embedding_model
