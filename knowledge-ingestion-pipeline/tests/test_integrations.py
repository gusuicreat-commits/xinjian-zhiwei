import hashlib
import math
import os

import pytest

from app.embeddings import QwenEmbeddingProvider
from app.models import Chunk
from app.storage import PostgresVectorStore


@pytest.mark.model
@pytest.mark.skipif(os.getenv("RUN_REAL_MODEL_TEST") != "1", reason="real model test disabled")
def test_real_qwen_embedding_provider() -> None:
    provider = QwenEmbeddingProvider(
        os.getenv("KIP_EMBEDDING_MODEL_PATH", "Qwen/Qwen3-Embedding-0.6B"),
        device="auto",
        batch_size=2,
    )
    vectors = provider.embed_documents(["I2C sensor timeout", "检查传感器上拉电阻"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 1024
    assert math.isclose(sum(value * value for value in vectors[0]), 1.0, rel_tol=1e-3)


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_pgvector_idempotency_and_cosine_search() -> None:
    store = PostgresVectorStore(os.environ["TEST_DATABASE_URL"], dimension=1024)
    store.initialize()
    document_id = hashlib.sha256(b"integration-vector-test").hexdigest()
    chunk = Chunk(
        id=f"{document_id}-chunk",
        document_id=document_id,
        content="ESP32 I2C sensor does not acknowledge",
        content_hash=hashlib.sha256(b"chunk").hexdigest(),
        source="integration.txt",
        metadata={"page": 1, "section": "I2C"},
        embedding=[1.0] + [0.0] * 1023,
        embedding_model="fake-1024d",
    )
    try:
        first = store.save_document(
            document_id,
            "integration.txt",
            "txt",
            document_id,
            {},
            False,
            [chunk],
        )
        second = store.save_document(
            document_id,
            "integration.txt",
            "txt",
            document_id,
            {},
            False,
            [chunk],
        )
        replaced = store.save_document(
            document_id,
            "integration.txt",
            "txt",
            document_id,
            {"reprocessed": True},
            False,
            [chunk],
            replace_existing=True,
        )
        results = store.search([1.0] + [0.0] * 1023, top_k=1)
        assert first == 1 and second == 0 and replaced == 1
        assert results[0].chunk_id == chunk.id
        assert results[0].similarity == pytest.approx(1.0)
    finally:
        with store.connect() as connection:
            connection.execute("DELETE FROM documents WHERE id = %s", (document_id,))
