"""Independent contracts for versioned package material identity and provenance."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from shared_write_authorization import authorize_write_fixture

from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package_payload,
    package_documents,
)

FROZEN = json.loads(
    (Path(__file__).parent / "fixtures/package_registry/frozen_v1.json").read_text()
)
SERIALIZED = json.loads(
    (Path(__file__).parent / "fixtures/package_registry/serialization_v1.json").read_text()
)


def v11_documents():
    documents = deepcopy(FROZEN["dht11_temperature_humidity"]["raw"]["documents"])
    metadata = documents["metadata.yaml"]
    metadata.update(
        schema_version="1.1",
        content_registry={
            "sources": [
                {
                    "source_id": "design",
                    "kind": "project_design",
                    "revision": "6eba821",
                    "location": "docs/project-truth-status.md",
                    "locator": "DHT11",
                    "availability": "available",
                    "sha256": None,
                }
            ],
            "units": [
                {
                    "unit_id": "interval",
                    "target": {
                        "artifact": "knowledge/concepts.yaml",
                        "entity_kind": "concept",
                        "entity_id": "dht11.minimum_interval",
                    },
                    "statement_kind": "project_configuration",
                    "source_refs": [
                        {"source_id": "design", "claim": "description", "locator": "DHT11"}
                    ],
                    "applicability": {"limits_text": "项目配置，尚未硬件验证。"},
                }
            ],
            "value_owners": [
                {
                    "parameter_id": "data_pin",
                    "owner": {
                        "target": {
                            "artifact": "hardware.yaml",
                            "entity_kind": "interface",
                            "entity_id": "dht11_gpio",
                            "field": "pins.data",
                        },
                        "unit": "gpio",
                    },
                    "copies": [
                        {
                            "target": {
                                "artifact": "hardware.yaml",
                                "entity_kind": "required_parameters",
                                "field": "data_pin",
                            },
                            "unit": "gpio",
                        }
                    ],
                }
            ],
        },
    )
    metadata["compatibility"]["engine"] = ">=2.2,<3.0"
    return documents


@pytest.mark.parametrize("package", sorted(FROZEN))
@pytest.mark.parametrize("variant", ["raw", "canonical", "missing_optional"])
def test_frozen_v1_hash_and_content_identity(package, variant):
    from app.experiment_packages.registry import content_digest

    fixture = FROZEN[package][variant]
    original = deepcopy(fixture["documents"])
    bundle, report = load_experiment_package_payload(original)
    assert report.package_hash == fixture["package_hash"]
    assert bundle.manifest.model_dump(mode="json") == fixture["manifest"]
    assert original == fixture["documents"]
    assert "content_registry" not in package_documents(bundle)["metadata.yaml"]
    assert content_digest(package_documents(bundle)) == SERIALIZED[package][variant]


def test_v11_registry_reports_unknown_sources_without_inventing_review():
    from app.experiment_packages.registry import registry_report

    bundle, _ = load_experiment_package_payload(v11_documents())
    report = registry_report(bundle, package_version_id="offline:fixture")
    assert report["source_traceability"] == "unverifiable"
    assert report["units"][0]["unit_id"] == "interval"
    assert report["units"][0]["review_status"] == "not_evaluated"
    assert len(report["units"][0]["unit_hash"]) == 64
    assert (
        "unit_hash"
        not in package_documents(bundle)["metadata.yaml"]["content_registry"]["units"][0]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_source",
        "duplicate_unit",
        "duplicate_target",
        "invalid_path",
        "cycle",
        "mismatched_value",
        "mismatched_unit",
        "case_duplicate_limits",
        "unknown_field",
        "competing_parameter_owner",
    ],
)
def test_registry_rejects_independent_invalid_fixtures(mutation):
    documents = v11_documents()
    registry = documents["metadata.yaml"]["content_registry"]
    unit = registry["units"][0]
    if mutation == "missing_source":
        unit["source_refs"][0]["source_id"] = "missing"
    elif mutation == "duplicate_unit":
        registry["units"].append(deepcopy(unit))
    elif mutation == "duplicate_target":
        registry["units"].append({**deepcopy(unit), "unit_id": "alias"})
    elif mutation == "invalid_path":
        unit["target"]["artifact"] = "../../private.txt"
    elif mutation == "cycle":
        unit["depends_on"] = ["interval"]
    elif mutation == "mismatched_value":
        documents["hardware.yaml"]["required_parameters"]["data_pin"] = 9
    elif mutation == "mismatched_unit":
        registry["value_owners"][0]["copies"][0]["unit"] = "seconds"
    elif mutation == "case_duplicate_limits":
        unit["target"] = {
            "artifact": "knowledge/cases.yaml",
            "entity_kind": "case",
            "entity_id": documents["knowledge/cases.yaml"]["cases"][0]["id"],
        }
    elif mutation == "competing_parameter_owner":
        registry["value_owners"].append(
            {
                "parameter_id": "competing_pin",
                "owner": registry["value_owners"][0]["copies"][0],
                "copies": [],
            }
        )
    else:
        unit["approved"] = True
    with pytest.raises(ExperimentPackageLoadError):
        load_experiment_package_payload(documents)


def test_v1_cannot_hide_structured_conditions_in_open_case_json():
    documents = deepcopy(FROZEN["dht11_temperature_humidity"]["raw"]["documents"])
    documents["knowledge/cases.yaml"]["cases"][0]["solutionRecord"] = {
        "confirmation_material": {
            "applicability_conditions": {
                "version": 1,
                "conditions": [
                    {
                        "field": "experiment_code",
                        "operator": "in",
                        "values": ["dht11_temperature_humidity"],
                    }
                ],
            }
        }
    }
    with pytest.raises(ExperimentPackageLoadError, match="1.1"):
        load_experiment_package_payload(documents)


def test_explicit_source_snapshot_hash_mismatch_is_rejected_without_io():
    from app.experiment_packages.registry import registry_report

    documents = v11_documents()
    source = documents["metadata.yaml"]["content_registry"]["sources"][0]
    source["sha256"] = hashlib.sha256(b"trusted source").hexdigest()
    bundle, _ = load_experiment_package_payload(documents)
    assert registry_report(bundle)["source_traceability"] == "unverifiable"
    assert (
        registry_report(bundle, trusted_sources={"design": b"trusted source"})[
            "source_traceability"
        ]
        == "verified_identity"
    )
    with pytest.raises(ValueError, match="hash"):
        registry_report(bundle, trusted_sources={"design": b"wrong source"})


def test_unit_hash_changes_with_conditions_and_dependency_content():
    from app.experiment_packages.registry import registry_report

    documents = v11_documents()
    before, _ = load_experiment_package_payload(documents)
    original = registry_report(before)["units"][0]["unit_hash"]
    documents["metadata.yaml"]["content_registry"]["units"][0]["applicability"]["limits_text"] += (
        "仅当前版本。"
    )
    after, _ = load_experiment_package_payload(documents)
    assert registry_report(after)["units"][0]["unit_hash"] != original

    unit = documents["metadata.yaml"]["content_registry"]["units"][0]
    dependency = {**deepcopy(unit), "unit_id": "bus"}
    dependency["target"]["entity_id"] = "dht11.single_bus"
    unit["depends_on"] = ["bus"]
    documents["metadata.yaml"]["content_registry"]["units"].append(dependency)
    baseline, _ = load_experiment_package_payload(documents)
    documents["knowledge/concepts.yaml"]["concepts"][1]["description"] += "这是新的限制。"
    changed, _ = load_experiment_package_payload(documents)
    assert (
        registry_report(baseline)["units"][0]["unit_hash"]
        != registry_report(changed)["units"][0]["unit_hash"]
    )


@pytest.mark.parametrize("bad_metadata", [None, "metadata", ["1.1"], {"schema_version": []}])
def test_non_object_metadata_is_a_package_error(bad_metadata):
    documents = v11_documents()
    documents["metadata.yaml"] = bad_metadata
    with pytest.raises(ExperimentPackageLoadError):
        load_experiment_package_payload(documents)


def test_v11_capability_cannot_be_bypassed_with_permissive_engine_string(monkeypatch):
    from app.experiment_packages import loader

    documents = v11_documents()
    documents["metadata.yaml"]["compatibility"]["engine"] = ">=2.0,<3.0"
    monkeypatch.setattr(loader, "DIAGNOSIS_ENGINE_VERSION", "2.1.0")
    with pytest.raises(ExperimentPackageLoadError, match="schema_capability"):
        load_experiment_package_payload(documents)


def test_renamed_case_derivation_uses_exact_source_identity_and_reports_unknown():
    from app.experiment_packages.registry import (
        content_digest,
        derived_case_matches,
        registry_report,
    )

    documents = v11_documents()
    source = {
        "kind": "case",
        "id": "original-global-case",
        "version": "3",
        "hash": content_digest({"confirmed": "fixture"}),
    }
    documents["metadata.yaml"]["content_registry"]["units"][0]["derived_from"] = [
        {**source, "relation": "adapted"}
    ]
    assert derived_case_matches(documents, source)
    assert not derived_case_matches(documents, {**source, "hash": "0" * 64})
    assert not derived_case_matches(documents, {**source, "version": "4"})
    assert not derived_case_matches(
        FROZEN["dht11_temperature_humidity"]["raw"]["documents"], source
    )
    bundle, _ = load_experiment_package_payload(documents)
    assert registry_report(bundle)["units"][0]["derivations"][0]["status"] == "unverifiable"
    provided = {"case:original-global-case:3": {"confirmed": "fixture"}}
    assert (
        registry_report(bundle, trusted_sources=provided)["units"][0]["derivations"][0]["status"]
        == "verified_identity"
    )
    with pytest.raises(ValueError, match="hash"):
        registry_report(bundle, trusted_sources={"case:original-global-case:3": {"wrong": True}})


def test_registered_derivation_lists_package_without_revoking_it(api_context):
    from sqlalchemy import select
    from test_experiment_packages import _admin_headers

    from app.models import MemoryEvent, User
    from app.services.experiment_packages import (
        import_experiment_package,
        transition_experiment_package,
    )
    from app.services.memory import digest
    from app.services.memory_governance import package_candidates

    _admin_headers(api_context)
    documents = v11_documents()
    source = {"kind": "case", "id": "old-global-id", "version": "1", "hash": "a" * 64}
    documents["metadata.yaml"]["content_registry"]["units"][0]["derived_from"] = [
        {**source, "relation": "adapted"}
    ]
    with api_context["session_factory"]() as db:
        actor = db.scalar(select(User).where(User.username == "experiment-package-admin"))
        authorize_write_fixture(db, actor)
        _, version = import_experiment_package(db, actor, documents, is_test_data=True)
        for status in ("pending", "approved", "published"):
            transition_experiment_package(db, actor, version, status)
        event = MemoryEvent(
            source_key=digest(source),
            source=source,
            actor_user_id=actor.id,
            reason="synthetic withdrawal",
        )
        db.add(event)
        db.commit()
        result = package_candidates(db, actor, event)
        assert result["items"][0]["version_id"] == version.id
        assert result["items"][0]["basis"] == "explicit_derived_source_identity_requires_review"
        assert result["items"][0]["action"] == "explicit_package_revocation_required"
        db.refresh(version)
        assert version.status == "published"


def test_case_and_concept_units_cannot_hash_only_a_convenient_fragment():
    documents = v11_documents()
    documents["metadata.yaml"]["content_registry"]["units"][0]["target"]["field"] = "description"
    with pytest.raises(ExperimentPackageLoadError, match="complete entity"):
        load_experiment_package_payload(documents)


def test_external_package_unit_snapshot_includes_its_limits_and_dependencies():
    from app.experiment_packages.registry import registry_report, unit_identity_payload

    origin, _ = load_experiment_package_payload(v11_documents())
    origin_hash = registry_report(origin)["units"][0]["unit_hash"]
    documents = v11_documents()
    documents["metadata.yaml"]["content_registry"]["units"][0]["derived_from"] = [
        {
            "kind": "package_unit",
            "package_id": "original-version-id",
            "id": "interval",
            "version": "2.0.5",
            "hash": origin_hash,
            "relation": "adapted",
        }
    ]
    adapted, _ = load_experiment_package_payload(documents)
    snapshot = unit_identity_payload(origin, "interval")
    trusted = {"package_unit:original-version-id:interval:2.0.5": snapshot}
    assert (
        registry_report(adapted, trusted_sources=trusted)["units"][0]["derivations"][0]["status"]
        == "verified_identity"
    )
    snapshot["applicability"]["limits_text"] = "wrong limits"
    with pytest.raises(ValueError, match="hash"):
        registry_report(adapted, trusted_sources=trusted)
    with pytest.raises(ValueError, match="local unit"):
        registry_report(adapted, package_version_id="original-version-id")
