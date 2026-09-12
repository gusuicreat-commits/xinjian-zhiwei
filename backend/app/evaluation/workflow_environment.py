"""Isolated evaluation fixtures. Never uses the application's database or AI credentials."""

import json
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.clients import AICompletion, AIProviderError
from app.ai.diagnosis_graph import build_diagnosis_graph
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.security import hash_device_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.experiment_packages.loader import load_experiment_package, package_documents
from app.models import (
    Classroom,
    Course,
    Device,
    DeviceBinding,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
    User,
)
from app.services.experiment_packages import (
    import_experiment_package,
    transition_experiment_package,
)
from app.services.rbac import assign_role, ensure_rbac_catalog

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "experiment_packages"
DEVICE_KEY = "workflow-evaluation-device"
DEVICE_TOKEN = "synthetic-device-token-never-production"
LOGIN_PASSWORD = "synthetic-evaluation-login"


class ScriptedProvider:
    """Reads only live prompts and a fault-injection mode, never expected answers."""

    configured = True
    provider = "evaluation-mock"
    model = "scripted-not-a-real-model"

    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    def complete_json(self, *, system_prompt, user_prompt):
        prompt, _ = json.JSONDecoder().raw_decode(user_prompt)
        stage = "reasoning" if "candidate_causes" in prompt else "explanation"
        self.calls.append({"stage": stage, "mode": self.mode})
        if self.mode == "timeout":
            raise AIProviderError("synthetic timeout; no network request")
        if self.mode == "invalid_json":
            return AICompletion(content="{invalid synthetic JSON")
        if stage == "reasoning":
            candidates = prompt["candidate_causes"]
            evidence = {
                r["id"]
                for r in prompt["evidence_registry"]
                if r.get("status") not in {"unknown", "invalid"}
            }
            ranked = []
            if candidates and evidence and self.mode != "unknown":
                cause = candidates[0]
                linked_evidence = [r for r in cause.get("evidence_refs", []) if r in evidence]
                ranked = (
                    [
                        {
                            "cause_id": cause["cause_id"],
                            "cause": cause["name"],
                            "support_level": "low",
                            "used_evidence_ids": linked_evidence[:1],
                            "reason": "合成排序样例，仅验证软件约束，不确认根因。",
                        }
                    ]
                    if linked_evidence
                    else []
                )
                if self.mode == "foreign_evidence" and ranked:
                    ranked[0]["used_evidence_ids"] = ["00000000-0000-0000-0000-000000000000"]
                if self.mode == "unrelated_evidence" and ranked:
                    unrelated = next(
                        (r for r in evidence if r not in cause.get("evidence_refs", [])), None
                    )
                    if unrelated is None:
                        raise ValueError(
                            "unrelated-evidence fixture requires an unrelated real UUID"
                        )
                    ranked[0]["used_evidence_ids"] = [unrelated]
            result = {
                "error_type": prompt["error_type"],
                "conclusion": "ranked" if ranked else "unknown",
                "ranked_causes": ranked,
                "summary": "现有日志不能区分具体硬件根因。",
                "missing_evidence": ["需独立硬件测量"] if not ranked else [],
                "limitations": ["合成数据"],
            }
        else:
            data = prompt["input"]
            result = {
                "error_type": data["rule_matches"][0]["error_type"]
                if data["rule_matches"]
                else "UNCLASSIFIED_ANOMALY",
                "summary": "合成解释",
                "evidence": data["allowed_evidence"][:1],
                "possible_causes": [],
                "steps": prompt["output_contract"]["allowed_steps"][:1],
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["合成数据"],
            }
        return AICompletion(content=json.dumps(result, ensure_ascii=False))


class WorkflowEnvironment:
    def __init__(self, package, mode, postgres_dsn=None):
        self.package = package
        self.provider = ScriptedProvider(mode)
        self.postgres_dsn = postgres_dsn
        self.schema = "workflow_eval_" + uuid4().hex
        self.events = []

    def request(self, method, path, *, headers=None, json=None):
        response = self.client.request(method, path, headers=headers or self.headers, json=json)
        body = response.json()
        # Auth credentials never enter the exported trajectory.
        recorded = (
            {"authenticated": response.status_code == 200}
            if path.endswith("auth/session")
            else body
        )
        self.events.append(
            {
                "method": method,
                "path": path,
                "request": json
                if not path.endswith("auth/session")
                else {"username": "synthetic-teacher"},
                "status_code": response.status_code,
                "response": recorded,
            }
        )
        return response

    def restart_graph(self):
        if not self.postgres_dsn:
            raise RuntimeError("durability verification requires PostgreSQL")
        self.saver_context.__exit__(None, None, None)
        self.engine.dispose()  # Subsequent business queries also use new connections.
        self._new_postgres_graph()

    def _new_postgres_graph(self):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.conninfo import make_conninfo

        scoped = make_conninfo(self.postgres_dsn, options=f"-c search_path={self.schema}")
        self.saver_context = PostgresSaver.from_conn_string(scoped)
        saver = self.saver_context.__enter__()
        saver.setup()
        self.app.state.diagnosis_graph = build_diagnosis_graph(saver)

    def seed(self):
        with self.sessions() as db:
            roles = ensure_rbac_catalog(db)
            student = User(
                username="synthetic-student",
                display_name="合成学生",
                password_hash="unused",
                is_test_data=True,
            )
            teacher = User(
                username="synthetic-teacher",
                display_name="合成教师角色，不代表教师审核",
                password_hash=hash_password(LOGIN_PASSWORD, iterations=1000),
                is_test_data=True,
            )
            device = Device(
                device_key=DEVICE_KEY,
                display_name="合成评测设备",
                device_type="test-fixture",
                token_hash=hash_device_token(DEVICE_TOKEN, iterations=1000),
            )
            course = Course(code="workflow-eval", title="合成课程", is_test_data=True)
            db.add_all([student, teacher, device, course])
            db.flush()
            assign_role(db, teacher, roles["teacher"])
            classroom = Classroom(
                course_id=course.id, code="eval", name="合成班级", is_test_data=True
            )
            db.add(classroom)
            db.flush()
            self.versions = {}
            self.hashes = {}
            for package in ("dht11_temperature_humidity", "gpio_led_output"):
                bundle, _ = load_experiment_package(PACKAGE_ROOT / package)
                _, version = import_experiment_package(db, teacher, package_documents(bundle))
                for status in ("pending", "approved", "published"):
                    transition_experiment_package(db, teacher, version, status)
                self.versions[package] = version.id
                self.hashes[package] = version.package_hash
            assignment = ExperimentAssignment(
                class_id=classroom.id,
                title="合成作业",
                status="published",
                experiment_version_id=self.versions[self.package],
                is_test_data=True,
            )
            db.add(assignment)
            db.flush()
            db.add_all(
                [
                    Enrollment(class_id=classroom.id, user_id=student.id, status="active"),
                    TeachingAssignment(class_id=classroom.id, user_id=teacher.id),
                    DeviceBinding(
                        device_id=device.id,
                        class_id=classroom.id,
                        student_user_id=student.id,
                        experiment_assignment_id=assignment.id,
                    ),
                ]
            )
            session = ExperimentSession(
                experiment_assignment_id=assignment.id,
                student_user_id=student.id,
                device_id=device.id,
                started_at=datetime.now(timezone.utc),
                status="active",
                is_test_data=True,
            )
            db.add(session)
            db.commit()
            self.session_id = session.id
            self.device_id = device.id
            self.assignment_id = assignment.id
            self.class_id = classroom.id
        self.headers = {
            "X-Device-ID": DEVICE_KEY,
            "X-Device-Token": DEVICE_TOKEN,
            "X-Experiment-Session-ID": self.session_id,
        }

    def other_student_headers(self):
        with self.sessions() as db:
            student = User(
                username="synthetic-other",
                display_name="另一合成学生",
                password_hash="unused",
                is_test_data=True,
            )
            db.add(student)
            db.flush()
            db.add_all(
                [
                    Enrollment(class_id=self.class_id, user_id=student.id, status="active"),
                    DeviceBinding(
                        device_id=self.device_id,
                        class_id=self.class_id,
                        student_user_id=student.id,
                        experiment_assignment_id=self.assignment_id,
                    ),
                ]
            )
            session = ExperimentSession(
                experiment_assignment_id=self.assignment_id,
                student_user_id=student.id,
                device_id=self.device_id,
                started_at=datetime.now(timezone.utc),
                status="active",
                is_test_data=True,
            )
            db.add(session)
            db.commit()
            return {**self.headers, "X-Experiment-Session-ID": session.id}


@contextmanager
def workflow_environment(package, mode="valid", postgres_dsn=None):
    env = WorkflowEnvironment(package, mode, postgres_dsn)
    admin = None
    try:
        if postgres_dsn:
            import psycopg
            from psycopg import sql

            admin = psycopg.connect(postgres_dsn, autocommit=True, connect_timeout=5)
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(env.schema)))
            env.engine = create_engine(
                postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1),
                connect_args={"options": f"-c search_path={env.schema}", "connect_timeout": 5},
            )
        else:
            env.engine = create_engine(
                "sqlite+pysqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        env.sessions = sessionmaker(bind=env.engine, autoflush=False, expire_on_commit=False)
        Base.metadata.create_all(env.engine)
        env.seed()
        env.app = FastAPI()
        env.app.include_router(api_router, prefix="/api/v1")
        settings = Settings(
            _env_file=None,
            ai_enabled=True,
            ai_require_knowledge=False,
            ai_api_key=None,
            ai_input_token_limit=32000,
            ai_calls_per_episode=20,
            ai_calls_per_device_hour=50,
            diagnosis_teacher_review_score=0,
            diagnosis_teacher_max_attempts=5,
            diagnosis_teacher_duration_seconds=3600,
        )

        def get_test_db():
            with env.sessions() as db:
                yield db

        env.app.dependency_overrides[get_db] = get_test_db
        env.app.dependency_overrides[get_settings] = lambda: settings
        if postgres_dsn:
            env._new_postgres_graph()
        else:
            env.app.state.diagnosis_graph = build_diagnosis_graph(InMemorySaver())
        with ExitStack() as stack:
            # Both production factories are replaced; no real provider is reachable.
            for module in ("app.ai.reasoning", "app.services.ai_diagnosis"):
                stack.enter_context(patch(f"{module}.build_ai_client", return_value=env.provider))
            env.client = stack.enter_context(TestClient(env.app))
            yield env
    finally:
        if hasattr(env, "saver_context"):
            env.saver_context.__exit__(None, None, None)
        if hasattr(env, "engine"):
            env.engine.dispose()
        if admin is not None:
            try:
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(env.schema)))
            finally:
                admin.close()
