import json
from copy import deepcopy

from app.evaluation import context_runner as runner


def test_independent_fixture_report_preserves_unrun_semantics(tmp_path):
    report = runner.run_context_evaluation()
    assert report["code_checks_passed"]
    assert runner.context_exit_code(report) == 0
    runner.write_context_report(report, tmp_path / "report.json")
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved["semantic_review"]["status"] == "not_run"
    assert saved["semantic_review"]["passed"] is None
    assert saved["real_provider"]["calls"] == 0
    assert saved["source_fingerprints"]


def test_expectations_are_not_sent_to_matcher_or_builder(monkeypatch):
    original = runner.exercise_input
    seen = []

    def observe(sample):
        seen.append(deepcopy(sample))
        assert "expected" not in json.dumps(sample)
        assert "eligible_ids" not in sample
        return original(sample)

    monkeypatch.setattr(runner, "exercise_input", observe)
    assert runner.run_context_evaluation()["code_checks_passed"]
    assert len(seen) == 11


def test_missing_materials_block_instead_of_passing(tmp_path):
    report = runner.run_context_evaluation(tmp_path / "missing.json")
    assert runner.context_exit_code(report) == 2
    assert not report["code_checks_passed"]


def test_invalid_source_gate_mutation_is_detected(monkeypatch):
    from app.knowledge.matcher import _rank_knowledge_cases

    # Isolated mutation: falsely approve/test-scope every source before the now
    # shared gate. The production wrapper no longer provides an unguarded route.
    def bypass(diagnosis, guidance, cases, limit):
        cases = deepcopy(cases)
        for case in cases:
            case.review_status = "approved"
            case.root_cause_status = "confirmed"
            case.facts_locked = True
            case.quality_check_passed = True
            case.is_test_data = False
        return _rank_knowledge_cases(cases, diagnosis, guidance, limit=limit)

    monkeypatch.setattr(runner, "match_knowledge_case_definitions", bypass)
    report = runner.run_context_evaluation()
    assert runner.context_exit_code(report) == 1
    failed = {case["id"] for case in report["cases"] if case["status"] == "failed"}
    assert {"CTX-F02", "CTX-F03", "CTX-F04", "CTX-F05", "CTX-F07"} <= failed


def test_serialized_truncation_mutation_is_detected(monkeypatch):
    def broken_selector(refs, settings, secrets):
        return [ref.model_copy(update={
            "content": ref.content[:settings.ai_knowledge_content_max_chars],
        }) for ref in refs], {}

    monkeypatch.setattr(runner, "select_knowledge", broken_selector)
    report = runner.run_context_evaluation()
    assert runner.context_exit_code(report) == 1
    broken = next(case for case in report["cases"] if case["id"] == "CTX-F08")
    assert broken["status"] == "error"
    assert broken["error_type"] == "JSONDecodeError"


def test_missing_eligible_match_is_separate_from_missing_source():
    sample = json.loads(runner.INPUTS.read_text())["cases"][0]
    expected = json.loads(runner.EXPECTATIONS.read_text())["cases"][sample["id"]]
    assert runner.attribute_stage(sample, expected, {"matched_ids": [], "selected_ids": []}) == (
        "matcher_missed")
    assert runner.attribute_stage({"sources": []}, {"eligible_ids": []}, {}) == "source_absent"
