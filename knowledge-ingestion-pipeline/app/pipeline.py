from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import List

from app.chunking import StructureChunker
from app.embeddings import EmbeddingProvider
from app.models import FileImportResult, ImportReport
from app.parsers import SUPPORTED_EXTENSIONS, get_parser
from app.storage import PostgresVectorStore


class IngestionPipeline:
    def __init__(
        self,
        store: PostgresVectorStore,
        embeddings: EmbeddingProvider,
        chunker: StructureChunker,
        pdf_ocr_min_chars_per_page: int = 30,
        pdf_primary_engine: str = "pdfium",
        pdf_quality_threshold: float = 0.65,
        expected_dimension: int = 1024,
    ) -> None:
        self.store = store
        self.embeddings = embeddings
        self.chunker = chunker
        self.pdf_ocr_min_chars_per_page = pdf_ocr_min_chars_per_page
        self.pdf_primary_engine = pdf_primary_engine
        self.pdf_quality_threshold = pdf_quality_threshold
        self.expected_dimension = expected_dimension

    @staticmethod
    def discover(path: Path) -> List[Path]:
        if path.is_file():
            return [path] if path.suffix.lower() in SUPPORTED_EXTENSIONS else []
        return sorted(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    def ingest(self, input_path: Path, force: bool = False) -> ImportReport:
        report = ImportReport()
        for path in self.discover(input_path):
            report.add(self.ingest_file(path, force=force))
        return report

    def ingest_file(self, path: Path, force: bool = False) -> FileImportResult:
        source = str(path)
        try:
            raw = path.read_bytes()
            file_hash = hashlib.sha256(raw).hexdigest()
            document_id = file_hash
            if not force and self.store.document_exists(document_id):
                return FileImportResult(source=source, success=True, duplicate=True)

            parser = get_parser(
                path,
                self.pdf_ocr_min_chars_per_page,
                self.pdf_primary_engine,
                self.pdf_quality_threshold,
            )
            documents = parser.parse(path)
            ocr_required = any(bool(doc.metadata.get("ocr_required")) for doc in documents)
            chunks = self.chunker.chunk(documents, document_id)
            vectors = self.embeddings.embed_documents([chunk.content for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("Embedding provider returned an unexpected vector count")
            if vectors and any(len(vector) != self.expected_dimension for vector in vectors):
                raise ValueError(
                    "Embedding dimension does not match "
                    f"KIP_EMBEDDING_DIMENSION={self.expected_dimension}"
                )
            embedded = [
                replace(chunk, embedding=vector, embedding_model=self.embeddings.model_name)
                for chunk, vector in zip(chunks, vectors)
            ]
            metadata = {
                "source_path": str(path.resolve()),
                "file_size": len(raw),
                "parsed_units": len(documents),
            }
            saved = self.store.save_document(
                document_id=document_id,
                source=path.name,
                file_type=path.suffix.lower().lstrip("."),
                content_hash=file_hash,
                metadata=metadata,
                ocr_required=ocr_required,
                chunks=embedded,
                replace_existing=force,
            )
            return FileImportResult(
                source=source,
                success=True,
                chunks=saved,
                embeddings=saved,
                duplicate=saved == 0,
                ocr_required=ocr_required,
            )
        except Exception as exc:
            return FileImportResult(source=source, success=False, error=str(exc))
