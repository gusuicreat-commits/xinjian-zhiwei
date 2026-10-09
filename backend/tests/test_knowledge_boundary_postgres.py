"""Real PostgreSQL locks, historical migration and overlap accounting constraints."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_migration_r2 import _seed

pytest_plugins = ["test_migration_r2"]


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
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261009_0040"
