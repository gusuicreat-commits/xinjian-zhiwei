"""Real PostgreSQL locks, historical migration and overlap accounting constraints."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_knowledge_boundary_fix import configure
from test_migration_r2 import _seed

from app.core.config import Settings
from app.db.base import Base
from app.models import AuditEvent, KnowledgeChunk, KnowledgeSource
from app.services.auth import current_actor, resolve_session
from app.services.knowledge import KnowledgeServiceError, update_chunk

pytest_plugins = ["test_knowledge_scope_repair", "test_migration_r2"]

def test_concurrent_edits_share_remaining_document_budget(api_context, workspace, migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    client, identities, sources = workspace
    configure(100, knowledge_chunk_size_chars=40, knowledge_chunk_overlap_chars=0)
    sid = sources["scope-a"][0]
    response = client.post(
        f"/api/v1/knowledge/sources/{sid}/documents/text",
        headers=identities["scope-a"][1],
        json={"title": "concurrency", "content": "x" * 80, "is_test_data": True},
    )
    assert response.status_code == 201
    ids = [c["id"] for c in response.json()["chunks"]]
    assert len(ids) == 2
    with api_context["session_factory"]() as source, engine.begin() as target:
        for table in Base.metadata.sorted_tables:
            rows = list(source.execute(select(table)).mappings())
            if rows:
                target.execute(table.insert(), [dict(r) for r in rows])
    token = identities["scope-a"][1]["Authorization"][7:]
    barrier = Barrier(3)

    def edit(cid):
        with Session(engine, expire_on_commit=False) as db:
            actor = current_actor(resolve_session(db, token))
            # A cached relationship before waiting must not authorize an old total.
            list(db.get(KnowledgeChunk, cid).document.chunks)
            barrier.wait(timeout=10)
            try:
                update_chunk(
                    db,
                    cid,
                    content="y" * 55,
                    metadata=None,
                    settings=Settings(_env_file=None, knowledge_max_document_chars=100),
                    actor_context=actor,
                )
                db.commit()
                return 200
            except KnowledgeServiceError as error:
                db.rollback()
                return error.status_code

    with Session(engine) as guard:
        guard.scalar(select(KnowledgeSource).where(KnowledgeSource.id == sid).with_for_update())
        before = guard.query(AuditEvent).count()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(edit, cid) for cid in ids]
            barrier.wait(timeout=10)
            guard.commit()
            results = [t.result(timeout=15) for t in tasks]
    assert sorted(results) == [200, 413]
    with Session(engine) as db:
        assert sum(len(db.get(KnowledgeChunk, cid).content) for cid in ids) == 95
        assert db.query(AuditEvent).count() == before + 1


def test_overlap_migration_preserves_history_and_guards_downgrade(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "20261002_0038")
    with engine.begin() as conn:
        source = _seed(conn, "knowledge_sources")
        document = _seed(conn, "knowledge_documents", source_id=source["id"])
        before = _seed(
            conn,
            "knowledge_chunks",
            document_id=document["id"],
            content="abc",
            char_count=3,
            locator_json={"unverified_old_overlap": 99},
        )
    migrate("upgrade", "head")
    migrate("check")
    with engine.begin() as conn:
        row = dict(
            conn.execute(text("SELECT * FROM knowledge_chunks WHERE id=:id"), {"id": before["id"]})
            .mappings()
            .one()
        )
        assert row.pop("overlap_credit_chars") == 0
        assert row == before
        for invalid in [-1, 4]:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text("UPDATE knowledge_chunks SET overlap_credit_chars=:value"),
                    {"value": invalid},
                )
        conn.execute(text("UPDATE knowledge_chunks SET overlap_credit_chars=1"))
    with pytest.raises(AssertionError, match="Recorded overlap accounting cannot be discarded"):
        migrate("downgrade", "20261002_0038")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT overlap_credit_chars FROM knowledge_chunks")) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261003_0039"
