from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.evaluation.query_contract import (
    Profile,
    Requirement,
    TaskContract,
    TaskScope,
    encoded,
    project_units,
)


def contract(kind="led_report", tools=None, question="observe_led", **limits):
    experiment = "sensor" if kind == "configuration" else "led"
    return TaskContract(
        scope=TaskScope(
            task_id="task",
            actor_id="actor",
            experiment=experiment,
            component=experiment,
            session_id="session",
            diagnosis_id="diagnosis",
            package_version="synthetic-v1",
        ),
        requirements=[
            Requirement(
                id="r",
                kind=kind,
                tools=tools if tools is not None else ["query_evidence"],
                question=None if experiment == "sensor" else question,
            )
        ],
        profile=Profile(**limits),
    )


def evidence(c, value="off", source="source", **overrides):
    return {
        "id": source,
        "source_id": source,
        "source_kind": "saved_configuration_comparison"
        if c.scope.experiment == "sensor"
        else "student_report",
        "source_revision": 1,
        "requirement_id": "r",
        "scope": c.scope.identity(),
        "input_revision": 1,
        "text": "合成观察",
        "value": value,
        "is_test_data": True,
        **overrides,
    }


def task(c, records=()):
    return {"records": list(records), "checked": [], "question": None, "counts": {"questions": 0}}


def test_mismatch_satisfies_comparison_without_confirming_root_cause():
    c = contract("configuration")
    result = c.view(task(c, c.merge([], [evidence(c, "mismatch")])))
    assert result["material"][0]["state"] == "present"
    assert result["eligible_actions"] == [{"kind": "finish_satisfied"}]
    assert result["root_cause"] == "unconfirmed"


def test_unknown_answer_is_not_support():
    c = contract()
    result = c.view(task(c, [evidence(c, "unclear")]))
    assert result["material"][0] == {
        "requirement_id": "r",
        "state": "checked_empty",
        "gap_reason": "observation_unknown",
    }
    assert result["gaps"]


def test_alias_dedup_independent_same_text_and_atomic_identity_conflict():
    c = contract()
    original = [evidence(c)]
    assert len(c.merge(original, [evidence(c, id="alias")])) == 1
    assert len(c.merge(original, [evidence(c, source="independent")])) == 2
    with pytest.raises(ValueError):
        c.merge(original, [evidence(c, source="good"), evidence(c, "on", id="alias")])
    assert original == [evidence(c)]


@pytest.mark.parametrize(
    "change",
    [
        {"scope": {"task_id": "other"}},
        {"input_revision": 2},
        {"source_kind": "device_command"},
        {"value": "root_cause_confirmed"},
        {"unknown_field": "injection"},
        {"is_test_data": False},
    ],
)
def test_whole_batch_rejected_including_one_bad_row(change):
    c = contract()
    rows = [evidence(c, source="good"), evidence(c, source="bad", **change)]
    with pytest.raises(ValueError):
        c.merge([], rows)


@pytest.mark.parametrize("question", ["confirm_config", "run_shell", "https://example.com"])
def test_unapproved_cross_experiment_questions_rejected(question):
    with pytest.raises(ValueError):
        contract(question=question)


def test_archives_precede_questions_and_pending_answer_never_reasks():
    c = contract()
    d = task(c)
    assert c.view(d)["eligible_actions"][0]["kind"] == "query"
    d["checked"] = ["r:query_evidence"]
    assert c.view(d)["eligible_actions"][0]["kind"] == "ask"
    d["question"] = {"status": "consumed"}
    assert c.view(d)["eligible_actions"] == [{"kind": "finish_unknown"}]


def test_conflicting_is_distinct_from_mismatch_and_unknown():
    c = contract()
    assert (
        c.view(task(c, [evidence(c), evidence(c, "on", source="other")]))["material"][0]["state"]
        == "conflicting"
    )


def test_projection_uses_utf8_bytes_and_does_not_truncate_units():
    c = contract()
    rows = [evidence(c, source=str(i), text="观察" * 2000) for i in range(2)]
    result = project_units(rows, 8192)
    assert len(encoded(result)) <= 8192
    assert result["omitted_count"] == 2
    assert result["rows"] == []
    small = evidence(c)
    result = project_units([rows[0], small], 8192)
    assert result["rows"] == [small]
    assert result["omitted_count"] == 1


@pytest.mark.parametrize(
    "text_length,serialized_length", [(7792, 8191), (7793, 8192), (7794, 8193)]
)
def test_projection_keeps_complete_unit_at_byte_boundary(text_length, serialized_length):
    c = contract()
    first = evidence(c, source="first", text="x" * text_length)
    rows = [first] + [
        evidence(c, source=f"other{i}", text="y" * 8000) for i in range(9)
    ]
    expected = {"rows": [first], "omitted_count": 9}
    actual_size = len(json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    assert actual_size == serialized_length
    if serialized_length <= 8192:
        assert project_units(rows, 8192) == expected
    else:
        assert project_units(rows, 8192) == {"rows": [], "omitted_count": 10}


def test_old_contract_and_unbounded_profile_rejected():
    c = contract().model_dump()
    old = deepcopy(c)
    old["scope"]["contract_version"] = "query-task-v2"
    with pytest.raises(ValueError):
        TaskContract.model_validate(old)
    with pytest.raises(ValueError):
        Profile(queries=5)


@pytest.mark.parametrize(
    "field,below,at,above",
    [
        ("selection_attempts", 0, 3, 4),
        ("model_attempts", 0, 5, 6),
        ("queries", 0, 4, 5),
        ("questions", 0, 1, 2),
        ("projection_bytes", 256, 8192, 8193),
        ("active_seconds", 0.01, 120.0, 120.01),
        ("input_tokens", 1, 10000, 10001),
    ],
)
def test_profile_below_at_and_above_each_ceiling(field, below, at, above):
    assert getattr(Profile(**{field: below}), field) == below
    assert getattr(Profile(**{field: at}), field) == at
    with pytest.raises(ValueError):
        Profile(**{field: above})
    if field not in {"active_seconds"}:
        with pytest.raises(ValueError):
            Profile(**{field: True})
