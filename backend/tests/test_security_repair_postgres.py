"""Final authorization interleavings on disposable PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_memory_postgres import memory_pg as _memory_pg
from test_migration_r2 import migration_db as _migration_db

from app.models import AuthSession, DiagnosisResult, MemoryEvent, MemoryImpactReview, User
from app.models.base import utc_now
from app.services.auth import AuthorizationDenied, current_actor
from app.services.memory import record_uses, register_stop
from app.services.memory_governance import review_impact

memory_pg = _memory_pg
migration_db = _migration_db


def test_memory_review_waiting_on_event_rechecks_revoked_session(memory_pg):
    engine, uid, did, cid, source = memory_pg
    with Session(engine, expire_on_commit=False) as db:
        user = db.get(User, uid)
        authorize_write_fixture(db, user)
        actor = current_actor(user)
        record_uses(
            db,
            db.get(DiagnosisResult, did),
            [{"chunk_id": cid, "source_version": "1"}],
            target_type="workflow",
            target_id="synthetic",
            use_kind="matched",
        )
        register_stop(db, source, user, "synthetic revocation")
        db.commit()
        eid = db.scalar(select(MemoryEvent.id))
    entered = Event()
    with Session(engine) as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.scalar(select(MemoryEvent).where(MemoryEvent.id == eid).with_for_update())

        def writer():
            with Session(engine) as db:
                db.execute(text("SET LOCAL statement_timeout='5s'"))
                user = db.get(User, uid)
                user._actor_context = actor
                entered.set()
                with pytest.raises(AuthorizationDenied) as denied:
                    review_impact(
                        db,
                        user,
                        db.get(MemoryEvent, eid),
                        db.get(DiagnosisResult, did),
                        expected_version=0,
                        decision="no_change",
                        note="synthetic",
                    )
                assert denied.value.status_code == 401
                db.rollback()

        pending = pool.submit(writer)
        assert entered.wait(5)
        with Session(engine) as revoker:
            revoker.get(AuthSession, actor.session_id).revoked_at = utc_now()
            revoker.commit()
        owner.commit()
        pending.result(timeout=10)
    with Session(engine) as db:
        assert db.query(MemoryImpactReview).count() == 0


def test_source_grant_revocation_commits_before_waiting_import(migration_db):
    from app.core.config import Settings
    from app.models import KnowledgeDocument, KnowledgeSource
    from app.models.knowledge_access import KnowledgeSourceGrant
    from app.schemas.knowledge import KnowledgeSourceCreate, KnowledgeTextImportRequest
    from app.services.knowledge import create_source, import_text_document

    engine, migrate = migration_db
    migrate("upgrade", "head")
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            username="source-race", display_name="test", password_hash="unused", is_test_data=True
        )
        db.add(user)
        authorize_write_fixture(db, user, "knowledge_organizer")
        actor = current_actor(user)
        source = create_source(
            db,
            KnowledgeSourceCreate(
                source_key="race", source_type="synthetic", title="test", is_test_data=True
            ),
            actor_context=actor,
        )
        sid = source.id
    entered = Event()
    with Session(engine) as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.scalar(select(KnowledgeSource).where(KnowledgeSource.id == sid).with_for_update())

        def importer():
            with Session(engine) as db:
                db.execute(text("SET LOCAL statement_timeout='5s'"))
                entered.set()
                with pytest.raises(AuthorizationDenied):
                    import_text_document(
                        db,
                        sid,
                        KnowledgeTextImportRequest(
                            title="no-write", content="synthetic", is_test_data=True
                        ),
                        Settings(),
                        actor_context=actor,
                    )
                db.rollback()

        pending = pool.submit(importer)
        assert entered.wait(5)
        # The source lock serializes grant changes with the waiting command.
        grant = owner.scalar(
            select(KnowledgeSourceGrant).where(KnowledgeSourceGrant.source_id == sid)
        )
        owner.delete(grant)
        owner.commit()
        pending.result(timeout=10)
    with Session(engine) as db:
        assert db.query(KnowledgeDocument).count() == 0


def test_security_upgrade_preserves_legacy_sources_and_unresolved_usage(migration_db):
    from sqlalchemy import MetaData, Table
    from test_migration_r2 import _seed

    engine, migrate = migration_db
    migrate("upgrade", "20260930_0036")
    with engine.begin() as conn:
        source = _seed(conn, "knowledge_sources")
        document = _seed(conn, "knowledge_documents", source_id=source["id"])
        device = _seed(conn, "devices")
        diagnosis = _seed(conn, "diagnosis_results", device_id=device["id"])
        reservation = _seed(
            conn,
            "ai_usage_reservations",
            device_id=device["id"],
            diagnosis_result_id=diagnosis["id"],
            status="reserved",
        )
    migrate("upgrade", "head")
    migrate("check")
    with engine.connect() as conn:
        for name, original, new_fields in [
            ("knowledge_sources", source, []),
            ("knowledge_documents", document, ["submitted_by_user_id"]),
            ("ai_usage_reservations", reservation, ["operation_id", "attempt_no"]),
        ]:
            table = Table(name, MetaData(), autoload_with=conn)
            current = dict(
                conn.execute(table.select().where(table.c.id == original["id"])).mappings().one()
            )
            for field in new_fields:
                assert current.pop(field) is None
            assert current == original
        assert conn.scalar(text("SELECT count(*) FROM knowledge_source_grants")) == 0
        assert conn.scalar(text("SELECT count(*) FROM ai_operations")) == 0
    with pytest.raises(
        AssertionError, match="AI operation state and uncertain costs cannot be discarded"
    ):
        migrate("downgrade", "20260930_0036")


def test_authorized_source_write_holds_grant_until_commit(migration_db):
    from sqlalchemy.exc import OperationalError

    from app.models.knowledge_access import KnowledgeSourceGrant
    from app.schemas.knowledge import KnowledgeSourceCreate
    from app.services.knowledge import create_source
    from app.services.knowledge_access import source_scope

    engine, migrate = migration_db
    migrate("upgrade", "head")
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            username="writer-first", display_name="test", password_hash="unused", is_test_data=True
        )
        db.add(user)
        authorize_write_fixture(db, user, "knowledge_organizer")
        actor = current_actor(user)
        source = create_source(
            db,
            KnowledgeSourceCreate(
                source_key="writer-first", source_type="synthetic", title="test", is_test_data=True
            ),
            actor_context=actor,
        )
        sid = source.id
    with Session(engine) as writer:
        source_scope(writer, actor, sid)
        # Even direct SQL grant revocation cannot pass the final authorization lock.
        with Session(engine) as revoker:
            revoker.execute(text("SET LOCAL lock_timeout='150ms'"))
            grant = revoker.scalar(
                select(KnowledgeSourceGrant).where(KnowledgeSourceGrant.source_id == sid)
            )
            revoker.delete(grant)
            with pytest.raises(OperationalError) as blocked:
                revoker.commit()
            assert blocked.value.orig.sqlstate == "55P03"
            revoker.rollback()
        writer.commit()
    with Session(engine) as revoker:
        grant = revoker.scalar(
            select(KnowledgeSourceGrant).where(KnowledgeSourceGrant.source_id == sid)
        )
        revoker.delete(grant)
        revoker.commit()
    with Session(engine) as db:
        with pytest.raises(AuthorizationDenied):
            source_scope(db, actor, sid)
