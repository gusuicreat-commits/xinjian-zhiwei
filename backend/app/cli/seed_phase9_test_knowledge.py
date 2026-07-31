"""Idempotently install the explicitly synthetic Phase 9 acceptance knowledge fixture."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeDocument, KnowledgeSource
from app.schemas.knowledge import (
    KnowledgeEmbeddingItem,
    KnowledgeEmbeddingUpsertRequest,
    KnowledgeReviewRequest,
    KnowledgeSourceCreate,
    KnowledgeTextImportRequest,
)
from app.services.knowledge import (
    create_source,
    import_text_document,
    review_document,
    upsert_embeddings,
)

SOURCE_KEY = "phase9.synthetic-acceptance"
TEST_VECTOR_PROVIDER = "phase9-test-vector"
TEST_VECTOR_MODEL = "deterministic-fixture-v1"

CASES = (
    {
        "title": "DHT11 读取失败测试案例",
        "content": (
            "测试知识：DHT11 实验出现 SENSOR_READ_FAILED。"
            "自然语言现象可以描述为“温湿度传感器一直读不到数据”。"
            "先保留错误日志，核对设备仍在线，再按通用供电、连接、配置和读取时序方向"
            "逐项排查。该内容只用于 Phase 9 自动化验收，不是正式课程知识。"
        ),
        "metadata": {
            "experiment_id": "DHT11",
            "error_code": "SENSOR_READ_FAILED",
            "device_type": "ESP32",
            "case_kind": "synthetic_acceptance",
        },
        "vector": [1.0, 0.0, 0.0, 0.0],
    },
    {
        "title": "设备离线测试案例",
        "content": (
            "测试知识：DEVICE_OFFLINE 表示设备最后上报时间超过示例规则窗口。"
            "应先确认设备运行状态、最后心跳与通用网络可达性，不能直接断言硬件损坏。"
            "该内容只用于 Phase 9 自动化验收。"
        ),
        "metadata": {
            "experiment_id": "generic-connectivity",
            "error_code": "DEVICE_OFFLINE",
            "device_type": "generic",
            "case_kind": "synthetic_acceptance",
        },
        "vector": [0.0, 1.0, 0.0, 0.0],
    },
    {
        "title": "温湿度越界测试案例",
        "content": (
            "测试知识：VALUE_OUT_OF_RANGE 表示采集值超出当前实验模板配置范围。"
            "应核对温湿度读数、单位和上下界，并区分单次波动、持续越界与设备离线。"
            "该内容只用于 Phase 9 自动化验收。"
        ),
        "metadata": {
            "experiment_id": "DHT11",
            "error_code": "VALUE_OUT_OF_RANGE",
            "device_type": "ESP32",
            "case_kind": "synthetic_acceptance",
        },
        "vector": [0.0, 0.0, 1.0, 0.0],
    },
    {
        "title": "LED 无响应无关测试案例",
        "content": (
            "测试知识：LED_NO_RESPONSE 只用于验证无关知识不会在 DHT11 读取失败查询中"
            "排到首位。该内容不是正式课程知识。"
        ),
        "metadata": {
            "experiment_id": "LED",
            "error_code": "LED_NO_RESPONSE",
            "device_type": "generic",
            "case_kind": "synthetic_acceptance",
        },
        "vector": [0.0, 0.0, 0.0, 1.0],
    },
)


def seed() -> dict[str, int | str]:
    settings = get_settings()
    with SessionLocal() as db:
        source = db.scalar(
            select(KnowledgeSource).where(KnowledgeSource.source_key == SOURCE_KEY)
        )
        if source is None:
            source_response = create_source(
                db,
                KnowledgeSourceCreate(
                    source_key=SOURCE_KEY,
                    source_type="synthetic-test-fixture",
                    title="Phase 9 最小测试知识库（非正式资料）",
                    source_uri="test-fixture://phase9/minimal-knowledge",
                    version="phase9-acceptance-v1",
                    license_name="test-only",
                    authorization_scope="仅用于本项目自动化验收，不得作为正式课程资料",
                    metadata={"fixture": "phase9", "formal_knowledge": False},
                    is_test_data=True,
                ),
            )
            source = db.get(KnowledgeSource, source_response.id)
        if source is None:
            raise RuntimeError("Phase 9 test source was not created")

        for case in CASES:
            document_response = import_text_document(
                db,
                source.id,
                KnowledgeTextImportRequest(
                    title=case["title"],
                    content=case["content"],
                    language="zh-CN",
                    storage_uri=f"test-fixture://phase9/{case['metadata']['error_code']}",
                    parser_name="phase9-synthetic-fixture",
                    parser_version="1",
                    locator_prefix={
                        "fixture": "phase9-minimal-knowledge",
                        "case": case["metadata"]["error_code"],
                    },
                    metadata=case["metadata"],
                    organizer_ref="phase9-test-organizer",
                    is_test_data=True,
                ),
                settings,
            )
            document = db.get(KnowledgeDocument, document_response.id)
            if document is None:
                raise RuntimeError("Phase 9 test document was not created")
            if document.review_status != "approved":
                review_steps = {
                    "draft": (
                        "pending",
                        "organizer",
                        "phase9-test-organizer",
                    ),
                    "pending": (
                        "approved",
                        "formal_approver",
                        "phase9-test-formal-approver",
                    ),
                }
                while document.review_status != "approved":
                    decision, reviewer_role, reviewer_ref = review_steps[
                        document.review_status
                    ]
                    review_document(
                        db,
                        document.id,
                        KnowledgeReviewRequest(
                            decision=decision,
                            reviewer_role=reviewer_role,
                            reviewer_ref=reviewer_ref,
                            note="明确标记的合成测试知识，仅用于 Phase 9 验收",
                        ),
                    )
                    db.refresh(document)
            chunks = sorted(document.chunks, key=lambda item: item.chunk_index)
            upsert_embeddings(
                db,
                document.id,
                KnowledgeEmbeddingUpsertRequest(
                    provider=TEST_VECTOR_PROVIDER,
                    model=TEST_VECTOR_MODEL,
                    items=[
                        KnowledgeEmbeddingItem(
                            chunk_id=chunk.id,
                            vector=case["vector"],
                        )
                        for chunk in chunks
                    ],
                    is_test_data=True,
                ),
                settings,
            )
        db.expire_all()
        return {
            "source_key": SOURCE_KEY,
            "sources": db.query(KnowledgeSource)
            .filter(KnowledgeSource.source_key == SOURCE_KEY)
            .count(),
            "documents": db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.source_id == source.id)
            .count(),
            "cases": len(CASES),
        }


def main() -> None:
    print(json.dumps(seed(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
