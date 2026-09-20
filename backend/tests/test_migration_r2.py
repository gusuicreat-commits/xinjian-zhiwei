"""Real Alembic upgrades in disposable PostgreSQL schemas; never production tables."""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Boolean, DateTime, MetaData, Numeric, Table, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.sqltypes import Float, Integer

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration_db():
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    schema = "migration_r2_" + uuid4().hex
    url = make_url(dsn).set(drivername="postgresql+psycopg")
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    scoped = url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(scoped)
    env = {
        **os.environ,
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "PGOPTIONS": f"-csearch_path={schema},public",
    }

    def migrate(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    try:
        yield engine, migrate
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_empty_database_upgrade_matches_models(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20260920_0032"
    migrate("check")


def _seed(conn, name, **overrides):
    table = Table(name, MetaData(), autoload_with=conn)
    values = {}
    for column in table.columns:
        if column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, JSON):
            value = {"historical": "原文保持", "nested": [1, None]}
        elif isinstance(column.type, Boolean):
            value = True
        elif isinstance(column.type, DateTime):
            value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        elif isinstance(column.type, (Integer, Float, Numeric)):
            value = 1
        else:
            value = str(uuid4())[: getattr(column.type, "length", None)]
        values[column.name] = value
    values.update(overrides)
    conn.execute(table.insert().values(**values))
    row = dict(conn.execute(table.select().where(table.c.id == values["id"])).mappings().one())
    return row


def test_historical_upgrade_preserves_content_and_does_not_guess_scope(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "20260917_0028")
    before = {}
    with engine.begin() as conn:
        device = _seed(conn, "devices")
        diagnosis = _seed(conn, "diagnosis_results", device_id=device["id"])
        feedback = _seed(
            conn, "diagnosis_feedback", device_id=device["id"], diagnosis_result_id=diagnosis["id"]
        )
        for name in ("device_logs", "sensor_readings", "device_heartbeats"):
            before[name] = _seed(conn, name, device_id=device["id"])
        before["diagnosis_results"] = diagnosis
        before["knowledge_case_drafts"] = _seed(
            conn,
            "knowledge_case_drafts",
            diagnosis_result_id=diagnosis["id"],
            feedback_id=feedback["id"],
        )
        before["knowledge_cases"] = _seed(conn, "knowledge_cases")
        before["diagnosis_episodes"] = _seed(
            conn,
            "diagnosis_episodes",
            device_id=device["id"],
            last_diagnosis_result_id=diagnosis["id"],
        )
    migrate("upgrade", "20260917_0029")
    additions = {
        "device_logs": ("experiment_session_id", None),
        "sensor_readings": ("experiment_session_id", None),
        "device_heartbeats": ("experiment_session_id", None),
        "diagnosis_results": ("episode_evidence_revision", None),
        "knowledge_cases": ("source_draft_id", None),
        "knowledge_case_drafts": ("version_no", 1),
        "diagnosis_episodes": ("evidence_revision", 0),
    }
    with engine.begin() as conn:
        for name, original in before.items():
            table = Table(name, MetaData(), autoload_with=conn)
            current = dict(
                conn.execute(
                    table.select().where(
                        table.c.id == original["id"],
                    )
                )
                .mappings()
                .one()
            )
            column, expected = additions[name]
            assert current.pop(column) == expected
            assert current == original
        source = before["knowledge_case_drafts"]["id"]
        _seed(conn, "knowledge_cases", source_draft_id=source)
        with pytest.raises(IntegrityError), conn.begin_nested():
            _seed(conn, "knowledge_cases", source_draft_id=source)
    migrate("upgrade", "head")
    migrate("check")
