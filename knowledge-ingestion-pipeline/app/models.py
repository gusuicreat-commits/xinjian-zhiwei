from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Document:
    """A structure-aware unit emitted by a file parser."""

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A traceable unit ready for embedding and storage."""

    id: str
    document_id: str
    content: str
    content_hash: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    embedding_model: Optional[str] = None


@dataclass
class FileImportResult:
    source: str
    success: bool
    chunks: int = 0
    embeddings: int = 0
    duplicate: bool = False
    ocr_required: bool = False
    error: Optional[str] = None


@dataclass
class ImportReport:
    files: int = 0
    succeeded: int = 0
    failed: int = 0
    chunks: int = 0
    embeddings: int = 0
    duplicates: int = 0
    ocr_required_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def add(self, result: FileImportResult) -> None:
        self.files += 1
        if result.success:
            self.succeeded += 1
        else:
            self.failed += 1
        self.chunks += result.chunks
        self.embeddings += result.embeddings
        self.duplicates += int(result.duplicate)
        if result.ocr_required:
            self.ocr_required_files.append(result.source)
        if result.error:
            self.errors.append(f"{result.source}: {result.error}")
