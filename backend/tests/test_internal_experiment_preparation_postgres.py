"""Real PostgreSQL serialization and permission changes during preparation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker
from test_internal_experiment_preparation import SECRETS, seed_preparation
from test_migration_r2 import migration_db as _migration_db

from app.models import AuditEvent, Course, ExperimentVersion, User
from app.services.auth import ActorContext, AuthorizationDenied
from app.services.internal_experiment_preparation import (
    PreparationError,
    apply_preparation,
    inspect_preparation,
)

migration_db = _migration_db


def test_concurrent_preparations_create_one_receipt_and_replay_after_reconnect(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        actor_id, spec = seed_preparation(db)
    barrier = Barrier(2)

    def apply():
        with factory() as db:
            barrier.wait(timeout=10)
            return apply_preparation(
                db,
                actor_id,
                spec,
                **SECRETS,
                actor_context=ActorContext(actor_id, mode="local_admin"),
            )

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(apply) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert results[0] == results[1]
    with factory() as db:
        assert db.scalar(select(func.count(Course.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "internal_experiment.prepare"
                )
            )
            == 1
        )
        assert inspect_preparation(db, actor_id, spec) == results[0]
        with pytest.raises(PreparationError):
            apply_preparation(
                db,
                actor_id,
                replace(spec, device_kind="hardware"),
                **SECRETS,
                actor_context=ActorContext(actor_id, mode="local_admin"),
            )
    migrate("check")


@pytest.mark.parametrize("change", ["actor", "package"])
def test_access_and_package_rechecked_after_lock_acquisition(migration_db, change):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        actor_id, spec = seed_preparation(db)
    locked, resume = Event(), Event()

    def pause_after_prefix_lock(conn, cursor, statement, parameters, context, many):
        if "pg_advisory_xact_lock" in statement:
            locked.set()
            assert resume.wait(timeout=10)

    event.listen(engine, "after_cursor_execute", pause_after_prefix_lock)

    def apply():
        with factory() as db:
            expected_error = AuthorizationDenied if change == "actor" else PreparationError
            with pytest.raises(expected_error) as exc:
                apply_preparation(
                    db,
                    actor_id,
                    spec,
                    **SECRETS,
                    actor_context=ActorContext(actor_id, mode="local_admin"),
                )
            if change == "actor":
                assert exc.value.status_code == 401

    try:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(apply)
            assert locked.wait(timeout=10)
            try:
                with factory() as db:
                    if change == "actor":
                        db.get(User, actor_id).is_active = False
                    else:
                        db.get(ExperimentVersion, spec.package_version_id).status = "revoked"
                    db.commit()
            finally:
                resume.set()
            pending.result(timeout=15)
    finally:
        resume.set()
        event.remove(engine, "after_cursor_execute", pause_after_prefix_lock)
    with factory() as db:
        assert db.scalar(select(func.count(Course.id))) == 0
