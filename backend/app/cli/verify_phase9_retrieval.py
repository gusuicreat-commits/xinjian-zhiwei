"""Run read-only Phase 9 hybrid-retrieval acceptance scenarios."""

from __future__ import annotations

import json

from app.ai.clients import DisabledEmbeddingClient
from app.cli.seed_phase9_test_knowledge import (
    TEST_VECTOR_MODEL,
    TEST_VECTOR_PROVIDER,
)
from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.hybrid_retrieval import hybrid_retrieve


class TestFixtureEmbeddingClient:
    provider = TEST_VECTOR_PROVIDER
    model = TEST_VECTOR_MODEL
    dimensions = 4
    configured = True

    def embed(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0, 0.0, 0.0]


def _serialize(result: object) -> list[dict[str, object]]:
    references = result.references
    return [
        {
            "chunk_id": item.chunk_id,
            "source_key": item.source_key,
            "source_version": item.source_version,
            "locator": item.locator,
            "review_status": item.review_status,
            "fusion_score": item.similarity,
            "retrieval_scores": item.retrieval_scores,
            "is_test_data": item.is_test_data,
            "content_preview": item.content[:80],
        }
        for item in references
    ]


def main() -> None:
    settings = Settings()
    with SessionLocal() as db:
        excluded = hybrid_retrieve(
            db,
            "SENSOR_READ_FAILED DHT11",
            settings,
            TestFixtureEmbeddingClient(),
            include_test_data=False,
            metadata_filters={
                "experiment_id": "DHT11",
                "error_code": "SENSOR_READ_FAILED",
                "device_type": "ESP32",
            },
        )
        scenario_a = hybrid_retrieve(
            db,
            "SENSOR_READ_FAILED DHT11",
            settings,
            TestFixtureEmbeddingClient(),
            include_test_data=True,
            metadata_filters={
                "experiment_id": "DHT11",
                "error_code": "SENSOR_READ_FAILED",
                "device_type": "ESP32",
            },
        )
        scenario_b = hybrid_retrieve(
            db,
            "温湿度传感器一直读不到数据",
            settings,
            TestFixtureEmbeddingClient(),
            include_test_data=True,
        )
        scenario_c = hybrid_retrieve(
            db,
            "SENSOR_READ_FAILED",
            settings,
            DisabledEmbeddingClient(),
            include_test_data=True,
        )
    print(
        json.dumps(
            {
                "default_excludes_test_knowledge": len(excluded.references) == 0,
                "scenario_a": _serialize(scenario_a),
                "scenario_b": _serialize(scenario_b),
                "scenario_c": _serialize(scenario_c),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
