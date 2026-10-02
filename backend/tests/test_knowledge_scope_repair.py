"""Workspace authentication must not depend on possession of a shared token."""

import pytest
from test_experiment_packages import _admin_headers

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.main import app
from app.models import AuditEvent, KnowledgeChunk, KnowledgeDocument, User
from app.services.rbac import assign_role, ensure_rbac_catalog


def test_shared_token_alone_cannot_create_source(api_context):
    app.dependency_overrides[get_settings] = lambda: Settings(
        review_access_token="synthetic-shared"
    )
    response = api_context["client"].post(
        "/api/v1/knowledge/sources",
        headers={"X-Review-Token": "synthetic-shared"},
        json={
            "source_key": "not-authorized",
            "source_type": "synthetic",
            "title": "synthetic",
            "is_test_data": True,
        },
    )
    assert response.status_code == 401
    from app.models import KnowledgeSource

    with api_context["session_factory"]() as db:
        assert db.query(KnowledgeSource).count() == 0


@pytest.fixture
def workspace(api_context):
    client = api_context["client"]
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        for name in ["scope-a", "scope-b", "scope-reviewer"]:
            user = User(
                username=name,
                display_name="synthetic",
                password_hash=hash_password("synthetic-password", iterations=1000),
                is_test_data=True,
            )
            db.add(user)
            db.flush()
            assign_role(
                db,
                user,
                roles["formal_approver" if name == "scope-reviewer" else "knowledge_organizer"],
            )
        db.commit()
    identities = {}
    for name in ["scope-a", "scope-b", "scope-reviewer"]:
        result = client.post(
            "/api/v1/auth/session", json={"username": name, "password": "synthetic-password"}
        ).json()
        identities[name] = (
            result["user_id"],
            {"Authorization": "Bearer " + result["access_token"]},
        )
    sources = {}
    for name in ["scope-a", "scope-b"]:
        source = client.post(
            "/api/v1/knowledge/sources",
            headers=identities[name][1],
            json={
                "source_key": name,
                "source_type": "synthetic",
                "title": "synthetic",
                "authorization_scope": "test",
                "is_test_data": True,
            },
        )
        assert source.status_code == 201, source.text
        doc = client.post(
            f"/api/v1/knowledge/sources/{source.json()['id']}/documents/text",
            headers=identities[name][1],
            json={
                "title": "synthetic",
                "content": "left content. right content.",
                "is_test_data": True,
            },
        )
        assert doc.status_code == 201, doc.text
        sources[name] = (source.json()["id"], doc.json())
    return client, identities, sources


@pytest.mark.parametrize("action", ["read", "import", "edit", "split", "merge", "delete"])
def test_workspace_cross_source_access_has_no_side_effect(api_context, workspace, action):
    client, identities, sources = workspace
    source, doc = sources["scope-b"]
    chunk = doc["chunks"][0]["id"]
    with api_context["session_factory"]() as db:
        before = (
            db.query(AuditEvent).count(),
            db.query(KnowledgeChunk).count(),
            db.query(KnowledgeDocument).count(),
        )
    requests = {
        "read": ("get", f"/documents/{doc['id']}/workspace", None),
        "import": (
            "post",
            f"/sources/{source}/documents/text",
            {"title": "bad", "content": "bad", "is_test_data": True},
        ),
        "edit": ("patch", f"/chunks/{chunk}", {"content": "unauthorized"}),
        "split": ("post", f"/chunks/{chunk}/split", {"offset": 5}),
        "merge": (
            "post",
            "/chunks/merge",
            {"chunk_ids": [chunk, sources["scope-a"][1]["chunks"][0]["id"]]},
        ),
        "delete": ("delete", f"/chunks/{chunk}", None),
    }
    method, path, payload = requests[action]
    response = client.request(
        method,
        "/api/v1/knowledge" + path,
        headers=identities["scope-a"][1],
        **({"json": payload} if payload else {}),
    )
    assert response.status_code == 404, response.text
    with api_context["session_factory"]() as db:
        assert (
            db.query(AuditEvent).count(),
            db.query(KnowledgeChunk).count(),
            db.query(KnowledgeDocument).count(),
        ) == before
        assert db.get(KnowledgeChunk, chunk).content == "left content. right content."
    listed = client.get("/api/v1/knowledge/sources", headers=identities["scope-a"][1]).json()
    assert [item["id"] for item in listed] == [sources["scope-a"][0]]
    assert (
        client.get("/api/v1/knowledge/status", headers=identities["scope-a"][1]).json()[
            "document_count"
        ]
        == 1
    )


def test_source_grant_revocation_and_independent_review(api_context, workspace):
    client, identities, sources = workspace
    source, doc = sources["scope-a"]
    admin = _admin_headers(api_context)
    url = f"/api/v1/knowledge/sources/{source}/grants/{identities['scope-b'][0]}/organize"
    assert client.put(url, headers=identities["scope-a"][1]).status_code == 403
    assert client.put(url, headers=admin).status_code == 204
    assert (
        client.get(
            f"/api/v1/knowledge/documents/{doc['id']}/workspace", headers=identities["scope-b"][1]
        ).status_code
        == 200
    )
    assert client.delete(url, headers=admin).status_code == 204
    assert (
        client.get(
            f"/api/v1/knowledge/documents/{doc['id']}/workspace", headers=identities["scope-b"][1]
        ).status_code
        == 404
    )
    pending = client.patch(
        f"/api/v1/knowledge/documents/{doc['id']}/review",
        headers=identities["scope-a"][1],
        json={"decision": "pending", "reviewer_role": "organizer", "reviewer_ref": "forged"},
    )
    assert pending.status_code == 200
    reviewer = identities["scope-reviewer"]
    review_url = f"/api/v1/knowledge/documents/{doc['id']}/review"
    body = {"decision": "approved", "reviewer_role": "formal_approver", "reviewer_ref": "forged"}
    assert client.patch(review_url, headers=reviewer[1], json=body).status_code == 404
    assert (
        client.put(
            f"/api/v1/knowledge/sources/{source}/grants/{reviewer[0]}/review", headers=admin
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/knowledge/documents/{doc['id']}/workspace", headers=reviewer[1]
        ).status_code
        == 200
    )
    approved = client.patch(review_url, headers=reviewer[1], json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["reviewer_ref"] == reviewer[0]


def test_source_inventory_is_admin_only_and_contains_no_document_body(api_context, workspace):
    client, identities, sources = workspace
    admin = _admin_headers(api_context)
    path = "/api/v1/knowledge/source-access-inventory"
    assert client.get(path, headers=identities["scope-a"][1]).status_code == 403
    result = client.get(path, headers=admin, params={"limit": 1})
    assert result.status_code == 200
    body = result.json()
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {"id", "source_key", "grant_counts"}
    assert body["items"][0]["grant_counts"] == {"organize": 1, "review": 0}
    assert "left content" not in result.text
    next_page = client.get(
        path,
        headers=admin,
        params={"limit": 1, "after_id": body["next_cursor"]},
    ).json()
    assert next_page["items"][0]["id"] != body["items"][0]["id"]
