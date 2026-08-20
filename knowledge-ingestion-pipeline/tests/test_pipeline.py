from pathlib import Path
from typing import List, Sequence

from app.chunking import StructureChunker
from app.embeddings import EmbeddingProvider
from app.pipeline import IngestionPipeline


class FakeEmbeddings(EmbeddingProvider):
    @property
    def model_name(self) -> str:
        return "fake-3d"

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class MemoryStore:
    def __init__(self) -> None:
        self.documents = {}

    def document_exists(self, document_id: str) -> bool:
        return document_id in self.documents

    def save_document(self, document_id, replace_existing=False, **kwargs) -> int:
        if document_id in self.documents and not replace_existing:
            return 0
        self.documents[document_id] = kwargs
        return len(kwargs["chunks"])


def test_embedding_provider_contract() -> None:
    provider = FakeEmbeddings()
    assert provider.embed_query("abc") == [3.0, 1.0, 0.0]
    assert len(provider.embed_documents(["a", "bb"])) == 2


def test_repeated_file_import_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "manual.txt"
    source.write_text("Reset the peripheral after an I2C timeout.", encoding="utf-8")
    store = MemoryStore()
    pipeline = IngestionPipeline(
        store=store,
        embeddings=FakeEmbeddings(),
        chunker=StructureChunker(chunk_size=100, overlap=10),
        expected_dimension=3,
    )

    first = pipeline.ingest_file(source)
    second = pipeline.ingest_file(source)
    assert first.success and first.chunks == 1 and first.embeddings == 1
    assert second.success and second.duplicate and second.chunks == 0
    assert len(store.documents) == 1


def test_force_reprocesses_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "manual.txt"
    source.write_text("I2C recovery procedure.", encoding="utf-8")
    store = MemoryStore()
    pipeline = IngestionPipeline(
        store=store,
        embeddings=FakeEmbeddings(),
        chunker=StructureChunker(),
        expected_dimension=3,
    )
    pipeline.ingest_file(source)
    forced = pipeline.ingest_file(source, force=True)
    assert forced.success and not forced.duplicate
    assert forced.chunks == 1 and forced.embeddings == 1


def test_one_bad_file_does_not_stop_batch(tmp_path: Path) -> None:
    (tmp_path / "good.txt").write_text("valid", encoding="utf-8")
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x00")
    pipeline = IngestionPipeline(
        store=MemoryStore(),
        embeddings=FakeEmbeddings(),
        chunker=StructureChunker(),
        expected_dimension=3,
    )
    report = pipeline.ingest(tmp_path)
    assert report.files == 2
    assert report.succeeded == 1
    assert report.failed == 1
    assert len(report.errors) == 1
