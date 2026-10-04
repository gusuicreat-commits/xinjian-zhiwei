"""Stage admission and explicit profiles use independent offline expectations."""

import json
from copy import deepcopy

import pytest

from app.experiment_packages import context_preview as preview
from app.experiment_packages.loader import load_experiment_package


def scenario(name="draft-dht11"):
    samples = json.loads(preview.INPUTS.read_text())["cases"]
    return preview.PreviewScenario.model_validate(
        deepcopy(next(row for row in samples if row["id"] == name))
    )


def preview_case(case, **kwargs):
    bundle = load_experiment_package(preview.ROOT / case.package)[0]
    return preview.preview_scenario(bundle, case, **kwargs)


def test_no_approved_knowledge_only_blocks_explanation_not_reasoning():
    report = preview_case(scenario())
    assert report["matched_ids"] == []
    reasoning, explanation = (report["stages"][name] for name in ("reasoning", "explanation"))
    assert reasoning["context_manifest"]["required_complete"] is True
    assert reasoning["status"] == "prepared"
    assert reasoning["context_skip_code"] is None
    assert explanation["status"] == "deterministic_fallback_expected"
    assert explanation["context_skip_code"] == "KNOWLEDGE_NOT_READY"
    assert reasoning["provider_attempted"] is explanation["provider_attempted"] is False


@pytest.mark.parametrize(
    "stage,required,complete,selected,omitted,expected",
    [
        ("reasoning", True, True, [], 0, None),
        ("reasoning:feedback:synthetic", True, True, [], 1, None),
        ("explanation", True, True, [], 0, "KNOWLEDGE_NOT_READY"),
        ("explanation", True, True, [], 1, "KNOWLEDGE_CONTEXT_BUDGET_EXCEEDED"),
        ("explanation", False, True, [], 1, None),
        ("explanation", True, True, ["approved"], 1, None),
        ("reasoning", False, False, [], 1, "INPUT_TOKEN_LIMIT"),
        ("explanation", False, False, ["approved"], 0, "INPUT_TOKEN_LIMIT"),
    ],
)
def test_stage_policy_keeps_capacity_and_case_requirements_distinct(
    stage, required, complete, selected, omitted, expected
):
    from app.ai.context_status import stage_context_skip_code

    manifest = {
        "required_complete": complete,
        "selected_ids": {"case_ids": selected},
        "omission_counts": {"budget_omitted": omitted},
    }
    assert stage_context_skip_code(stage, manifest, require_knowledge=required) == expected


def test_unknown_stage_cannot_silently_bypass_knowledge_requirement():
    from app.ai.context_status import stage_context_skip_code

    with pytest.raises(ValueError, match="stage"):
        stage_context_skip_code("polish", {}, require_knowledge=True)


def runtime_profile(**changes):
    # Explicit in-memory settings; neither environment nor a credential file is read.
    settings = preview.preview_settings({"ai_input_token_limit": 10000})
    profile = preview.snapshot_preview_profile(settings)
    profile["settings"].update(changes)
    return profile


def test_explicit_profile_changes_explanation_requirement_and_reports_actual_limits(monkeypatch):
    case = scenario().model_copy(update={"budgets": {}})
    profile = runtime_profile(ai_require_knowledge=False, ai_timeout_seconds=17.0,
                              ai_output_token_limit=600)
    monkeypatch.setenv("AI_REQUIRE_KNOWLEDGE", "true")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "1")
    report = preview_case(case, profile=profile)
    assert report["effective_profile"] == profile
    assert report["budgets"]["ai_input_token_limit"] == 10000
    for stage in report["stages"].values():
        assert stage["status"] == "prepared"
        assert stage["context_skip_code"] is None
        assert stage["knowledge_required"] is False
        assert stage["provider_attempted"] is False
    budget = report["stages"]["explanation"]["context_manifest"]["budget"]
    assert budget["input_token_limit"] == 10000


def test_explicit_profile_cannot_be_overridden_by_scenario_or_legacy_budgets():
    case = scenario().model_copy(update={"budgets": {"ai_input_token_limit": 32000}})
    with pytest.raises(ValueError, match="conflict"):
        preview_case(case, profile=runtime_profile())
    case = case.model_copy(update={"budgets": {}})
    with pytest.raises(ValueError, match="conflict"):
        preview_case(case, profile=runtime_profile(), budgets={"ai_input_token_limit": 32000})


def test_profile_snapshot_excludes_credentials_and_unknown_fields_are_rejected():
    settings = preview.preview_settings({})
    settings = settings.model_copy(update={"ai_api_key": "SYNTHETIC_SECRET_SENTINEL"})
    profile = preview.snapshot_preview_profile(settings)
    assert "SYNTHETIC_SECRET_SENTINEL" not in json.dumps(profile)
    assert set(profile["settings"]) == set(preview.PROFILE_FIELDS)
    profile["settings"]["ai_api_key"] = "SYNTHETIC_SECRET_SENTINEL"
    with pytest.raises(ValueError):
        preview.PreviewProfile.model_validate(profile)


@pytest.mark.parametrize("field,value", [
    ("ai_input_token_limit", True), ("ai_require_knowledge", "false"),
    ("ai_total_timeout_seconds", float("inf")), ("ai_max_retries", -1),
])
def test_profile_does_not_coerce_types_or_accept_unbounded_limits(field, value):
    profile = runtime_profile(**{field: value})
    with pytest.raises(ValueError):
        preview.PreviewProfile.model_validate(profile)


def test_incomplete_profile_cannot_claim_runtime_snapshot():
    profile = runtime_profile()
    profile["settings"].pop("ai_require_knowledge")
    with pytest.raises(ValueError):
        preview.PreviewProfile.model_validate(profile)


def test_profile_cli_uses_explicit_file_and_does_not_run_provider(tmp_path, monkeypatch):
    from app.cli.preview_package_context import main

    case = scenario().model_dump(mode="json")
    case["budgets"] = {}
    inputs, profile, output = (
        tmp_path / name for name in ("inputs.json", "profile.json", "out.json")
    )
    inputs.write_text(json.dumps({"schema_version": "package-context-inputs-v1", "cases": [case]}))
    profile.write_text(json.dumps(runtime_profile(ai_require_knowledge=False)))
    monkeypatch.setattr("sys.argv", ["preview_package_context", "--inputs", str(inputs),
                                    "--profile", str(profile), "--output", str(output)])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["real_provider"]["calls"] == 0
    assert report["cases"][0]["effective_profile"]["source"] == "runtime_snapshot"
    assert report["cases"][0]["stages"]["explanation"]["status"] == "prepared"


def test_legacy_fixture_overrides_are_not_labeled_actual_configuration():
    report = preview_case(scenario())
    assert report["effective_profile"]["source"] == "fixture_defaults"


def test_tiny_explicit_capacity_blocks_both_stages_even_without_knowledge_requirement():
    case = scenario().model_copy(update={"budgets": {}})
    report = preview_case(case, profile=runtime_profile(
        ai_require_knowledge=False, ai_input_token_limit=100
    ))
    assert report["effective_profile"]["settings"]["ai_input_token_limit"] == 100
    for stage in report["stages"].values():
        assert stage["status"] == "deterministic_fallback_expected"
        assert stage["context_skip_code"] == "INPUT_TOKEN_LIMIT"
        assert stage["provider_attempted"] is False


def test_batch_preview_conflict_is_explicit_error_not_a_successful_runtime_check(tmp_path):
    case = scenario().model_dump(mode="json")
    case["budgets"] = {"ai_input_token_limit": 32000}
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"schema_version": "package-context-inputs-v1", "cases": [case]}))
    report = preview.run_package_context_preview(inputs, profile=runtime_profile())
    assert report["status"] == "error"
    assert report["reason"] == "preview_execution_or_material_invalid"
    assert report["cases"] == []
    assert report["real_provider"]["calls"] == 0
