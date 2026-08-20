from __future__ import annotations

import argparse

from app.config import Settings, load_project_env
from app.embeddings import QwenEmbeddingProvider
from app.storage import PostgresVectorStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Semantic similarity search without an LLM")
    parser.add_argument("query", help="Natural-language search text")
    parser.add_argument("--top-k", type=int, default=None)
    return parser


def main() -> int:
    load_project_env()
    args = build_parser().parse_args()
    settings = Settings()
    provider = QwenEmbeddingProvider(
        settings.model_source,
        settings.embedding_device,
        settings.embedding_batch_size,
    )
    vector = provider.embed_query(args.query)
    if len(vector) != settings.embedding_dimension:
        raise SystemExit(
            f"Model returned {len(vector)} dimensions; expected {settings.embedding_dimension}"
        )
    store = PostgresVectorStore(settings.database_url, settings.embedding_dimension)
    results = store.search(vector, args.top_k or settings.query_top_k)
    if not results:
        print("未找到 Chunk。请先导入资料。")
        return 0
    for index, result in enumerate(results, start=1):
        location = []
        if result.metadata.get("page") is not None:
            location.append(f"页码: {result.metadata['page']}")
        if result.metadata.get("section"):
            location.append(f"章节: {result.metadata['section']}")
        if result.metadata.get("sheet"):
            location.append(
                f"工作表: {result.metadata['sheet']} / 行: {result.metadata.get('row', '-')}"
            )
        print(f"\n[{index}] 相似度: {result.similarity:.4f}")
        print(f"Chunk ID: {result.chunk_id}")
        print(f"来源: {result.source}")
        if location:
            print(" | ".join(location))
        print("原文:")
        print(result.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
