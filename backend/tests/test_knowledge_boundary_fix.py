"""Independent provenance and document budget contracts from the boundary audit."""

import sys

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.models import AuditEvent, KnowledgeChunk, KnowledgeDocument, KnowledgeSource, User

pytest_plugins = ["test_knowledge_scope_repair"]

def configure(limit=100, **kw):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, knowledge_max_document_chars=limit, **kw
    )


@pytest.mark.parametrize(
    "actor_test,explicit,expected",
    [(False, False, False), (True, False, True), (False, True, True)],
)
def test_source_and_document_provenance(api_context, workspace, actor_test, explicit, expected):
    client, identities, _ = workspace
    uid, headers = identities["scope-a"]
    with api_context["session_factory"]() as db:
        db.get(User, uid).is_test_data = actor_test
        db.commit()
    source = client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        json={
            "source_key": "provenance-control",
            "source_type": "supplementary",
            "title": "synthetic",
            "source_uri": "urn:synthetic",
            "version": "1",
            "authorization_scope": "test",
            "is_test_data": explicit,
        },
    )
    assert source.status_code == 201
    sid = source.json()["id"]
    doc = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/text",
        headers=headers,
        json={
            "title": "synthetic",
            "content": "fixture text",
            "is_test_data": False,
            "metadata": {"applicable_hardware": ["fixture"]},
        },
    )
    assert doc.status_code == 201
    with api_context["session_factory"]() as db:
        assert db.get(KnowledgeSource, sid).is_test_data is expected
        assert db.get(KnowledgeDocument, doc.json()["id"]).is_test_data is expected
        audits = list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.resource_id.in_([sid, doc.json()["id"]]))
            )
        )
        assert audits and all(a.is_test_data is expected for a in audits)


@pytest.mark.parametrize("size,status", [(100, 200), (101, 413), (500001, 413)])
def test_edit_budget_and_no_side_effect(api_context, workspace, size, status):
    configure(500000 if size == 500001 else 100)
    client, identities, sources = workspace
    cid = sources["scope-a"][1]["chunks"][0]["id"]
    with api_context["session_factory"]() as db:
        before = db.get(KnowledgeChunk, cid).content
        audits = db.query(AuditEvent).count()
    response = client.patch(
        f"/api/v1/knowledge/chunks/{cid}",
        headers=identities["scope-a"][1],
        json={"content": "x" * size},
    )
    assert response.status_code == status
    with api_context["session_factory"]() as db:
        assert db.get(KnowledgeChunk, cid).content == ("x" * size if status == 200 else before)
        assert db.query(AuditEvent).count() == audits + (status == 200)


def test_whole_document_and_merge_newline_budget(api_context, workspace):
    configure(100, knowledge_chunk_size_chars=50, knowledge_chunk_overlap_chars=0)
    client, identities, sources = workspace
    headers = identities["scope-a"][1]
    sid = sources["scope-a"][0]
    response = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/text",
        headers=headers,
        json={"title": "two", "content": "x" * 100, "is_test_data": True},
    )
    assert response.status_code == 201
    ids = [c["id"] for c in response.json()["chunks"]]
    assert len(ids) == 2
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{ids[0]}", headers=headers, json={"content": "a" * 51}
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/v1/knowledge/chunks/merge", headers=headers, json={"chunk_ids": ids}
        ).status_code
        == 413
    )
    with api_context["session_factory"]() as db:
        assert sum(len(db.get(KnowledgeChunk, c).content) for c in ids) == 100


def test_test_actor_cannot_mutate_existing_formal_document(api_context, workspace):
    client, identities, sources = workspace
    sid, doc = sources["scope-a"]
    cid = doc["chunks"][0]["id"]
    with api_context["session_factory"]() as db:
        db.get(KnowledgeSource, sid).is_test_data = False
        db.get(KnowledgeDocument, doc["id"]).is_test_data = False
        before = db.query(AuditEvent).count()
        db.commit()
    response = client.patch(
        f"/api/v1/knowledge/chunks/{cid}",
        headers=identities["scope-a"][1],
        json={"content": "changed"},
    )
    assert response.status_code == 403
    with api_context["session_factory"]() as db:
        assert db.get(KnowledgeChunk, cid).content == "left content. right content."
        assert db.query(AuditEvent).count() == before


def test_import_overlap_and_edits_do_not_mint_credit(api_context, workspace):
    configure(100, knowledge_chunk_size_chars=40, knowledge_chunk_overlap_chars=10)
    client, identities, sources = workspace
    headers = identities["scope-a"][1]
    sid = sources["scope-a"][0]
    doc = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/text",
        headers=headers,
        json={"title": "overlap", "content": "z" * 100, "is_test_data": True},
    )
    assert doc.status_code == 201
    ids = [c["id"] for c in doc.json()["chunks"]]
    with api_context["session_factory"]() as db:
        chunks = [db.get(KnowledgeChunk, c) for c in ids]
        assert sum(len(c.content) for c in chunks) == 120
        assert sum(c.overlap_credit_chars for c in chunks) == 20
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{ids[1]}", headers=headers, json={"content": "y" * 40}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{ids[1]}", headers=headers, json={"content": "y" * 41}
        ).status_code
        == 413
    )
    split = client.post(
        f"/api/v1/knowledge/chunks/{ids[1]}/split", headers=headers, json={"offset": 20}
    )
    assert split.status_code == 200
    with api_context["session_factory"]() as db:
        chunks = list(
            db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.json()["id"]))
        )
        assert sum(len(c.content) - c.overlap_credit_chars for c in chunks) == 100
        assert sum(c.overlap_credit_chars for c in chunks) == 20
    # A merge creates one newline; no credit is minted to cover that new content.
    split_ids = [c["id"] for c in split.json()["chunks"]][1:3]
    assert (
        client.post(
            "/api/v1/knowledge/chunks/merge", headers=headers, json={"chunk_ids": split_ids}
        ).status_code
        == 413
    )


def test_legacy_oversize_can_shrink_but_not_grow_or_submit(api_context, workspace):
    configure(100)
    client, identities, sources = workspace
    _, doc = sources["scope-a"]
    cid = doc["chunks"][0]["id"]
    headers = identities["scope-a"][1]
    with api_context["session_factory"]() as db:
        chunk = db.get(KnowledgeChunk, cid)
        chunk.content = "x" * 200
        chunk.char_count = 200
        db.commit()
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{cid}", headers=headers, json={"content": "x" * 150}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{cid}", headers=headers, json={"content": "x" * 151}
        ).status_code
        == 413
    )
    review = {"decision": "pending", "reviewer_role": "organizer", "reviewer_ref": "untrusted"}
    assert (
        client.patch(
            f"/api/v1/knowledge/documents/{doc['id']}/review", headers=headers, json=review
        ).status_code
        == 413
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/chunks/{cid}", headers=headers, json={"content": "x" * 100}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/documents/{doc['id']}/review", headers=headers, json=review
        ).status_code
        == 200
    )


@pytest.mark.parametrize("operation", ["split", "merge", "delete", "submit"])
def test_formal_write_boundary_covers_sibling_commands(api_context, workspace, operation):
    client, identities, sources = workspace
    sid, doc = sources["scope-a"]
    headers = identities["scope-a"][1]
    split = client.post(
        f"/api/v1/knowledge/chunks/{doc['chunks'][0]['id']}/split",
        headers=headers,
        json={"offset": 10},
    )
    assert split.status_code == 200
    ids = [c["id"] for c in split.json()["chunks"]]
    with api_context["session_factory"]() as db:
        db.get(KnowledgeSource, sid).is_test_data = False
        db.get(KnowledgeDocument, doc["id"]).is_test_data = False
        db.commit()
        before = (db.query(AuditEvent).count(), db.query(KnowledgeChunk).count())
    requests = {
        "split": ("post", f"/chunks/{ids[0]}/split", {"offset": 3}),
        "merge": ("post", "/chunks/merge", {"chunk_ids": ids}),
        "delete": ("delete", f"/chunks/{ids[0]}", None),
        "submit": (
            "patch",
            f"/documents/{doc['id']}/review",
            {"decision": "pending", "reviewer_role": "organizer", "reviewer_ref": "forged"},
        ),
    }
    method, path, payload = requests[operation]
    response = client.request(
        method,
        "/api/v1/knowledge" + path,
        headers=headers,
        **({"json": payload} if payload else {}),
    )
    assert response.status_code == 403
    with api_context["session_factory"]() as db:
        assert before == (db.query(AuditEvent).count(), db.query(KnowledgeChunk).count())
        assert db.get(KnowledgeDocument, doc["id"]).review_status == "draft"


def test_test_import_cannot_replay_formal_document(api_context, workspace):
    client, identities, sources = workspace
    sid, doc = sources["scope-a"]
    headers = identities["scope-a"][1]
    with api_context["session_factory"]() as db:
        db.get(KnowledgeSource, sid).is_test_data = False
        db.get(KnowledgeDocument, doc["id"]).is_test_data = False
        db.commit()
        before = db.query(AuditEvent).count()
    response = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/text",
        headers=headers,
        json={
            "title": "repeat",
            "content": "left content. right content.",
            "is_test_data": False,
            "metadata": {"applicable_hardware": ["fixture"]},
        },
    )
    assert response.status_code == 409
    with api_context["session_factory"]() as db:
        assert db.get(KnowledgeDocument, doc["id"]).is_test_data is False
        assert db.query(AuditEvent).count() == before


@pytest.mark.skipif(sys.platform != "linux", reason="Bounded parser requires Linux")
def test_file_import_inherits_test_actor(api_context, workspace):
    import base64

    client, identities, sources = workspace
    sid, _ = sources["scope-a"]
    headers = identities["scope-a"][1]
    with api_context["session_factory"]() as db:
        db.get(KnowledgeSource, sid).is_test_data = False
        db.commit()
    response = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/file",
        headers=headers,
        json={
            "filename": "fixture.txt",
            "content_base64": base64.b64encode(b"new synthetic content").decode(),
            "media_type": "text/plain",
            "is_test_data": False,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["is_test_data"] is True
