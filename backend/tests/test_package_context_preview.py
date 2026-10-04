"""Offline preview exercises the runtime builders with independent synthetic inputs."""

import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai import prompts
from app.experiment_packages import context_preview as preview
from app.experiment_packages.loader import load_experiment_package


def _sample(name="text-only"):
    document = json.loads(preview.INPUTS.read_text())
    return deepcopy(next(item for item in document["cases"] if item["id"] == name))


def _bundle(sample):
    return load_experiment_package(preview.ROOT / sample["package"])[0]


def _capture_prompts(monkeypatch):
    captured = {}
    original_reasoning = preview._reasoning_prompt
    original_explanation = prompts.build_prompts

    def reasoning(*args, **kwargs):
        result = original_reasoning(*args, **kwargs)
        captured["reasoning"] = json.loads(result[1])
        return result

    def explanation(*args, **kwargs):
        result = original_explanation(*args, **kwargs)
        captured["explanation"] = args[0].model_dump(mode="json")
        return result

    monkeypatch.setattr(preview, "_reasoning_prompt", reasoning)
    monkeypatch.setattr(prompts, "build_prompts", explanation)
    return captured


def test_independent_strict_fixtures_use_both_runtime_stages(monkeypatch):
    import sqlalchemy

    from app.ai import clients
    from app.services import experiment_packages

    def forbidden(*args, **kwargs):
        raise AssertionError("offline preview attempted a Provider, database or publication")

    monkeypatch.setattr(clients, "build_ai_client", forbidden)
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(experiment_packages, "load_experiment_package_runtime", forbidden)
    report = preview.run_package_context_preview(strict=True, expectations=preview.EXPECTATIONS)
    assert report["status"] == "passed", report.get("assertions", report.get("reason"))
    assert preview.preview_exit_code(report) == 0
    assert len(report["cases"]) == 11
    assert report["real_provider"] == {
        "status": "not_run",
        "calls": 0,
        "tokens": None,
        "cost": None,
    }
    assert report["scope_authorization"] == "not_evaluated"
    for case in report["cases"]:
        assert case["stage_coverage"]["status"] == "covered"
        assert case["package"]["version_id"].startswith("offline:")
        assert not case["concept_text_provided"]
        assert not case["step_text_provided"]
        for stage in case["stages"].values():
            assert stage["provider_attempted"] is False
            assert stage["context_manifest"]["prompt_hash"]
            assert stage["context_manifest"]["budget"]["estimated_input_tokens"] > 0


def test_original_package_and_fixture_stay_immutable():
    sample = _sample("draft-dht11")
    bundle = _bundle(sample)
    original = bundle.model_dump_json()
    frozen_sample = deepcopy(sample)
    report = preview.preview_scenario(bundle, preview.PreviewScenario.model_validate(sample))
    assert bundle.model_dump_json() == original
    assert sample == frozen_sample
    assert all(case.review_status == "draft" for case in bundle.cases.cases)
    assert report["matched_ids"] == []
    assert report["matcher_trace"][0]["reason"] == "review_not_approved"
    # Runtime reasoning needs current evidence, not an approved historical case.
    assert report["stages"]["reasoning"]["status"] == "prepared"
    assert report["stages"]["explanation"]["status"] == "deterministic_fallback_expected"


def test_prompt_content_has_complete_limits_without_private_review_material(monkeypatch):
    sample = _sample()
    secret = "PRIVATE_FIXTURE_REVIEW_4729"
    fixture = sample["fixture_cases"][0]
    fixture["facts"] = {"teacher_private_note": secret}
    fixture["symptom"] = f"读取失败；{secret}。"
    fixture["solutionRecord"]["confirmation_material"]["finding"] = secret
    captured = _capture_prompts(monkeypatch)
    report = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    limits = fixture["solutionRecord"]["confirmation_material"]["applicability_limits"]
    assert report["matched_ids"] == [fixture["id"]]
    assert set(captured) == {"reasoning", "explanation"}
    for stage, payload in captured.items():
        encoded = json.dumps(payload, ensure_ascii=False)
        assert limits in encoded, stage
        assert secret not in encoded, stage
        assert "recovery_diagnosis_id" not in encoded
        assert "confirmation_material" not in encoded
    assert secret not in json.dumps(report, ensure_ascii=False)


def test_limits_change_actual_fingerprints_and_independent_case_source_hashes():
    sample = _sample()
    before = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    sample["fixture_cases"][0]["solutionRecord"]["confirmation_material"][
        "applicability_limits"
    ] += "仅供额外的特定版本条件核对。"
    after = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    assert before["fixture_source_hashes"] != after["fixture_source_hashes"]
    for stage in ("reasoning", "explanation"):
        assert (
            before["stages"][stage]["context_manifest"]["payload_sha256"]
            != (after["stages"][stage]["context_manifest"]["payload_sha256"])
        )
        assert (
            before["stages"][stage]["context_manifest"]["prompt_hash"]
            != (after["stages"][stage]["context_manifest"]["prompt_hash"])
        )


def test_required_evidence_link_missing_is_not_silently_repaired():
    sample = _sample()
    sample["candidates"][0]["evidence_refs"] = ["unprovided-evidence"]
    report = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    reasoning = report["stages"]["reasoning"]
    assert reasoning["selected_ids"] == []
    assert reasoning["context_manifest"]["required_complete"] is False
    assert reasoning["reason_codes"] == ["AI_CONTEXT_INCOMPLETE"]


def test_raw_test_answers_and_concept_text_do_not_enter_model_inputs(monkeypatch):
    sample = _sample()
    bundle = _bundle(sample)
    bundle.concepts.concepts[0].description = "CONCEPT_BODY_MUST_NOT_BE_EXPORTED"
    bundle.normal_tests.cases[0].name = "PACKAGE_TEST_ANSWER_MUST_NOT_BE_EXPORTED"
    captured = _capture_prompts(monkeypatch)
    preview.preview_scenario(bundle, preview.PreviewScenario.model_validate(sample))
    encoded = json.dumps(captured, ensure_ascii=False)
    assert "CONCEPT_BODY_MUST_NOT_BE_EXPORTED" not in encoded
    assert "PACKAGE_TEST_ANSWER_MUST_NOT_BE_EXPORTED" not in encoded


def test_expected_answers_are_read_only_after_builders(tmp_path, monkeypatch):
    expected = json.loads(preview.EXPECTATIONS.read_text())
    expected["cases"]["text-only"]["matched_ids"] = ["EXPECTED_ANSWER_SENTINEL"]
    path = tmp_path / "expected.json"
    path.write_text(json.dumps(expected))
    captured = _capture_prompts(monkeypatch)
    report = preview.run_package_context_preview(strict=True, expectations=path)
    assert preview.preview_exit_code(report) == 1
    assert report["assertions"]["text-only"]["checks"]["matched_ids"] is False
    assert "EXPECTED_ANSWER_SENTINEL" not in json.dumps(captured)


@pytest.mark.parametrize(
    "mutation",
    [
        {"expected": {"selected_ids": ["foo"]}},
        {"source_mode": "package"},
        {"budgets": {"ai_enabled": 1}},
        {"budgets": {"ai_input_token_limit": True}},
        {"stages": ["reasoning", "reasoning"]},
    ],
)
def test_scenario_contract_rejects_hidden_oracle_and_control_overrides(mutation):
    sample = _sample()
    sample.update(mutation)
    with pytest.raises(ValidationError):
        preview.PreviewScenario.model_validate(sample)


def test_settings_are_explicit_and_ignore_ambient_budgets(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "1")
    monkeypatch.setenv("AI_KNOWLEDGE_CONTENT_MAX_CHARS", "2")
    settings = preview.preview_settings({})
    assert settings.ai_input_token_limit == 10000
    assert settings.ai_knowledge_content_max_chars == 1000
    assert settings.ai_enabled is False


def test_exit_codes_distinguish_analysis_assertions_parse_errors_and_missing(tmp_path):
    analyzed = preview.run_package_context_preview()
    assert analyzed["status"] == "analyzed"
    assert preview.preview_exit_code(analyzed) == 0
    assert preview.preview_exit_code(preview.run_package_context_preview(strict=True)) == 2
    assert preview.preview_exit_code(preview.run_package_context_preview(tmp_path / "absent")) == 2
    malformed = tmp_path / "bad.json"
    malformed.write_text('{"cases": []}')
    assert preview.preview_exit_code(preview.run_package_context_preview(malformed)) == 1
    incomplete_oracle = tmp_path / "oracle.json"
    incomplete_oracle.write_text('{"schema_version":"package-context-expectations-v1","cases":{}}')
    result = preview.run_package_context_preview(strict=True, expectations=incomplete_oracle)
    assert preview.preview_exit_code(result) == 1


def test_unknown_source_is_not_reported_as_verified_and_fingerprints_are_exact():
    sample = _sample()
    report = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    trace = report["source_traceability"]
    assert trace["source_traceability"] in {"not_provided", "unverifiable"}
    assert all(item["status"] != "verified_identity" for item in trace["sources"])
    identity = preview.source_identity()
    path = "backend/app/knowledge/matcher.py"
    assert (
        identity["source_fingerprints"][path]
        == hashlib.sha256((preview.ROOT.parent / path).read_bytes()).hexdigest()
    )


def test_markdown_report_contains_separate_acceptance_boundary(tmp_path):
    report = preview.run_package_context_preview()
    target = tmp_path / "report.json"
    preview.write_preview_report(report, target)
    assert json.loads(target.read_text())["report_format"] == "package-context-preview-v1"
    assert "offline_fixture" in target.with_suffix(".md").read_text()
    assert "权限、语义、真实模型与硬件未验收" in target.with_suffix(".md").read_text()


def test_cli_missing_optional_budget_material_is_blocked(tmp_path, monkeypatch):
    from app.cli.preview_package_context import main

    monkeypatch.setattr(
        "sys.argv", ["preview_package_context", "--budgets", str(tmp_path / "absent")]
    )
    assert main() == 2


def test_cli_invalid_budget_is_execution_error(tmp_path, monkeypatch):
    from app.cli.preview_package_context import main

    path = tmp_path / "budget.json"
    path.write_text('{"arbitrary_provider_url":"must-not-be-used"}')
    monkeypatch.setattr(
        "sys.argv",
        [
            "preview_package_context",
            "--budgets",
            str(path),
            "--output",
            str(tmp_path / "out.json"),
        ],
    )
    assert main() == 1


def test_exact_packing_trace_uses_runtime_final_budget_reasons():
    sample = _sample("required-prompt-budget")
    report = preview.preview_scenario(
        _bundle(sample), preview.PreviewScenario.model_validate(sample)
    )
    for stage in report["stages"].values():
        assert stage["selection_trace"] == [
            {
                "case_id": "fixture.sensor.failure",
                "reason": "budget_omitted",
                "cleaned_chars": stage["selection_trace"][0]["cleaned_chars"],
            }
        ]
        assert stage["selection_trace"][0]["cleaned_chars"] > 0
        assert stage["selected_ids"] == []


def test_mutation_removing_limits_fails_independent_strict_oracle(monkeypatch):
    original = preview.case_references

    def broken_projection(cases):
        refs = original(cases)
        for ref in refs:
            payload = json.loads(ref.content)
            payload.pop("applicability", None)
            ref.content = json.dumps(payload, ensure_ascii=False)
        return refs

    monkeypatch.setattr(preview, "case_references", broken_projection)
    report = preview.run_package_context_preview(strict=True, expectations=preview.EXPECTATIONS)
    assert preview.preview_exit_code(report) == 1
    assert (
        report["assertions"]["text-only"]["checks"]["explanation.limits:fixture.sensor.failure"]
        is False
    )


def test_mutation_bypassing_applicability_gate_fails_independent_oracle(monkeypatch):
    from app.knowledge import matcher

    original = matcher.evaluate_case_applicability
    replacement = _sample()["fixture_cases"][0]["solutionRecord"]

    def broken_gate(solution_record, context):
        return original(replacement, context)

    monkeypatch.setattr(matcher, "evaluate_case_applicability", broken_gate)
    report = preview.run_package_context_preview(strict=True, expectations=preview.EXPECTATIONS)
    assert preview.preview_exit_code(report) == 1
    assert report["assertions"]["unknown-component"]["checks"]["matched_ids"] is False
    assert report["assertions"]["missing-limits"]["checks"]["matcher_reasons"] is False


def _source_registered_bundle(sample):
    from app.experiment_packages.loader import load_experiment_package_payload, package_documents

    documents = package_documents(_bundle(sample))
    metadata = documents["metadata.yaml"]
    metadata["schema_version"] = "1.1"
    metadata["compatibility"]["engine"] = ">=2.2,<3.0"
    source = b"independently supplied source snapshot"
    metadata["content_registry"] = {
        "sources": [
            {
                "source_id": "fixture_source",
                "kind": "project_design",
                "revision": None,
                "location": "offline://explicitly-supplied-fixture",
                "availability": "available",
                "sha256": hashlib.sha256(source).hexdigest(),
            }
        ],
        "units": [
            {
                "unit_id": "fixture-concept",
                "statement_kind": "pending_proposal",
                "target": {
                    "artifact": "knowledge/concepts.yaml",
                    "entity_kind": "concept",
                    "entity_id": documents["knowledge/concepts.yaml"]["concepts"][0]["concept_id"],
                },
                "source_refs": [
                    {
                        "source_id": "fixture_source",
                        "claim": "description",
                        "locator": "whole synthetic text",
                    }
                ],
                "applicability": {"limits_text": "仅用于来源比对，不构成真实依据。"},
            }
        ],
    }
    return load_experiment_package_payload(documents)[0], source


def test_v11_source_identity_unknown_verified_and_mismatch_stay_distinct():
    sample = _sample()
    bundle, source = _source_registered_bundle(sample)
    scenario = preview.PreviewScenario.model_validate(sample)
    unknown = preview.preview_scenario(bundle, scenario)["source_traceability"]
    assert unknown["source_traceability"] == "unverifiable"
    assert unknown["sources"] == [{"source_id": "fixture_source", "status": "unverifiable"}]
    assert len(unknown["units"][0]["unit_hash"]) == 64
    known = preview.preview_scenario(bundle, scenario, trusted_sources={"fixture_source": source})[
        "source_traceability"
    ]
    assert known["source_traceability"] == "verified_identity"
    assert known["units"][0]["review_status"] == "not_evaluated"
    with pytest.raises(ValueError, match="hash"):
        preview.preview_scenario(bundle, scenario, trusted_sources={"fixture_source": b"different"})
