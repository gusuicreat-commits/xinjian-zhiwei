from typing import Any

from app.api.dependencies import require_review_access
from app.main import app


def allow_review_access() -> None:
    app.dependency_overrides[require_review_access] = lambda: None


def approve_test_document(client: Any, document_id: str, prefix: str) -> None:
    steps = (
        ("pending", "organizer", f"{prefix}-organizer"),
        (
            "technical_reviewed",
            "technical_reviewer",
            f"{prefix}-technical-reviewer",
        ),
        ("approved", "formal_approver", f"{prefix}-formal-approver"),
    )
    for decision, reviewer_role, reviewer_ref in steps:
        response = client.patch(
            f"/api/v1/knowledge/documents/{document_id}/review",
            json={
                "decision": decision,
                "reviewer_role": reviewer_role,
                "reviewer_ref": reviewer_ref,
                "note": "明确标记的自动化测试审核。",
            },
        )
        assert response.status_code == 200, response.text


def test_knowledge_endpoints_fail_closed_without_review_access(
    api_context: dict[str, Any],
) -> None:
    response = api_context["client"].get("/api/v1/knowledge/status")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "REVIEW_ACCESS_NOT_CONFIGURED"


def test_empty_knowledge_status_is_explicit(api_context: dict[str, Any]) -> None:
    allow_review_access()

    response = api_context["client"].get("/api/v1/knowledge/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["framework_ready"] is True
    assert payload["content_available"] is False
    assert payload["source_count"] == 0
    assert payload["embedding_provider_configured"] is False
    assert "尚未导入" in payload["notice"]


def test_approval_requires_recorded_authorization(api_context: dict[str, Any]) -> None:
    allow_review_access()
    client = api_context["client"]
    source = client.post(
        "/api/v1/knowledge/sources",
        json={
            "source_key": "missing-authorization",
            "source_type": "course_material",
            "title": "未确认授权的测试来源",
            "is_test_data": True,
        },
    ).json()
    document = client.post(
        f"/api/v1/knowledge/sources/{source['id']}/documents/text",
        json={
            "title": "待审核文本",
            "content": "仅用于测试的文本。",
            "organizer_ref": "authorization-test-organizer",
            "is_test_data": True,
        },
    ).json()
    client.patch(
        f"/api/v1/knowledge/documents/{document['id']}/review",
        json={
            "decision": "pending",
            "reviewer_role": "organizer",
            "reviewer_ref": "authorization-test-organizer",
        },
    )
    client.patch(
        f"/api/v1/knowledge/documents/{document['id']}/review",
        json={
            "decision": "technical_reviewed",
            "reviewer_role": "technical_reviewer",
            "reviewer_ref": "authorization-test-technical-reviewer",
        },
    )

    response = client.patch(
        f"/api/v1/knowledge/documents/{document['id']}/review",
        json={
            "decision": "approved",
            "reviewer_role": "formal_approver",
            "reviewer_ref": "authorization-test-formal-approver",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "KNOWLEDGE_AUTHORIZATION_REQUIRED"


def test_test_knowledge_import_review_embedding_and_search_are_traceable(
    api_context: dict[str, Any],
) -> None:
    allow_review_access()
    client = api_context["client"]
    source_response = client.post(
        "/api/v1/knowledge/sources",
        json={
            "source_key": "phase8-test-source",
            "source_type": "verified_case",
            "title": "Phase 8 明确标记的测试资料",
            "source_uri": "test://phase8/source",
            "version": "test-v1",
            "license_name": "test-only",
            "authorization_scope": "仅限自动化测试，不属于真实专业知识。",
            "metadata": {"fixture": True},
            "is_test_data": True,
        },
    )
    assert source_response.status_code == 201
    source = source_response.json()

    content = ("通用实验测试段落。" * 90) + "\n" + ("第二段测试内容。" * 80)
    import_payload = {
        "title": "Phase 8 测试文本",
        "content": content,
        "media_type": "text/plain",
        "language": "zh-CN",
        "storage_uri": "test://phase8/document",
        "locator_prefix": {"section": "test"},
        "organizer_ref": "phase8-test-organizer",
        "is_test_data": True,
    }
    document_response = client.post(
        f"/api/v1/knowledge/sources/{source['id']}/documents/text", json=import_payload
    )
    replay_response = client.post(
        f"/api/v1/knowledge/sources/{source['id']}/documents/text", json=import_payload
    )
    assert document_response.status_code == 201
    assert replay_response.status_code == 201
    document = document_response.json()
    replay = replay_response.json()
    assert len(document["chunks"]) >= 2
    assert replay["id"] == document["id"]
    assert replay["idempotent_replay"] is True
    assert document["chunks"][0]["locator"]["section"] == "test"

    approve_test_document(client, document["id"], "phase8-test")

    embedding_items = [
        {"chunk_id": chunk["id"], "vector": [1.0, index + 0.5, 0.25]}
        for index, chunk in enumerate(document["chunks"])
    ]
    embedding = client.post(
        f"/api/v1/knowledge/documents/{document['id']}/embeddings",
        json={
            "provider": "phase8-test-provider",
            "model": "phase8-test-model",
            "items": embedding_items,
            "is_test_data": True,
        },
    )
    assert embedding.status_code == 200
    assert embedding.json()["stored_count"] == len(document["chunks"])
    assert embedding.json()["dimensions"] == 3

    hidden_test_search = client.post(
        "/api/v1/knowledge/search",
        json={
            "query_embedding": [1.0, 0.5, 0.25],
            "provider": "phase8-test-provider",
            "model": "phase8-test-model",
        },
    )
    visible_test_search = client.post(
        "/api/v1/knowledge/search",
        json={
            "query_embedding": [1.0, 0.5, 0.25],
            "provider": "phase8-test-provider",
            "model": "phase8-test-model",
            "include_test_data": True,
        },
    )
    assert hidden_test_search.status_code == 200
    assert hidden_test_search.json()["results"] == []
    assert visible_test_search.status_code == 200
    result = visible_test_search.json()["results"][0]
    assert result["source_key"] == "phase8-test-source"
    assert result["source_uri"] == "test://phase8/source"
    assert result["source_version"] == "test-v1"
    assert result["is_test_data"] is True

    status_payload = client.get("/api/v1/knowledge/status").json()
    assert status_payload["source_count"] == 1
    assert status_payload["document_count"] == 1
    assert status_payload["approved_chunk_count"] == len(document["chunks"])
    assert status_payload["embedding_count"] == len(document["chunks"])
    assert status_payload["content_available"] is False


def test_real_embeddings_are_rejected_until_provider_is_configured(
    api_context: dict[str, Any],
) -> None:
    allow_review_access()
    client = api_context["client"]
    source = client.post(
        "/api/v1/knowledge/sources",
        json={
            "source_key": "provider-gate-test",
            "source_type": "course_material",
            "title": "Provider 门禁测试来源",
            "authorization_scope": "仅限自动化门禁测试。",
            "is_test_data": True,
        },
    ).json()
    document = client.post(
        f"/api/v1/knowledge/sources/{source['id']}/documents/text",
        json={
            "title": "门禁测试文本",
            "content": "测试文本",
            "organizer_ref": "provider-gate-organizer",
            "is_test_data": True,
        },
    ).json()
    approve_test_document(client, document["id"], "provider-gate")

    response = client.post(
        f"/api/v1/knowledge/documents/{document['id']}/embeddings",
        json={
            "provider": "unconfirmed-provider",
            "model": "unconfirmed-model",
            "items": [{"chunk_id": document["chunks"][0]["id"], "vector": [1.0, 0.5]}],
            "is_test_data": False,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EMBEDDING_PROVIDER_NOT_CONFIGURED"
