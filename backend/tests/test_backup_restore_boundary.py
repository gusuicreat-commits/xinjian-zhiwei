"""Actual dump/restore in disposable databases; no live source comparison."""

import importlib.util
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


def test_snapshot_backup_restores_all_tables_and_detects_mutations(tmp_path):
    container = os.getenv("XINJIAN_BACKUP_TEST_CONTAINER")
    if not container:
        pytest.skip("XINJIAN_BACKUP_TEST_CONTAINER must identify an isolated PostgreSQL container")
    spec = importlib.util.spec_from_file_location(
        "database_backup", Path(__file__).parents[2] / "scripts/database_backup.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    source_name = "xinjian_backup_test_" + uuid4().hex
    restored_name = "xinjian_restore_test_" + uuid4().hex
    control = tool.SQL(container)
    source = restored = None
    try:
        control.query("CREATE DATABASE " + tool.quote(source_name))
        control.query("CREATE DATABASE " + tool.quote(restored_name))
        source = tool.SQL(container, source_name)
        source.query(
            "CREATE TABLE experiment_sessions(id text PRIMARY KEY, owner text NOT NULL); "
            "CREATE TABLE diagnosis_checks(id text PRIMARY KEY, "
            "session_id text REFERENCES experiment_sessions(id), state jsonb NOT NULL); "
            "INSERT INTO experiment_sessions VALUES ('session','original'); "
            "INSERT INTO diagnosis_checks VALUES ('check','session','{\"status\":\"completed\"}')"
        )
        path = tmp_path / "backup.dump"
        tool.backup(path, container, source_name)
        # Live source can advance. Restored content must match the backup's own snapshot.
        source.query("UPDATE experiment_sessions SET owner='new owner'")
        with path.open("rb") as stream:
            subprocess.run(
                tool.pg_command(
                    container,
                    "pg_restore",
                    restored_name,
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                ),
                stdin=stream,
                check=True,
            )
        restored = tool.SQL(container, restored_name)
        assert tool.verify(path, restored) == 2
        for mutation in [
            "DELETE FROM diagnosis_checks WHERE id='check'",
            'UPDATE diagnosis_checks SET state=\'{"status":"failed"}\'',
            "ALTER TABLE diagnosis_checks DROP CONSTRAINT diagnosis_checks_session_id_fkey; "
            "UPDATE diagnosis_checks SET session_id='missing'",
        ]:
            restored.query("BEGIN; " + mutation)
            with pytest.raises(ValueError, match="content or relationships differ"):
                tool.verify(path, restored)
            restored.query("ROLLBACK")
        tool.restore_drill(path, container)
    finally:
        if source:
            source.close()
        if restored:
            restored.close()
        control.query("DROP DATABASE IF EXISTS " + tool.quote(source_name))
        control.query("DROP DATABASE IF EXISTS " + tool.quote(restored_name))
        control.close()


def test_full_workflow_database_restore(tmp_path):
    from sqlalchemy.engine import make_url
    from test_teaching_materials import start

    from app.evaluation.workflow_environment import workflow_environment

    container = os.getenv("XINJIAN_BACKUP_TEST_CONTAINER")
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not container or not dsn:
        pytest.skip("isolated PostgreSQL DSN and container required")
    spec = importlib.util.spec_from_file_location(
        "database_backup", Path(__file__).parents[2] / "scripts/database_backup.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    name = "xinjian_backup_full_" + uuid4().hex
    control = tool.SQL(container)
    try:
        control.query("CREATE DATABASE " + tool.quote(name))
        setup = tool.SQL(container, name)
        setup.query("CREATE EXTENSION vector")
        setup.close()
        isolated = make_url(dsn).set(database=name).render_as_string(hide_password=False)
        with workflow_environment("dht11_temperature_humidity", postgres_dsn=isolated) as env:
            start(env)
            path = tmp_path / "workflow.dump"
            tool.backup(path, container, name)
            import json

            tables = json.loads(Path(str(path) + ".manifest.json").read_text())["snapshot"][
                "tables"
            ]
            for suffix in [
                "diagnosis_results",
                "diagnosis_checks",
                "diagnosis_episodes",
                "experiment_sessions",
                "experiment_versions",
                "diagnosis_workflow_runs",
            ]:
                assert any(
                    key.endswith("." + suffix) and value["rows"] > 0
                    for key, value in tables.items()
                )
            assert len(tables) > 30
        # The source fixture was removed; recovery still verifies against its frozen manifest.
        tool.restore_drill(path, container)
    finally:
        control.query("DROP DATABASE IF EXISTS " + tool.quote(name))
        control.close()
