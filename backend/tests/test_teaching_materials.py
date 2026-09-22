"""Teaching references must never become actions, evidence, or cross-component advice."""

from copy import deepcopy

import pytest
from test_experiment_packages import PACKAGE_ROOT

from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package,
    load_experiment_package_payload,
    package_documents,
)
from app.services.teaching_materials import select_teaching_materials


def documents():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    docs = package_documents(bundle)
    docs["teaching/steps.yaml"]["bindings"] = [
        {
            "tree_id": bundle.fault_trees.trees[0].id,
            "cause_id": "wiring.data_pin_mismatch",
            "component_id": "dht11",
            "levels": [1, 2],
            "concept_ids": ["dht11.single_bus"],
            "step_ids": ["connect"],
        }
    ]
    return docs


def select(bundle, **overrides):
    args = dict(
        tree_id=bundle.fault_trees.trees[0].id,
        cause_id="wiring.data_pin_mismatch",
        level=1,
        scope={"kind": "component", "keys": ["dht11"]},
    )
    args.update(overrides)
    return select_teaching_materials(bundle, **args)


def test_selection_is_explicit_scoped_and_does_not_create_actions():
    bundle, _ = load_experiment_package_payload(documents())
    result = select(bundle)
    assert [c["concept_id"] for c in result["concepts"]] == ["dht11.single_bus"]
    assert [s["step_id"] for s in result["steps"]] == ["connect"]
    assert "actions" not in result
    for overrides in (
        {"tree_id": "foreign"},
        {"cause_id": "hardware.sensor_failure"},
        {"level": 3},
        {"scope": {"kind": "component", "keys": ["other"]}},
        {"scope": {"kind": "unknown", "keys": []}},
        {"scope": {"kind": "component", "keys": ["dht11", "other"]}},
    ):
        assert select(bundle, **overrides) == {"concepts": [], "steps": []}


@pytest.mark.parametrize(
    "mutation",
    [
        "concept",
        "step",
        "component",
        "cause",
        "tree",
        "duplicate",
        "cycle",
        "missing_dependency",
        "duplicate_concept",
    ],
)
def test_invalid_teaching_links_are_rejected(mutation):
    docs = documents()
    teaching = docs["teaching/steps.yaml"]
    binding = teaching["bindings"][0]
    if mutation in {"concept", "step"}:
        binding[f"{mutation}_ids"] = ["missing"]
    elif mutation in {"component", "cause", "tree"}:
        binding[f"{mutation}_id"] = "missing"
    elif mutation == "duplicate":
        teaching["bindings"].append(deepcopy(binding))
    elif mutation == "duplicate_concept":
        docs["knowledge/concepts.yaml"]["concepts"].append(
            deepcopy(docs["knowledge/concepts.yaml"]["concepts"][0])
        )
    elif mutation == "cycle":
        teaching["steps"][0]["prerequisite_step_ids"] = ["configure"]
        teaching["steps"][1]["prerequisite_step_ids"] = ["connect"]
    else:
        teaching["steps"][0]["prerequisite_step_ids"] = ["missing"]
    with pytest.raises(ExperimentPackageLoadError):
        load_experiment_package_payload(docs)


def test_old_packages_remain_readable_without_invented_links():
    docs = documents()
    docs["teaching/steps.yaml"].pop("bindings")
    bundle, report = load_experiment_package_payload(docs)
    assert report.valid
    assert select(bundle) == {"concepts": [], "steps": []}


def test_reference_steps_follow_dependencies_but_are_not_executed():
    docs = documents()
    docs["teaching/steps.yaml"]["steps"][1]["prerequisite_step_ids"] = ["connect"]
    docs["teaching/steps.yaml"]["bindings"][0]["step_ids"] = ["configure", "connect"]
    bundle, _ = load_experiment_package_payload(docs)
    result = select(bundle)
    assert [s["step_id"] for s in result["steps"]] == ["connect", "configure"]
    assert "completed" not in str(result)


def start(env):
    import json
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.evaluation.workflow_environment import DEVICE_KEY

    case = next(
        c
        for c in json.loads((PACKAGE_ROOT.parent / "evaluation/workflow_inputs.json").read_text())
        if c["id"] == "dht-valid"
    )
    now = datetime.now(timezone.utc).isoformat()
    response = env.request(
        "POST",
        "/api/v1/device/ingest",
        json={
            "protocolVersion": "1.0",
            "schemaVersion": "1",
            "requestId": str(uuid4()),
            "bootId": "teaching-tests",
            "sequenceNo": 1,
            "sentAt": now,
            "isTestData": True,
            "records": [{**r, "occurredAt": now} for r in case["records"]],
        },
    )
    assert response.status_code == 201, response.text
    response = env.request(
        "POST",
        f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}",
        json={"lookback_seconds": 3600, "question": "请解释异常"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def dashboard(env):
    response = env.request("GET", "/api/v1/student/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("mode", ["valid", "disabled", "timeout", "zero_budget"])
def test_http_guidance_snapshot_survives_feedback_and_all_ai_modes(mode):
    from uuid import uuid4

    from app.core.config import get_settings
    from app.evaluation.workflow_environment import workflow_environment

    with workflow_environment(
        "dht11_temperature_humidity", "timeout" if mode == "timeout" else "valid"
    ) as env:
        settings = env.app.dependency_overrides[get_settings]()
        if mode == "disabled":
            settings.ai_enabled = False
        if mode == "zero_budget":
            settings.ai_calls_per_episode = 0
        workflow = start(env)
        before = dashboard(env)["guidance"]
        materials = [h["teaching"] for g in before for h in g["hints"]]
        assert materials and any(m["status"] == "available" for m in materials)
        assert all(m["package_version"] == "2.0.5" for m in materials)
        assert all(m["is_test_data"] for m in materials)
        request = {"request_id": str(uuid4()), "action": "unresolved"}
        path = f"/api/v1/student/diagnoses/{workflow['diagnosis_result_id']}/feedback"
        for _ in range(2):
            response = env.request("POST", path, json=request)
            assert response.status_code == 201, response.text
        assert dashboard(env)["guidance"] == before
        if mode in {"disabled", "zero_budget"}:
            assert env.provider.calls == []


def test_new_release_does_not_rewrite_guidance_and_revocation_stops_display():
    from sqlalchemy import select

    from app.evaluation.workflow_environment import workflow_environment
    from app.models import User
    from app.models.experiment import ExperimentVersion
    from app.services.experiment_packages import (
        import_experiment_package,
        transition_experiment_package,
    )

    with workflow_environment("dht11_temperature_humidity") as env:
        start(env)
        before = dashboard(env)["guidance"]
        with env.sessions() as db:
            old = db.get(ExperimentVersion, env.versions[env.package])
            docs = deepcopy(old.package_content)
            docs["metadata.yaml"]["package"]["version"] = "2.0.6"
            docs["knowledge/concepts.yaml"]["concepts"][0]["description"] = "新版资料不能覆盖旧诊断"
            actor = db.scalar(select(User).where(User.username == "synthetic-teacher"))
            _, new = import_experiment_package(db, actor, docs, is_test_data=True)
            for state in ("pending", "approved", "published"):
                transition_experiment_package(db, actor, new, state)
        assert dashboard(env)["guidance"] == before
        with env.sessions() as db:
            old = db.get(ExperimentVersion, env.versions[env.package])
            actor = db.scalar(select(User).where(User.username == "synthetic-teacher"))
            transition_experiment_package(db, actor, old, "revoked")
        assert dashboard(env)["guidance"] == []


def test_reference_text_is_not_sent_to_real_provider_entry_points(monkeypatch):
    from unittest.mock import patch

    from app.evaluation import workflow_environment as module

    original = module.load_experiment_package
    secret = "教学参考专有标记_不得外发"

    def with_reference(path):
        bundle, _ = original(path)
        docs = package_documents(bundle)
        for concept in docs["knowledge/concepts.yaml"]["concepts"]:
            concept["description"] = secret
        return load_experiment_package_payload(docs)

    monkeypatch.setattr(module, "load_experiment_package", with_reference)
    with module.workflow_environment("dht11_temperature_humidity") as env:
        with patch.object(env.provider, "complete_json", wraps=env.provider.complete_json) as spy:
            start(env)
        assert {c["stage"] for c in env.provider.calls} == {"reasoning", "explanation"}
        assert secret in str(dashboard(env)["guidance"])
        for call in spy.call_args_list:
            assert secret not in call.kwargs["user_prompt"]
            assert "teaching-reference-v1" not in call.kwargs["user_prompt"]

        from uuid import uuid4

        from sqlalchemy import select
        from test_knowledge_case_drafting import FakePolishClient

        from app.core.config import get_settings
        from app.knowledge.case_drafting import generate_ai_assisted_polish
        from app.models.knowledge import KnowledgeCaseDraft

        diagnosis_id = dashboard(env)["diagnosis"]["id"]
        response = env.request(
            "POST",
            f"/api/v1/student/diagnoses/{diagnosis_id}/feedback",
            json={"request_id": str(uuid4()), "action": "resolved"},
        )
        assert response.status_code == 201, response.text
        provider = FakePolishClient()
        with env.sessions() as db:
            draft = db.scalar(
                select(KnowledgeCaseDraft).where(
                    KnowledgeCaseDraft.diagnosis_result_id == diagnosis_id
                )
            )
            assert draft is not None
            generate_ai_assisted_polish(
                db, draft, env.app.dependency_overrides[get_settings](), ai_client=provider
            )
        assert len(provider.prompts) == 1
        assert secret not in provider.prompts[0]
        assert "teaching-reference-v1" not in provider.prompts[0]


def test_old_guidance_is_not_backfilled_and_new_unavailable_material_fails_closed():
    from sqlalchemy import select

    from app.evaluation.workflow_environment import workflow_environment
    from app.models import Device, DiagnosisResult, GuidanceHistory
    from app.services.guidance import generate_guidance, history_to_evaluation
    from app.services.teaching_materials import attach_teaching_materials

    with workflow_environment("dht11_temperature_humidity") as env:
        workflow = start(env)
        with env.sessions() as db:
            diagnosis = db.get(DiagnosisResult, workflow["diagnosis_result_id"])
            record = db.scalar(
                select(GuidanceHistory).where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
            )
            original = deepcopy(record.hints)
            # Reproduce an existing record written before this optional field existed.
            record.hints = [{k: v for k, v in h.items() if k != "teaching"} for h in original]
            db.commit()
            generate_guidance(db, db.get(Device, env.device_id), diagnosis)
            db.refresh(record)
            assert all("teaching" not in h for h in record.hints)
            assert all(h.teaching is None for h in history_to_evaluation(record).hints)
            diagnosis.context_snapshot = {
                **diagnosis.context_snapshot,
                "experiment_package_hash": "wrong-hash",
            }
            result = attach_teaching_materials(
                db,
                diagnosis,
                tree_id=record.fault_tree_id,
                scope={"kind": "component", "keys": ["dht11"]},
                hints=record.hints,
            )
            assert all(h["teaching"]["status"] == "unavailable" for h in result)
            assert [h["text"] for h in result] == [h["text"] for h in original]
            assert all(not h["teaching"]["concepts"] for h in result)


def test_old_snapshot_without_new_optional_fields_keeps_its_hash():
    from sqlalchemy import select

    from app.evaluation.workflow_environment import workflow_environment
    from app.models.experiment import ExperimentVersion
    from app.services.experiment_packages import load_experiment_package_runtime

    with workflow_environment("dht11_temperature_humidity") as env:
        with env.sessions() as db:
            version = db.scalar(
                select(ExperimentVersion).where(ExperimentVersion.id == env.versions[env.package])
            )
            old_docs = deepcopy(version.package_content)
            old_docs["metadata.yaml"]["compatibility"]["engine"] = ">=2.0,<3.0"
            old_docs["teaching/steps.yaml"].pop("bindings")
            for step in old_docs["teaching/steps.yaml"]["steps"]:
                step.pop("prerequisite_step_ids", None)
            bundle, report = load_experiment_package_payload(old_docs)
            # Historical-format fixture: sign the original documents, not the new defaults.
            version.package_content = old_docs
            version.package_hash = report.package_hash
            version.package_manifest = bundle.manifest.model_dump(mode="json")
            db.commit()
            loaded = load_experiment_package_runtime(db, version.id)
            assert loaded.version.package_hash == report.package_hash
            assert loaded.bundle.steps.bindings == []
            assert version.package_content == old_docs
