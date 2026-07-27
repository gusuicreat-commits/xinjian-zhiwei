import pytest

from app.core.security import hash_password
from app.models import User
from app.services.experiment_templates import (
    create_template,
    create_template_version,
    transition,
    update_content,
)


def _complete_content() -> dict[str, object]:
    return {
        "objective": "synthetic objective",
        "steps": [{"id": "s1", "instruction": "synthetic step"}],
        "expected_outputs": ["synthetic output"],
        "device_profile": {"kind": "generic-test-device"},
        "sensor_fields": [{"metric_key": "synthetic_metric", "unit": "test-unit"}],
        "safety_notes": ["synthetic safety note"],
    }


def _actor(api_context: dict[str, object]) -> User:
    with api_context["session_factory"]() as db:
        actor = User(
            username="template-test-teacher",
            display_name="合成模板教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(actor)
        db.commit()
        db.refresh(actor)
        db.expunge(actor)
        return actor


def test_incomplete_or_placeholder_template_cannot_be_approved(
    api_context: dict[str, object],
) -> None:
    actor = _actor(api_context)
    with api_context["session_factory"]() as db:
        actor = db.merge(actor)
        _, version = create_template(
            db,
            actor,
            code="SYNTH-INCOMPLETE",
            title="合成未完成模板",
            description=None,
            version="1",
            content={"objective": "TODO[待补充]"},
            is_test_data=True,
        )
        transition(db, actor, version, "pending")
        with pytest.raises(ValueError, match="incomplete"):
            transition(db, actor, version, "approved")


def test_published_version_is_immutable_and_a_new_version_is_required(
    api_context: dict[str, object],
) -> None:
    actor = _actor(api_context)
    with api_context["session_factory"]() as db:
        actor = db.merge(actor)
        template, version = create_template(
            db,
            actor,
            code="SYNTH-COMPLETE",
            title="合成完整模板",
            description=None,
            version="1",
            content=_complete_content(),
            is_test_data=True,
        )
        transition(db, actor, version, "pending")
        transition(db, actor, version, "approved")
        transition(db, actor, version, "published")

        assert version.status == "published"
        assert version.published_at is not None
        with pytest.raises(ValueError, match="only draft"):
            update_content(db, actor, version, {"objective": "changed"})

        new_version = create_template_version(
            db,
            actor,
            template,
            version="2",
            content=_complete_content(),
        )
        transition(db, actor, new_version, "pending")
        transition(db, actor, new_version, "approved")
        transition(db, actor, new_version, "published")
        db.refresh(version)

        assert version.status == "superseded"
        assert new_version.status == "published"


def test_formal_template_requires_confirmed_hardware_facts(
    api_context: dict[str, object],
) -> None:
    actor = _actor(api_context)
    with api_context["session_factory"]() as db:
        actor = db.merge(actor)
        _, version = create_template(
            db,
            actor,
            code="FORMAL-MISSING-HARDWARE",
            title="待确认硬件事实的正式模板",
            description=None,
            version="1",
            content=_complete_content(),
            is_test_data=False,
        )
        transition(db, actor, version, "pending")

        assert version.missing_fields_json == [
            "hardware_facts.model",
            "hardware_facts.gpio_mapping",
            "hardware_facts.supply_voltage",
        ]
        with pytest.raises(ValueError, match="hardware_facts"):
            transition(db, actor, version, "approved")
