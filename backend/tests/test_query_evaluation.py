"""Evaluation integrity: disjoint fixtures, actual A, and identical replay material."""

import json
from collections import Counter

from app.evaluation.query_runner import FIXTURES, collect, fixed_A, same_material_replay


def test_frozen_inputs_expectations_answers_and_split_families_are_separate():
    inputs = json.loads((FIXTURES / "inputs.json").read_text())
    expected = json.loads((FIXTURES / "expectations.json").read_text())
    answers = json.loads((FIXTURES / "answers.json").read_text())
    assert Counter(c["split"] for c in inputs) == {"development": 12, "holdout": 24}
    assert Counter(c["category"] for c in inputs if c["split"] == "holdout") == {
        key: 3
        for key in [
            "sufficient",
            "retrievable",
            "answer",
            "answered_unknown",
            "conflict_stale",
            "scope",
            "failure_resource",
            "injection",
        ]
    }
    assert len({c["family"] for c in inputs}) == 36
    assert set(expected) == {c["id"] for c in inputs}
    assert set(answers) <= set(expected)
    assert all("expected" not in c and "answer" not in c for c in inputs)
    assert all(
        v["semantic_review"] == {"status": "not_run", "judgement": None} for v in expected.values()
    )


def test_actual_fixed_graph_A_and_same_material_replay():
    case = json.loads((FIXTURES / "inputs.json").read_text())[0]
    original = fixed_A(case)
    assert {"context_builder", "rule_engine", "fault_tree_analyzer"} <= set(original["node_trace"])
    assert original["real_model_calls"] == 0
    assert original["persisted_material_replay"]["mode"] == "ai"
    assert original["persisted_material_replay"]["invented_cause_links"] == 0
    collected = collect(case, None, model_scripted=False)
    replay = same_material_replay(original["state"], collected["result"]["evidence"])
    assert replay["rules_material_hash"] == replay["ai_material_hash"]
    assert replay["real_api"] == "not_run"


def test_real_cli_is_closed_without_any_provider_attempt(monkeypatch, tmp_path):
    import sys

    import pytest

    from app.ai.clients import OpenAICompatibleClient
    from app.cli.run_query_evaluation import main

    calls = []
    monkeypatch.setattr(
        OpenAICompatibleClient, "complete_json_once", lambda *args, **kwargs: calls.append(1)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_query_evaluation", "--mode", "real", "--output", str(tmp_path / "blocked.json")],
    )
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2
    assert calls == []
