"""Loopback-only browser fixture: migrated isolated PostgreSQL, real routes and graph.

This CLI is never imported by the production app. Its local control file injects
one feedback outage window without adding a testing endpoint to the API.
"""

import argparse
import json
import os
import re
import signal
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg import sql
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.evaluation.workflow_environment import DEVICE_KEY, DEVICE_TOKEN, WorkflowEnvironment
from app.models import AICallRecord, Device, DiagnosisEvidence, DiagnosisFeedback
from app.models.diagnosis_workflow import DiagnosisWorkflowRun

BACKEND = Path(__file__).resolve().parents[2]


def scoped_url(dsn, schema):
    if not re.fullmatch(r"workflow_eval_[a-f0-9]{32}", schema):
        raise ValueError("refusing an unrecognized integration schema")
    return (
        make_url(dsn)
        .set(drivername="postgresql+psycopg")
        .update_query_dict({"options": f"-c search_path={schema},public"})
    )


def test_settings(url):
    return Settings(
        _env_file=None,
        database_url=url.render_as_string(hide_password=False).replace("%", "%%"),
        app_env="test",
        ai_enabled=True,
        ai_require_knowledge=False,
        ai_api_key=None,
        ai_local_api_key=None,
        ai_cloud_api_key=None,
        ai_input_token_limit=32000,
        ai_calls_per_episode=20,
        ai_calls_per_device_hour=50,
        diagnosis_teacher_review_score=0,
        diagnosis_teacher_max_attempts=5,
        diagnosis_teacher_duration_seconds=3600,
        diagnosis_checkpoint_backend="memory",
    )


@contextmanager
def fixture(dsn, control_dir, origin):
    env = WorkflowEnvironment("dht11_temperature_humidity", "valid", dsn)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as admin:
        extension = admin.execute(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
            "ON n.oid=e.extnamespace WHERE e.extname='vector'"
        ).fetchone()
        if extension != ("public",):
            raise RuntimeError("temporary test database needs vector extension in public")
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(env.schema)))
        try:
            # public can itself already be at head. Shadow its version table
            # before Alembic inspects search_path, otherwise it may skip upgrades.
            admin.execute(
                sql.SQL(
                    "CREATE TABLE {}.alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
                ).format(sql.Identifier(env.schema))
            )
            url = scoped_url(dsn, env.schema)
            settings = test_settings(url)
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "migrations"))
            # env.py reads Settings; the override scopes every Alembic connection.
            with patch("app.core.config.get_settings", return_value=settings):
                command.upgrade(config, "head")
            for table in ("alembic_version", "devices", "diagnosis_feedback", "diagnosis_evidence"):
                actual_schema = admin.execute(
                    "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.relname=%s AND n.nspname=%s",
                    (table, env.schema),
                ).fetchone()
                if actual_schema != (env.schema,):
                    raise RuntimeError(f"migration did not create {table} in its isolated schema")
            env.engine = create_engine(url)
            env.sessions = sessionmaker(bind=env.engine, autoflush=False, expire_on_commit=False)
            env.seed()
            with env.sessions() as db:
                device = db.get(Device, env.device_id)
                device.metadata_json = {"is_test_fixture": True, "is_test_data": True}
                db.commit()
            env.app = FastAPI(title="Synthetic browser integration fixture")
            env.app.include_router(api_router, prefix="/api/v1")
            env.app.add_middleware(
                CORSMiddleware,
                allow_origins=[origin],
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=[
                    "Content-Type",
                    "X-Device-ID",
                    "X-Device-Token",
                    "X-Experiment-Session-ID",
                ],
            )

            def test_db():
                with env.sessions() as db:
                    yield db

            env.app.dependency_overrides[get_db] = test_db
            env.app.dependency_overrides[get_settings] = lambda: settings
            env._new_postgres_graph()
            with ExitStack() as stack:
                for module in ("app.ai.reasoning", "app.services.ai_diagnosis"):
                    stack.enter_context(
                        patch(f"{module}.build_ai_client", return_value=env.provider)
                    )
                import app.services.student_feedback as feedback_service

                original_resume = feedback_service.resume_workflow_with_feedback

                def controlled_resume(*args, **kwargs):
                    if (control_dir / "pause-feedback").exists():
                        raise RuntimeError("synthetic outage before graph resume")
                    return original_resume(*args, **kwargs)

                stack.enter_context(
                    patch.object(
                        feedback_service, "resume_workflow_with_feedback", controlled_resume
                    )
                )
                case = next(
                    item
                    for item in json.loads(
                        (BACKEND / "evaluation/workflow_inputs.json").read_text()
                    )
                    if item["id"] == "dht-valid"
                )
                (control_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "schema": env.schema,
                            "device_key": DEVICE_KEY,
                            "device_token": DEVICE_TOKEN,
                            "session_id": env.session_id,
                            "records": case["records"],
                            "is_test_data": True,
                        }
                    )
                )
                yield env
        finally:
            if hasattr(env, "saver_context"):
                env.saver_context.__exit__(None, None, None)
            if hasattr(env, "engine"):
                env.engine.dispose()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(env.schema)))


def snapshot(dsn, control_dir):
    manifest = json.loads((control_dir / "manifest.json").read_text())
    engine = create_engine(scoped_url(dsn, manifest["schema"]))
    try:
        with sessionmaker(bind=engine)() as db:
            workflows = list(db.scalars(select(DiagnosisWorkflowRun)))
            result = {
                "migration": db.scalar(text("SELECT version_num FROM alembic_version")),
                "workflows": [
                    {
                        "id": w.id,
                        "diagnosis_id": w.diagnosis_result_id,
                        "session_id": w.experiment_session_id,
                        "status": w.status,
                        "resume_count": w.resume_count,
                        "node_trace": w.node_trace,
                        "is_test_data": w.is_test_data,
                    }
                    for w in workflows
                ],
                "feedback": [
                    {
                        "id": f.id,
                        "request_id": f.request_id,
                        "session_id": f.experiment_session_id,
                        "action": f.action,
                        "note": f.note,
                        "processing_status": f.processing_status,
                        "is_test_data": f.is_test_data,
                    }
                    for f in db.scalars(select(DiagnosisFeedback))
                ],
                "evidence_ids": sorted(db.scalars(select(DiagnosisEvidence.id))),
                "ai_call_ids": sorted(db.scalars(select(AICallRecord.id))),
            }
            print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["serve", "snapshot", "assert-clean"])
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18101)
    parser.add_argument("--frontend-origin", default="http://127.0.0.1:15173")
    args = parser.parse_args()
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn or not dsn.startswith("postgresql://"):
        parser.error("XINJIAN_EVAL_POSTGRES_DSN must point to an explicit temporary PostgreSQL DB")
    if args.operation == "assert-clean":
        schema = json.loads((args.control_dir / "manifest.json").read_text())["schema"]
        scoped_url(dsn, schema)  # Validate the fixture-owned namespace.
        with psycopg.connect(dsn, connect_timeout=5) as db:
            if db.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone():
                raise RuntimeError("integration fixture left its temporary schema behind")
        print("isolated schema cleanup verified")
    elif args.operation == "snapshot":
        snapshot(dsn, args.control_dir)
    else:
        # Uvicorn re-raises captured SIGTERM after its shutdown. Convert that
        # signal into normal stack unwinding so our schema cleanup still runs.
        def terminate(_signal, _frame):
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, terminate)
        with fixture(dsn, args.control_dir, args.frontend_origin) as env:
            uvicorn.run(env.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
