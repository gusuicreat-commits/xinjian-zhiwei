from __future__ import annotations

import argparse
from pathlib import Path

from app.chunking import StructureChunker
from app.config import Settings, load_project_env
from app.embeddings import QwenEmbeddingProvider
from app.pipeline import IngestionPipeline
from app.storage import PostgresVectorStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import supported documents into pgvector")
    parser.add_argument("path", type=Path, help="A supported file or directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess and transactionally replace an existing document",
    )
    return parser


def main() -> int:
    load_project_env()
    args = build_parser().parse_args()
    if not args.path.exists():
        raise SystemExit(f"Path does not exist: {args.path}")
    settings = Settings()
    store = PostgresVectorStore(settings.database_url, settings.embedding_dimension)
    store.initialize()
    pipeline = IngestionPipeline(
        store=store,
        embeddings=QwenEmbeddingProvider(
            settings.model_source,
            settings.embedding_device,
            settings.embedding_batch_size,
        ),
        chunker=StructureChunker(settings.chunk_size, settings.chunk_overlap),
        pdf_ocr_min_chars_per_page=settings.pdf_ocr_min_chars_per_page,
        pdf_primary_engine=settings.pdf_primary_engine,
        pdf_quality_threshold=settings.pdf_quality_threshold,
        expected_dimension=settings.embedding_dimension,
    )
    report = pipeline.ingest(args.path, force=args.force)
    print(f"文件数量: {report.files}")
    print(f"成功数量: {report.succeeded}")
    print(f"失败数量: {report.failed}")
    print(f"Chunk 数量: {report.chunks}")
    print(f"Embedding 数量: {report.embeddings}")
    print(f"重复数量: {report.duplicates}")
    print("需要 OCR 的文件: " + (", ".join(report.ocr_required_files) or "无"))
    if report.errors:
        print("错误信息:")
        for error in report.errors:
            print(f"- {error}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
