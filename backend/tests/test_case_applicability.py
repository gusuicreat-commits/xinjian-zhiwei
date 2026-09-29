from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.knowledge.matcher import match_knowledge_case_definitions
from app.schemas.knowledge_case import CaseConfirmationMaterial

LIMITS = "只适用于已核对接线的 DHT11；没有独立恢复测量时不得确认根因。"


def case_record(case_id="case-1", **updates):
    values = dict(
        id=case_id, experiment_type="dht11", error_type="READ_FAILED", symptom="read failed",
        normal_state={}, evidence=[], possible_causes=["wiring"], solution_steps=["检查接线"],
        teacher_notes=None, root_cause_value="wiring", root_cause_status="confirmed",
        source_ref="review:one", version="1", is_test_data=False, review_status="approved",
        facts_locked=True, quality_check_passed=True, facts={},
        solution_record={"confirmation_material": {"applicability_limits": LIMITS}},
    )
    values.update(updates)
    return SimpleNamespace(**values)


def diagnosis_record(**updates):
    values = dict(
        experiment_id="dht11", experiment_version_id="version-1", is_test_data=False,
        matched_rules=[{"error_type": "READ_FAILED", "summary": "read failed", "evidence": []}],
        context_snapshot={
            "experiment_id": "dht11", "experiment_version": "2.0.5",
            "experiment_version_id": "version-1", "experiment_package_hash": "a" * 64,
        },
    )
    values.update(updates)
    return SimpleNamespace(**values)


def guidance_record(keys=None, *, kind="component"):
    return SimpleNamespace(
        fault_tree_scope={"kind": kind, "keys": ["dht11"] if keys is None else keys},
        ranked_causes=[],
    )


def conditional_case(*conditions, **updates):
    record = case_record(**updates)
    record.solution_record["confirmation_material"]["applicability_conditions"] = {
        "version": 1, "conditions": list(conditions),
    }
    return record


def condition(field, *values):
    return {"field": field, "operator": "in", "values": list(values)}


@pytest.mark.parametrize("solution_record", [
    {}, {"confirmation_material": {}},
    {"confirmation_material": {"applicability_limits": "   "}},
    {"confirmation_material": {"applicability_limits": 123}},
])
def test_missing_or_invalid_limits_are_not_recalled(solution_record):
    matched = match_knowledge_case_definitions(
        diagnosis_record(), [], [case_record(solution_record=solution_record)],
    )
    assert matched == []


def test_limits_kept_from_only_authoritative_source_and_private_data_not_serialized():
    record = case_record()
    record.solution_record["confirmation_material"]["teacher_private_note"] = "private-secret"
    matched = match_knowledge_case_definitions(diagnosis_record(), [], [record])
    assert len(matched) == 1
    assert matched[0].applicability.limits_text == LIMITS
    assert matched[0].applicability.condition_status == "text_only"
    assert "private-secret" not in matched[0].model_dump_json()
    assert matched[0]._sensitive_sources


def test_component_mismatch_is_filtered_before_top_k():
    mismatch = conditional_case(
        condition("experiment_code", "dht11"), condition("component_id", "other"),
        case_id="case-0",
    )
    good = case_record("case-1")
    matched = match_knowledge_case_definitions(
        diagnosis_record(), [guidance_record()], [mismatch, good], limit=1,
    )
    assert [item.case_id for item in matched] == ["case-1"]


def test_all_declared_conditions_must_match_fixed_snapshot():
    record = conditional_case(
        condition("experiment_code", "dht11"), condition("package_version", "2.0.5"),
        condition("component_id", "dht11"),
    )
    matched = match_knowledge_case_definitions(diagnosis_record(), [guidance_record()], [record])
    assert matched[0].applicability.condition_status == "matched"
    assert {check.field for check in matched[0].applicability.checks} == {
        "experiment_code", "package_version", "component_id",
    }
    assert all(check.status == "matched" for check in matched[0].applicability.checks)


@pytest.mark.parametrize("guidance", [
    [], [guidance_record(["dht11", "second"])], [guidance_record(kind="interface")],
    [guidance_record(), guidance_record(["second"])],
])
def test_missing_or_ambiguous_component_scope_is_not_guessed(guidance):
    record = conditional_case(
        condition("experiment_code", "dht11"), condition("component_id", "dht11"),
    )
    assert match_knowledge_case_definitions(diagnosis_record(), guidance, [record]) == []


def test_unbound_package_version_is_unknown_even_if_legacy_version_text_exists():
    record = conditional_case(
        condition("experiment_code", "dht11"), condition("package_version", "2.0.5"),
    )
    diagnosis = diagnosis_record(experiment_version_id=None)
    diagnosis.context_snapshot.pop("experiment_version_id")
    assert match_knowledge_case_definitions(diagnosis, [], [record]) == []


@pytest.mark.parametrize("updates", [
    {"review_status": "draft"}, {"root_cause_status": "unknown"}, {"facts_locked": False},
    {"quality_check_passed": False}, {"is_test_data": True},
    {"experiment_type": "led"}, {"error_type": "OTHER"},
])
def test_applicability_does_not_relax_existing_eligibility(updates):
    assert match_knowledge_case_definitions(diagnosis_record(), [], [case_record(**updates)]) == []


@pytest.mark.parametrize("conditions", [
    [], [condition("experiment_code")], [condition("firmware", "1")],
    [condition("component_id", "dht11")],
    [condition("experiment_code", "dht11"), condition("experiment_code", "led")],
    [{"field": "experiment_code", "operator": "eval", "values": ["dht11"]}],
])
def test_malformed_declared_conditions_are_rejected_by_approval_schema(conditions):
    with pytest.raises(ValidationError):
        CaseConfirmationMaterial.model_validate({
            "method": "measurement", "finding": "measured recovery",
            "recovery_diagnosis_id": "a" * 36, "applicability_limits": LIMITS,
            "applicability_conditions": {"version": 1, "conditions": conditions},
        })


def test_old_approval_without_structured_conditions_still_valid():
    value = CaseConfirmationMaterial.model_validate({
        "method": "measurement", "finding": "measured recovery",
        "recovery_diagnosis_id": "a" * 36, "applicability_limits": LIMITS,
    })
    assert value.applicability_conditions is None


def test_condition_values_deduplicated_without_changing_order_or_source():
    from app.knowledge.applicability import CaseApplicabilityContext, evaluate_case_applicability

    record = conditional_case(condition("experiment_code", "dht11", "dht11", "led"))
    original = deepcopy(record.solution_record)
    result = evaluate_case_applicability(
        record.solution_record, CaseApplicabilityContext(experiment_code="dht11"),
    )
    assert result.projection.checks[0].values == ["dht11", "led"]
    assert record.solution_record == original


def test_trace_explains_qualification_and_top_k_without_private_content():
    from app.knowledge.matcher import match_case_candidates

    no_limits = case_record("missing", solution_record={})
    wrong = conditional_case(condition("experiment_code", "led"), case_id="wrong")
    unreviewed = case_record("draft", review_status="draft")
    matched, trace = match_case_candidates(
        [no_limits, wrong, unreviewed, case_record("a"), case_record("b")],
        diagnosis_record(), [], limit=1,
    )
    assert [item.case_id for item in matched] == ["a"]
    by_id = {item["case_id"]: item for item in trace}
    assert by_id["missing"]["reason"] == "applicability_missing"
    assert by_id["wrong"]["reason"] == "applicability_mismatch"
    assert by_id["draft"]["reason"] == "review_not_approved"
    assert by_id["b"]["reason"] == "top_k_omitted"
    assert LIMITS not in repr(trace)


def test_other_notes_do_not_backfill_missing_authoritative_limits():
    record = case_record(solution_record={}, teacher_notes=LIMITS, facts={"limits": LIMITS})
    assert match_knowledge_case_definitions(diagnosis_record(), [], [record]) == []


def test_conflicting_frozen_experiment_identity_is_unknown():
    from app.knowledge.matcher import match_case_candidates

    diagnosis = diagnosis_record()
    diagnosis.context_snapshot["experiment_id"] = "led"
    record = conditional_case(condition("experiment_code", "dht11"))
    matched, trace = match_case_candidates([record], diagnosis, [])
    assert matched == []
    assert trace[0]["reason"] == "applicability_unknown"


def test_old_limits_are_not_trimmed_or_mutated():
    limits = "  条件 A\n条件 B  "
    record = case_record(solution_record={
        "confirmation_material": {"applicability_limits": limits},
    })
    matched = match_knowledge_case_definitions(diagnosis_record(), [], [record])
    assert matched[0].applicability.limits_text == limits


def test_global_and_package_paths_produce_same_controlled_projection():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.knowledge.matcher import match_knowledge_cases
    from app.models.knowledge import KnowledgeCase

    good = conditional_case(
        condition("experiment_code", "dht11"), condition("component_id", "dht11"),
    )
    records = [good, case_record("missing", solution_record={}),
               case_record("draft", review_status="draft")]
    diagnosis, guidance = diagnosis_record(), [guidance_record()]
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(KnowledgeCase(**vars(record)) for record in records)
            db.commit()
            database_matches = match_knowledge_cases(db, diagnosis, guidance)
            package_matches = match_knowledge_case_definitions(diagnosis, guidance, records)
            assert len(database_matches) == len(package_matches) == 1
            assert database_matches[0].model_dump() == package_matches[0].model_dump()
    finally:
        engine.dispose()
