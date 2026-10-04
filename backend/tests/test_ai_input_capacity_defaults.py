"""Capacity acceptance uses a bounded synthetic source set and deployment entry points."""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.experiment_packages import context_preview as preview
from app.experiment_packages.loader import load_experiment_package

ROOT = Path(__file__).resolve().parents[2]
ALIASES = ("AI_MAX_INPUT_TOKENS", "AI_INPUT_TOKEN_LIMIT", "ai_input_token_limit")


@pytest.fixture(autouse=True)
def isolated_input_settings(monkeypatch):
    for name in ALIASES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("entry", ["direct", "example", "compose", "preview"])
def test_default_capacity_is_consistent_across_startup_entries(entry):
    if entry == "direct":
        actual = Settings(_env_file=None).ai_input_token_limit
    elif entry == "preview":
        actual = preview.preview_settings({}).ai_input_token_limit
    elif entry == "example":
        text = (ROOT / ".env.example").read_text()
        actual = int(re.search(r"^AI_MAX_INPUT_TOKENS=(\d+)$", text, re.M)[1])
    else:
        text = (ROOT / "compose.yaml").read_text()
        actual = int(re.search(r"AI_MAX_INPUT_TOKENS: \$\{AI_MAX_INPUT_TOKENS:-(\d+)\}", text)[1])
    # Accepted configuration is backed by the previous real two-package study.
    assert actual == 10000


@pytest.mark.parametrize("alias", ALIASES)
def test_explicit_lower_budget_is_preserved_for_every_settings_alias(monkeypatch, alias):
    monkeypatch.setenv(alias, "4000")
    assert Settings(_env_file=None).ai_input_token_limit == 4000


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_budget_is_still_rejected(limit):
    with pytest.raises(ValidationError, match="positive"):
        Settings(_env_file=None, ai_input_token_limit=limit)


@pytest.mark.parametrize("limit", [None, 4000])
def test_default_admits_complete_sources_but_explicit_low_budget_still_refuses(limit):
    sample = deepcopy(next(
        case for case in json.loads(preview.INPUTS.read_text())["cases"]
        if case["id"] == "text-only"
    ))
    # Independent additional reports; they cannot be discarded to make the input fit.
    sample["evidence"] += [
        {"id": f"capacity-evidence-{index}", "fact": "合成观测记录，不代表根因确认。" * 10}
        for index in range(10)
    ]
    bundle = load_experiment_package(preview.ROOT / sample["package"])[0]
    report = preview.preview_scenario(
        bundle, preview.PreviewScenario.model_validate(sample),
        budgets={} if limit is None else {"ai_input_token_limit": limit},
    )
    for stage in report["stages"].values():
        manifest = stage["context_manifest"]
        assert stage["provider_attempted"] is False
        if limit is None:
            assert stage["status"] == "prepared"
            assert stage["context_skip_code"] is None
            assert set(manifest["selected_ids"]["evidence_ids"]) == {
                row["id"] for row in sample["evidence"]
            }
            assert manifest["selected_ids"]["case_ids"] == ["fixture.sensor.failure"]
            assert manifest["budget"]["estimated_input_tokens"] <= 10000
        else:
            assert stage["status"] == "deterministic_fallback_expected"
            assert stage["context_skip_code"] == "INPUT_TOKEN_LIMIT"
            assert manifest["required_complete"] is False
