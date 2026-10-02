"""Teacher summaries use the same workspace source scope as workspace APIs."""
import pytest
from test_knowledge_scope_repair import workspace as _workspace

from app.core.security import hash_password
from app.models import KnowledgeChunk, User
from app.services.rbac import assign_role, ensure_rbac_catalog

workspace = _workspace


@pytest.mark.parametrize("has_workspace_role", [False, True])
def test_teacher_dashboard_does_not_reveal_other_workspace_totals(
    api_context, workspace, has_workspace_role,
):
    client, identities, _ = workspace
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        if has_workspace_role:
            teacher = db.get(User, identities["scope-a"][0])
        else:
            teacher = User(username="scope-only-teacher", display_name="Synthetic teacher",
                password_hash=hash_password("synthetic-password", iterations=1000),
                is_test_data=True)
            db.add(teacher)
            db.flush()
        assign_role(db, teacher, roles["teacher"])
        # Mark the unrelated source's chunks approved to exercise that count too.
        for chunk in db.query(KnowledgeChunk).all():
            chunk.review_status = "approved"
        db.commit()
        username = teacher.username
    login = client.post("/api/v1/auth/session", json={
        "username": username, "password": "synthetic-password",
    })
    assert login.status_code == 200
    response = client.get("/api/v1/teacher/dashboard", headers={
        "Authorization": "Bearer " + login.json()["access_token"],
    })
    assert response.status_code == 200
    knowledge = response.json()["knowledge_cases"]
    expected = 1 if has_workspace_role else 0
    assert knowledge["source_count"] == expected
    assert knowledge["document_count"] == expected
    assert knowledge["approved_chunk_count"] == expected
    assert knowledge["case_count"] == 0
    if not has_workspace_role:
        assert "受限" in knowledge["notice"]
