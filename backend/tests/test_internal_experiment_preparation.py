"""Preparation must preserve authorization, atomicity and pinned package identity."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import hash_password
from app.experiment_packages.loader import load_experiment_package, package_documents
from app.models import AuditEvent, Course, Device, ExperimentAssignment, ExperimentSession, User
from app.services.experiment_packages import (
    import_experiment_package,
    transition_experiment_package,
)
from app.services.experiment_sessions import start_session
from app.services.internal_experiment_preparation import (
    PreparationError,
    PreparationSpec,
    apply_preparation,
    inspect_preparation,
)
from app.services.rbac import assign_role, ensure_rbac_catalog

SECRETS = dict(
    student_password="test-student-password",
    teacher_password="test-teacher-password",
    device_token="test-device-token-not-production",
)


def seed_preparation(db):
    roles = ensure_rbac_catalog(db)
    actor = User(
        username="prep-test-admin",
        display_name="Test admin",
        password_hash=hash_password("test-admin-password", iterations=1000),
        is_test_data=True,
    )
    db.add(actor)
    db.flush()
    assign_role(db, actor, roles["admin"])
    db.commit()
    root = Path(__file__).resolve().parents[1] / "experiment_packages/dht11_temperature_humidity"
    bundle, _ = load_experiment_package(root)
    _, version = import_experiment_package(db, actor, package_documents(bundle), is_test_data=True)
    for state in ("pending", "approved", "published"):
        transition_experiment_package(db, actor, version, state)
    return actor.id, PreparationSpec("lab-prep-test", version.id, version.package_hash)


@pytest.fixture
def prepared_context(api_context):
    factory = api_context["session_factory"]
    with factory() as db:
        actor_id, spec = seed_preparation(db)
    return factory, actor_id, spec


def test_plan_is_read_only_and_apply_replays_without_reset_or_session(prepared_context):
    factory, actor_id, spec = prepared_context
    with factory() as db:
        before = db.scalar(select(func.count(AuditEvent.id)))
        assert inspect_preparation(db, actor_id, spec)["state"] == "absent"
        assert db.scalar(select(func.count(AuditEvent.id))) == before
        assert db.scalar(select(Course).where(Course.code == spec.prefix + "-course")) is None
        first = apply_preparation(db, actor_id, spec, **SECRETS)
        student = db.get(User, first["objects"]["student_id"])
        pw = student.password_hash
        token = db.get(Device, first["objects"]["device_id"]).token_hash
        # Retrying a committed operation must not require or change credentials.
        assert apply_preparation(db, actor_id, spec) == first
        assert inspect_preparation(db, actor_id, spec) == first
        assert db.get(User, student.id).password_hash == pw
        assert db.get(Device, first["objects"]["device_id"]).token_hash == token
        assert (
            db.scalar(
                select(func.count(ExperimentSession.id)).where(
                    ExperimentSession.device_id == first["objects"]["device_id"]
                )
            )
            == 0
        )
        result = start_session(
            db,
            student,
            request_id=uuid4(),
            device_key=first["objects"]["device_key"],
            assignment_id=first["objects"]["assignment_id"],
        )
        session = db.get(ExperimentSession, result["id"])
        assert session.experiment_version_id == spec.package_version_id
        assert session.is_test_data
        assert apply_preparation(db, actor_id, spec) == first
        assert session.experiment_version_id == spec.package_version_id
        assert (
            db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "internal_experiment.prepare"
                )
            )
            == 1
        )
        assert all(value not in str(first) for value in SECRETS.values())


@pytest.mark.parametrize("state", ["draft", "pending", "approved", "revoked", "superseded"])
def test_unpublished_or_stale_package_cannot_create_objects(prepared_context, state):
    from app.models import ExperimentVersion

    factory, actor_id, spec = prepared_context
    with factory() as db:
        db.get(ExperimentVersion, spec.package_version_id).status = state
        db.commit()
        with pytest.raises(PreparationError):
            apply_preparation(db, actor_id, spec, **SECRETS)
        assert db.scalar(select(Course).where(Course.code == spec.prefix + "-course")) is None


@pytest.mark.parametrize(
    "change", ["actor", "hash", "formal", "partial", "inactive", "weak_secret"]
)
def test_invalid_input_cannot_leave_partial_preparation(prepared_context, change):
    from app.models import ExperimentVersion

    factory, actor_id, spec = prepared_context
    with factory() as db:
        if change == "actor":
            actor_id = "unknown-user"
        if change == "hash":
            spec = replace(spec, package_hash="0" * 64)
        if change == "formal":
            db.get(ExperimentVersion, spec.package_version_id).is_test_data = False
        if change == "inactive":
            db.get(User, actor_id).is_active = False
        if change == "partial":
            db.add(Course(code=spec.prefix + "-course", title="Foreign partial", is_test_data=True))
        db.commit()
        values = {**SECRETS, "student_password": "x"} if change == "weak_secret" else SECRETS
        with pytest.raises(PreparationError):
            apply_preparation(db, actor_id, spec, **values)
        assert db.scalar(select(User).where(User.username == spec.prefix + "-student")) is None
        assert db.scalar(select(Device).where(Device.device_key == spec.prefix + "-device")) is None


def test_precommit_failure_rolls_back_and_after_commit_receipt_is_recoverable(
    prepared_context, monkeypatch
):
    factory, actor_id, spec = prepared_context
    with factory() as db:
        real_commit = db.commit

        def fail():
            raise RuntimeError("injected before commit")

        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            apply_preparation(db, actor_id, spec, **SECRETS)
        monkeypatch.setattr(db, "commit", real_commit)
    with factory() as db:
        assert inspect_preparation(db, actor_id, spec)["state"] == "absent"
        apply_preparation(db, actor_id, spec, **SECRETS)  # discard response, reconnect
    with factory() as db:
        recovered = inspect_preparation(db, actor_id, spec)
        assert recovered["state"] == "ready"
        assert apply_preparation(db, actor_id, spec) == recovered


def test_existing_objects_are_not_silently_repaired_or_rebound(prepared_context):
    factory, actor_id, spec = prepared_context
    with factory() as db:
        result = apply_preparation(db, actor_id, spec, **SECRETS)
        with pytest.raises(PreparationError):
            apply_preparation(db, actor_id, replace(spec, device_kind="hardware"), **SECRETS)
        task = db.get(ExperimentAssignment, result["objects"]["assignment_id"])
        task.experiment_version_id = None
        db.commit()
        with pytest.raises(PreparationError):
            apply_preparation(db, actor_id, spec, **SECRETS)
        assert db.get(ExperimentAssignment, task.id).experiment_version_id is None
