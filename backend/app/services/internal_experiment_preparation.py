"""Explicit test-lab provisioning. No package publication or session creation.

The caller owns selection of the isolated database and authenticates the actor.
This service rechecks authority and package identity, serializes a prefix, and
commits objects and a recoverable receipt together. Existing objects are never repaired.
"""

import hashlib
import re
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select, text

from app.core.errors import InvalidRequest
from app.core.security import hash_device_token, hash_password
from app.models import (
    AuditEvent,
    Classroom,
    Course,
    Device,
    DeviceBinding,
    Enrollment,
    Experiment,
    ExperimentAssignment,
    ExperimentVersion,
    TeachingAssignment,
    User,
)
from app.models.base import utc_now
from app.models.classroom import Role
from app.services.auth import ActorContext, AuthorizationDenied, authorize_actor, user_access
from app.services.experiment_packages import load_experiment_package_runtime
from app.services.rbac import assign_role

ACTION = "internal_experiment.prepare"


class PreparationError(InvalidRequest):
    pass


@dataclass(frozen=True)
class PreparationSpec:
    prefix: str
    package_version_id: str
    package_hash: str
    device_kind: str = "synthetic"

    def __post_init__(self):
        if not re.fullmatch(r"lab-[a-z0-9][a-z0-9-]{0,35}", self.prefix):
            raise PreparationError(
                "prefix must be lab- followed by 1-36 lowercase letters/digits/hyphens"
            )
        try:
            UUID(self.package_version_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PreparationError("package version ID must be a UUID") from exc
        if not re.fullmatch(r"[a-f0-9]{64}", self.package_hash):
            raise PreparationError("package hash must be a lowercase SHA-256")
        if self.device_kind not in {"synthetic", "hardware"}:
            raise PreparationError("device kind must be synthetic or hardware")


def _authorize(db, actor_id):
    actor = db.scalar(
        select(User).where(User.id == actor_id).execution_options(populate_existing=True)
    )
    if actor is None or not actor.is_active or not actor.is_test_data:
        raise PreparationError("an active test administrator is required")
    roles, permissions = user_access(db, actor.id)
    if "admin" not in roles or not {"class.manage", "assignment.manage", "user.manage"} <= set(
        permissions
    ):
        raise PreparationError("administrator provisioning permissions are required")
    return actor


def _package(db, spec):
    try:
        runtime = load_experiment_package_runtime(db, spec.package_version_id)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    version = runtime.version
    if (
        version.status != "published"
        or not version.is_current
        or not version.is_test_data
        or not runtime.experiment.is_test_data
        or runtime.experiment.status != "active"
        or version.package_hash != spec.package_hash
    ):
        raise PreparationError("a current published test package with the exact hash is required")
    return runtime


def _receipt(db, spec):
    receipts = list(
        db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == ACTION,
                AuditEvent.details_json["prefix"].as_string() == spec.prefix,
            )
        )
    )
    if len(receipts) > 1:
        raise PreparationError("ambiguous preparation receipts; inspect without repair")
    return receipts[0] if receipts else None


def _existing(db, spec, actor_id):
    """Verify the receipt against current rows; no successful file receipt is required."""
    prefix = spec.prefix
    receipt = _receipt(db, spec)
    course = db.scalar(select(Course).where(Course.code == prefix + "-course"))
    student = db.scalar(select(User).where(User.username == prefix + "-student"))
    teacher = db.scalar(select(User).where(User.username == prefix + "-teacher"))
    device = db.scalar(select(Device).where(Device.device_key == prefix + "-device"))
    classes = list(db.scalars(select(Classroom).where(Classroom.code == prefix + "-class")))
    if not receipt:
        if any((course, student, teacher, device, classes)):
            raise PreparationError("prefix collides with existing or incomplete objects")
        return None
    details = receipt.details_json
    if (
        not receipt.is_test_data
        or receipt.actor_user_id != actor_id
        or details.get("spec") != asdict(spec)
        or details.get("schema_version") != 1
    ):
        raise PreparationError("preparation identity conflicts with the existing receipt")
    result = details.get("result", {})
    ids = result.get("objects", {})
    if (
        not all((course, student, teacher, device))
        or len(classes) != 1
        or receipt.resource_type != "course"
        or receipt.resource_id != course.id
    ):
        raise PreparationError("preparation objects missing or ambiguous")
    classroom = classes[0]
    tasks = list(
        db.scalars(
            select(ExperimentAssignment).where(ExperimentAssignment.class_id == classroom.id)
        )
    )
    bindings = list(db.scalars(select(DeviceBinding).where(DeviceBinding.device_id == device.id)))
    enrollments = list(db.scalars(select(Enrollment).where(Enrollment.class_id == classroom.id)))
    teachers = list(
        db.scalars(select(TeachingAssignment).where(TeachingAssignment.class_id == classroom.id))
    )
    if any(len(rows) != 1 for rows in (tasks, bindings, enrollments, teachers)):
        raise PreparationError("preparation scope changed; inspect without repair")
    task, binding, enrollment, teaching = tasks[0], bindings[0], enrollments[0], teachers[0]
    expected = dict(
        course_id=course.id,
        class_id=classroom.id,
        student_id=student.id,
        teacher_id=teacher.id,
        assignment_id=task.id,
        device_id=device.id,
        device_key=device.device_key,
    )
    valid = (
        ids == expected
        and result.get("state") == "ready"
        and result.get("spec") == asdict(spec)
        and course.is_test_data
        and classroom.is_test_data
        and classroom.is_active
        and classroom.course_id == course.id
        and student.is_test_data
        and student.is_active
        and teacher.is_test_data
        and teacher.is_active
        and set(user_access(db, student.id)[0]) == {"student"}
        and set(user_access(db, teacher.id)[0]) == {"teacher"}
        and task.is_test_data
        and task.status == "published"
        and task.experiment_version_id == spec.package_version_id
        and task.template_version_id is None
        and task.rule_artifact_id is None
        and task.fault_tree_artifact_id is None
        and task.starts_at is None
        and task.due_at is None
        and device.is_active
        and device.metadata_json.get("is_test_data") is True
        and device.metadata_json.get("preparation_prefix") == prefix
        and device.metadata_json.get("data_origin") == spec.device_kind
        and device.device_type == "internal-" + spec.device_kind
        and binding.is_active
        and binding.class_id == classroom.id
        and binding.student_user_id == student.id
        and binding.experiment_assignment_id == task.id
        and enrollment.user_id == student.id
        and enrollment.status == "active"
        and teaching.user_id == teacher.id
    )
    if not valid:
        raise PreparationError("preparation scope or test boundary changed; inspect without repair")
    return result


def inspect_preparation(db, actor_id, spec):
    """Read-only plan/status. A published test package remains a prerequisite."""
    if db.new or db.dirty or db.deleted:
        raise PreparationError("use a clean session for preparation")
    db.expire_all()
    _authorize(db, actor_id)
    try:
        _package(db, spec)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    existing = _existing(db, spec, actor_id)
    return existing or {
        "state": "absent",
        "spec": asdict(spec),
        "names": {
            key: spec.prefix + "-" + key
            for key in ("course", "class", "student", "teacher", "device")
        },
        "next_step": "apply with privately supplied credentials; no session will be created",
    }


def apply_preparation(
    db,
    actor_id,
    spec,
    *,
    student_password=None,
    teacher_password=None,
    device_token=None,
    recheck_access=None,
    actor_context: ActorContext | None = None,
):
    """Atomic provisioning. Retrying a committed prefix returns its unchanged receipt."""
    if not isinstance(actor_context, ActorContext) or actor_context.user_id != actor_id:
        raise AuthorizationDenied(401)
    if db.new or db.dirty or db.deleted:
        raise PreparationError("use a clean session for preparation")
    try:
        db.expire_all()
        _authorize(db, actor_id)
        if db.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(
                hashlib.sha256(("internal-lab:" + spec.prefix).encode()).digest()[:8],
                byteorder="big",
                signed=True,
            )
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        # Same experiment-parent lock as publication: a waited-on revocation is rechecked.
        version = db.get(ExperimentVersion, spec.package_version_id)
        if version is None:
            raise PreparationError("package version not found")
        db.scalar(
            select(Experiment).where(Experiment.id == version.experiment_id).with_for_update()
        )
        runtime = _package(db, spec)
        db.scalar(select(User).where(User.id == actor_id).with_for_update())
        if recheck_access is not None:
            recheck_access()
        authorize_actor(db, actor_context, "class.manage")
        _authorize(db, actor_id)
        existing = _existing(db, spec, actor_id)
        if existing:
            db.commit()
            return existing
        for value in (student_password, teacher_password, device_token):
            if not isinstance(value, str) or not 12 <= len(value) <= 512:
                raise PreparationError(
                    "new accounts and device require privately supplied 12-512 character secrets"
                )
        roles = {
            role.code: role
            for role in db.scalars(select(Role).where(Role.code.in_(["student", "teacher"])))
        }
        if len(roles) != 2:
            raise PreparationError("RBAC catalog missing; prepare the test administrator first")
        prefix = spec.prefix
        course = Course(code=prefix + "-course", title="项目内部测试课程", is_test_data=True)
        student = User(
            username=prefix + "-student",
            display_name="内部实验测试学生",
            password_hash=hash_password(student_password),
            is_test_data=True,
        )
        teacher = User(
            username=prefix + "-teacher",
            display_name="内部实验测试教师角色",
            password_hash=hash_password(teacher_password),
            is_test_data=True,
        )
        device = Device(
            device_key=prefix + "-device",
            display_name="内部测试设备（" + spec.device_kind + "）",
            device_type="internal-" + spec.device_kind,
            token_hash=hash_device_token(device_token),
            metadata_json={
                "is_test_data": True,
                "preparation_prefix": prefix,
                "data_origin": spec.device_kind,
            },
        )
        db.add_all([course, student, teacher, device])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code=prefix + "-class",
            name="项目内部测试班级",
            term="internal-test",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        task = ExperimentAssignment(
            class_id=classroom.id,
            title=runtime.experiment.name + "（内部测试）",
            experiment_version_id=spec.package_version_id,
            status="published",
            is_test_data=True,
        )
        db.add(task)
        db.flush()
        assign_role(db, student, roles["student"])
        assign_role(db, teacher, roles["teacher"])
        db.add_all(
            [
                Enrollment(class_id=classroom.id, user_id=student.id, status="active"),
                TeachingAssignment(class_id=classroom.id, user_id=teacher.id),
                DeviceBinding(
                    device_id=device.id,
                    class_id=classroom.id,
                    student_user_id=student.id,
                    experiment_assignment_id=task.id,
                    is_active=True,
                ),
            ]
        )
        result = {
            "state": "ready",
            "spec": asdict(spec),
            "objects": {
                "course_id": course.id,
                "class_id": classroom.id,
                "student_id": student.id,
                "teacher_id": teacher.id,
                "assignment_id": task.id,
                "device_id": device.id,
                "device_key": device.device_key,
            },
            "next_step": "student starts a session through the existing authorized session API",
        }
        db.add(
            AuditEvent(
                actor_user_id=actor_id,
                action=ACTION,
                resource_type="course",
                resource_id=course.id,
                details_json={
                    "schema_version": 1,
                    "prefix": prefix,
                    "spec": asdict(spec),
                    "result": result,
                },
                is_test_data=True,
                created_at=utc_now(),
            )
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
