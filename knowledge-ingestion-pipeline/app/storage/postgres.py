from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from app.models import Chunk


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    content: str
    source: str
    metadata: Dict[str, Any]
    similarity: float
    embedding_model: str


class PostgresVectorStore:
    def __init__(self, database_url: str, dimension: int = 1024) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.database_url = database_url
        self.dimension = dimension

    def connect(self):
        connection = psycopg.connect(self.database_url)
        register_vector(connection)
        return connection

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    ocr_required BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    source TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding VECTOR({self.dimension}) NOT NULL,
                    embedding_model TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks(document_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx "
                "ON chunks USING hnsw (embedding vector_cosine_ops)"
            )

    def document_exists(self, document_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM documents WHERE id = %s", (document_id,)
            ).fetchone()
        return row is not None

    def save_document(
        self,
        document_id: str,
        source: str,
        file_type: str,
        content_hash: str,
        metadata: Dict[str, Any],
        ocr_required: bool,
        chunks: Sequence[Chunk],
        replace_existing: bool = False,
    ) -> int:
        with self.connect() as connection:
            if replace_existing:
                connection.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            inserted = connection.execute(
                """
                INSERT INTO documents (id, source, file_type, content_hash, metadata, ocr_required)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (document_id, source, file_type, content_hash, Jsonb(metadata), ocr_required),
            ).fetchone()
            if inserted is None:
                return 0
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO chunks
                        (id, document_id, content, metadata, source, content_hash,
                         embedding, embedding_model)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (
                            chunk.id,
                            chunk.document_id,
                            chunk.content,
                            Jsonb(chunk.metadata),
                            chunk.source,
                            chunk.content_hash,
                            np.asarray(chunk.embedding, dtype=np.float32),
                            chunk.embedding_model,
                        )
                        for chunk in chunks
                    ],
                )
        return len(chunks)

    def search(self, vector: Sequence[float], top_k: int = 5) -> List[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        query_vector = np.asarray(vector, dtype=np.float32)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, content, source, metadata, embedding_model,
                       1 - (embedding <=> %s) AS similarity
                FROM chunks
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vector, query_vector, top_k),
            ).fetchall()
        return [
            SearchResult(
                chunk_id=row[0],
                content=row[1],
                source=row[2],
                metadata=row[3],
                embedding_model=row[4],
                similarity=float(row[5]),
            )
            for row in rows
        ]
