import hashlib
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.classroom import AuditEvent, User
from app.models.experiment import ExperimentTemplate, ExperimentTemplateVersion

REQUIRED_FIELDS = (
    "objective",
    "steps",
    "expected_outputs",
    "device_profile",
    "sensor_fields",
    "safety_notes",
)
FORMAL_HARDWARE_FIELDS = (
    "hardware_facts.model",
    "hardware_facts.gpio_mapping",
    "hardware_facts.supply_voltage",
)
PLACEHOLDER_MARKERS = ("TODO", "待确认", "待补充")
TRANSITIONS = {
    "draft": {"pending"},
    "pending": {"approved"},
    "approved": {"published"},
    "published": {"revoked", "deactivated", "superseded"},
    "revoked": set(),
    "deactivated": set(),
    "superseded": set(),
}


def content_hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_missing(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    serialized = json.dumps(value, ensure_ascii=False)
    return any(marker in serialized for marker in PLACEHOLDER_MARKERS)


def missing_publish_fields(
    content: dict[str, Any],
    *,
    is_test_data: bool,
) -> list[str]:
    missing = []
    for field in REQUIRED_FIELDS:
        value = content.get(field)
        if _is_missing(value):
            missing.append(field)
    if not is_test_data:
        hardware_facts = content.get("hardware_facts")
        if not isinstance(hardware_facts, dict):
            missing.extend(FORMAL_HARDWARE_FIELDS)
        else:
            for field in FORMAL_HARDWARE_FIELDS:
                key = field.removeprefix("hardware_facts.")
                if _is_missing(hardware_facts.get(key)):
                    missing.append(field)
    return missing


def create_template(
    db: Session,
    actor: User,
    *,
    code: str,
    title: str,
    description: Optional[str],
    version: str,
    content: dict[str, Any],
    is_test_data: bool,
) -> tuple[ExperimentTemplate, ExperimentTemplateVersion]:
    template = ExperimentTemplate(
        code=code,
        title=title,
        description=description,
        is_test_data=is_test_data,
    )
    db.add(template)
    db.flush()
    template_version = ExperimentTemplateVersion(
        template_id=template.id,
        version=version,
        status="draft",
        content_json=content,
        content_hash=content_hash(content),
        missing_fields_json=missing_publish_fields(
            content,
            is_test_data=is_test_data,
        ),
        created_by_user_id=actor.id,
    )
    db.add(template_version)
    db.flush()
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="experiment_template.create",
            resource_type="experiment_template_version",
            resource_id=template_version.id,
            details_json={"code": code, "version": version},
            is_test_data=is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    return template, template_version


def create_template_version(
    db: Session,
    actor: User,
    template: ExperimentTemplate,
    *,
    version: str,
    content: dict[str, Any],
) -> ExperimentTemplateVersion:
    template_version = ExperimentTemplateVersion(
        template_id=template.id,
        version=version,
        status="draft",
        content_json=content,
        content_hash=content_hash(content),
        missing_fields_json=missing_publish_fields(
            content,
            is_test_data=template.is_test_data,
        ),
        created_by_user_id=actor.id,
    )
    db.add(template_version)
    db.flush()
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="experiment_template.version.create",
            resource_type="experiment_template_version",
            resource_id=template_version.id,
            details_json={"code": template.code, "version": version},
            is_test_data=template.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    return template_version


def update_content(
    db: Session,
    actor: User,
    version: ExperimentTemplateVersion,
    content: dict[str, Any],
) -> None:
    if version.status != "draft":
        raise ValueError("only draft template versions are editable")
    version.content_json = content
    version.content_hash = content_hash(content)
    template = db.get(ExperimentTemplate, version.template_id)
    version.missing_fields_json = missing_publish_fields(
        content,
        is_test_data=template.is_test_data,
    )
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="experiment_template.update",
            resource_type="experiment_template_version",
            resource_id=version.id,
            details_json={"content_hash": version.content_hash},
            is_test_data=template.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()


def transition(
    db: Session,
    actor: User,
    version: ExperimentTemplateVersion,
    target: str,
) -> None:
    if target not in TRANSITIONS.get(version.status, set()):
        raise ValueError(f"invalid template transition {version.status} -> {target}")
    template = db.get(ExperimentTemplate, version.template_id)
    missing = missing_publish_fields(
        version.content_json,
        is_test_data=template.is_test_data,
    )
    version.missing_fields_json = missing
    if target in {"approved", "published"} and missing:
        raise ValueError(f"template publication fields are incomplete: {', '.join(missing)}")
    version.status = target
    version.reviewed_by_user_id = actor.id
    if target == "published":
        prior_published = db.scalars(
            select(ExperimentTemplateVersion).where(
                ExperimentTemplateVersion.template_id == version.template_id,
                ExperimentTemplateVersion.status == "published",
                ExperimentTemplateVersion.id != version.id,
            )
        ).all()
        for prior_version in prior_published:
            prior_version.status = "superseded"
        version.published_at = utc_now()
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action=f"experiment_template.{target}",
            resource_type="experiment_template_version",
            resource_id=version.id,
            details_json={"content_hash": version.content_hash},
            is_test_data=template.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()


def get_template_version(
    db: Session,
    version_id: str,
) -> Optional[ExperimentTemplateVersion]:
    return db.scalar(
        select(ExperimentTemplateVersion).where(ExperimentTemplateVersion.id == version_id)
    )
