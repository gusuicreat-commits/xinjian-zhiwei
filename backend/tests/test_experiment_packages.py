from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import hash_password
from app.diagnosis.schemas import RawDeviceRecord
from app.experiment_packages.loader import (
    load_experiment_package,
    load_experiment_packages,
    package_documents,
    package_fault_tree_document,
    package_rule_document,
)
from app.models import Device, DiagnosisEvidence, User
from app.services.ai_diagnosis import _match_structured_knowledge
from app.services.diagnosis import build_raw_diagnosis_context, diagnose, save_diagnosis_result
from app.services.experiment_packages import (
    import_experiment_package,
    load_experiment_package_runtime,
    transition_experiment_package,
)
from app.services.rbac import assign_role, ensure_rbac_catalog

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "experiment_packages"


def _admin_headers(api_context: dict[str, object]) -> dict[str, str]:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        admin = User(
            username="experiment-package-admin",
            display_name="实验包管理员",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(admin)
        db.flush()
        assign_role(db, admin, roles["admin"])
        db.commit()
    response = api_context["client"].post(
        "/api/v1/auth/session",
        json={"username": admin.username, "password": "synthetic-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _context(bundle, records):
    from app.experiment_packages.loader import package_to_experiment_definition

    context = build_raw_diagnosis_context(
        device_id="package-engine-test",
        definition=package_to_experiment_definition(bundle),
        records=records,
        evaluated_at=datetime.now(timezone.utc),
    )
    return context.model_copy(
        update={
            "package_rule_document": package_rule_document(bundle),
            "package_fault_tree_document": package_fault_tree_document(bundle),
        }
    )


def test_dht11_and_led_packages_pass_the_same_strict_contract() -> None:
    loaded = load_experiment_packages(PACKAGE_ROOT)
    assert [item[0].metadata.experiment.code for item in loaded] == [
        "dht11_temperature_humidity",
        "gpio_led_output",
    ]
    assert all(report.valid for _, report in loaded)
    assert all(len(report.package_hash) == 64 for _, report in loaded)


def test_same_engine_diagnoses_two_distinct_experiment_packages() -> None:
    dht, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    dht_context = _context(
        dht,
        [
            RawDeviceRecord(
                id=f"dht-{index}",
                source="device_log",
                payload={"error_code": "DHT11_READ_FAILED"},
            )
            for index in range(5)
        ],
    )
    led, _ = load_experiment_package(PACKAGE_ROOT / "gpio_led_output")
    led_context = _context(
        led,
        [
            RawDeviceRecord(
                id="led-low",
                source="sensor_reading",
                payload={"pin": 2, "level": 0},
            )
        ],
    )

    assert diagnose(dht_context).matches[0].error_type == "SENSOR_READ_FAILED"
    assert diagnose(led_context).matches[0].error_type == "GPIO_EXPECTATION_FAILED"


def test_package_versions_are_immutable_and_runtime_is_database_backed(
    api_context: dict[str, object],
) -> None:
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    with api_context["session_factory"]() as db:
        actor = User(
            username="package-publisher",
            display_name="实验包发布测试用户",
            password_hash="test-only",
            is_test_data=True,
        )
        db.add(actor)
        db.commit()
        documents = package_documents(bundle)
        documents["metadata.yaml"]["experiment"].pop("locale")
        experiment, version = import_experiment_package(db, actor, documents, is_test_data=True)
        with pytest.raises(ValueError, match="cannot be overwritten"):
            import_experiment_package(db, actor, package_documents(bundle), is_test_data=True)
        db.rollback()

        transition_experiment_package(db, actor, version, "pending")
        transition_experiment_package(db, actor, version, "approved")
        transition_experiment_package(db, actor, version, "published")
        runtime = load_experiment_package_runtime(db, version.id)

        assert runtime.experiment.id == experiment.id
        assert runtime.version.package_hash == version.package_hash
        assert runtime.definition.experiment.id == "dht11_temperature_humidity"


def test_package_management_api_validates_imports_and_publishes(
    api_context: dict[str, object],
) -> None:
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "gpio_led_output")
    payload = {"documents": package_documents(bundle), "is_test_data": True}
    client = api_context["client"]
    assert client.post("/api/v1/experiments/packages/validate", json=payload).status_code == 401

    headers = _admin_headers(api_context)
    validated = client.post("/api/v1/experiments/packages/validate", headers=headers, json=payload)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    imported = client.post("/api/v1/experiments/packages/import", headers=headers, json=payload)
    assert imported.status_code == 201
    version_id = imported.json()["id"]
    for package_status in ("pending", "approved", "published"):
        changed = client.post(
            f"/api/v1/experiments/package-versions/{version_id}/status",
            headers=headers,
            json={"status": package_status},
        )
        assert changed.status_code == 200
        assert changed.json()["status"] == package_status
    listed = client.get("/api/v1/experiments/package-versions", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == version_id
    assert listed.json()[0]["is_current"] is True


def test_diagnosis_persists_package_binding_and_normalized_evidence(
    api_context: dict[str, object],
) -> None:
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    context = _context(
        bundle,
        [
            RawDeviceRecord(
                id=f"raw-{index}",
                source="device_log",
                payload={"error_code": "DHT11_READ_FAILED"},
            )
            for index in range(5)
        ],
    )
    with api_context["session_factory"]() as db:
        actor = User(
            username="evidence-package-publisher",
            display_name="证据测试用户",
            password_hash="test-only",
            is_test_data=True,
        )
        db.add(actor)
        db.commit()
        experiment, version = import_experiment_package(
            db, actor, package_documents(bundle), is_test_data=True
        )
        transition_experiment_package(db, actor, version, "pending")
        transition_experiment_package(db, actor, version, "approved")
        transition_experiment_package(db, actor, version, "published")
        context = context.model_copy(
            update={
                "experiment_record_id": experiment.id,
                "experiment_version_id": version.id,
                "experiment_package_hash": version.package_hash,
                "experiment_package_is_test_data": version.is_test_data,
            }
        )
        device = db.scalar(select(Device).limit(1))
        outcome = diagnose(context)
        result = save_diagnosis_result(db, device, context, outcome)
        evidence = list(
            db.scalars(select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == result.id))
        )

        assert result.experiment_version_id == version.id
        assert result.is_test_data is True
        assert evidence
        assert all(item.experiment_version_id == version.id for item in evidence)
        assert any(item.normalized_value["kind"] == "rule_fact" for item in evidence)
        references = _match_structured_knowledge(db, result, [], Settings())
        assert [item.chunk_id for item in references] == ["dht11.sensor-read-failed.confirmed.v2"]
