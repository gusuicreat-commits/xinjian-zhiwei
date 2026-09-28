"""DATA-02: a new receipt freezes current handling; old receipts remain immutable."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_diagnosis_checks import check, ingest
from test_teaching_materials import start

from app.evaluation.workflow_environment import DEVICE_KEY, workflow_environment
from app.models import DiagnosisCheck, DiagnosisEpisode, DiagnosisResult, DiagnosisWorkflowRun


@pytest.fixture(params=["sqlite", "postgres"])
def env(request):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if request.param == "postgres" else None
    if request.param == "postgres" and not dsn:
        pytest.skip("requires explicitly selected test PostgreSQL")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as environment:
        yield environment


@pytest.mark.parametrize("second_tab", [False, True])
@pytest.mark.parametrize(
    "action,expected",
    [
        ("resolved", "resolved"),
        ("request_teacher_help", "escalated"),
    ],
)
def test_new_reused_receipt_reads_current_handling_without_rewriting_history(
    env,
    second_tab,
    action,
    expected,
):
    first = start(env)
    latest = first
    if second_tab:
        ingest(env)
        response = check(env, baseline_id=first["diagnosis_result_id"])
        assert response.status_code == 201, response.text
        latest = response.json()
    old_receipt = deepcopy(latest["check"])
    with env.sessions() as db:
        old_results = {row.id: deepcopy(row.result) for row in db.scalars(select(DiagnosisCheck))}
    response = env.request(
        "POST",
        f"/api/v1/student/diagnoses/{latest['diagnosis_result_id']}/feedback",
        json={"request_id": str(uuid4()), "action": action},
    )
    assert response.status_code == 201, response.text
    with env.sessions() as db:
        states = {
            e.id: (e.status, e.resolution_source) for e in db.scalars(select(DiagnosisEpisode))
        }
        assert states and all(value[0] == expected for value in states.values())
    calls = len(env.provider.calls)
    request_id = str(uuid4())
    response = check(env, request_id=request_id, baseline_id=first["diagnosis_result_id"])
    assert response.status_code == 201, response.text
    result = response.json()["check"]
    assert result["status"] == ("completed" if second_tab else "no_new_data")
    assert result["issues"]
    assert {
        i["episode_id"]: (i["handling_status"], i["resolution_source"]) for i in result["issues"]
    } == states
    assert all(i["handling_status"] == "open" for i in old_receipt["issues"])
    if second_tab:
        assert [i["observation"] for i in result["issues"]] == [
            i["observation"] for i in old_receipt["issues"]
        ]
    else:
        assert result["new_records"] == 0
        assert all(i["observation"] == "no_new_related_data" for i in result["issues"])
    replay = check(env, request_id=request_id, baseline_id=first["diagnosis_result_id"])
    assert replay.status_code == 201 and replay.json()["check"] == result
    read = env.request("GET", f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}/checks/latest")
    assert read.status_code == 200 and read.json() == result
    with env.sessions() as db:
        for row_id, value in old_results.items():
            assert db.get(DiagnosisCheck, row_id).result == value
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 1 + int(second_tab)
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowRun)) == 1 + int(
            second_tab
        )
    assert len(env.provider.calls) == calls


def test_replay_after_resolution_keeps_original_snapshot_but_new_request_refreshes(env):
    first = start(env)
    request_id = str(uuid4())
    payload = {"request_id": request_id, "baseline_id": first["diagnosis_result_id"]}
    old = check(env, **payload).json()["check"]
    assert all(i["handling_status"] == "open" for i in old["issues"])
    resolved = env.request(
        "POST",
        f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback",
        json={"request_id": str(uuid4()), "action": "resolved"},
    )
    assert resolved.status_code == 201
    replay = check(env, **payload)
    assert replay.status_code == 201 and replay.json()["check"] == old
    new = check(env, baseline_id=first["diagnosis_result_id"])
    assert new.status_code == 201
    assert all(i["handling_status"] == "resolved" for i in new.json()["check"]["issues"])


def test_repeated_no_data_checks_keep_distinct_old_and_new_incidents(env):
    first = start(env)
    resolved = env.request(
        "POST",
        f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback",
        json={"request_id": str(uuid4()), "action": "resolved"},
    )
    assert resolved.status_code == 201
    ingest(env)
    new = check(env, baseline_id=first["diagnosis_result_id"])
    assert new.status_code == 201, new.text
    body = new.json()
    states = {i["episode_id"]: i["handling_status"] for i in body["check"]["issues"]}
    assert sorted(states.values()) == ["open", "resolved"]
    calls = len(env.provider.calls)
    for _ in range(3):
        response = check(env, baseline_id=body["diagnosis_result_id"])
        assert response.status_code == 201, response.text
        receipt = response.json()["check"]
        assert receipt["status"] == "no_new_data"
        assert {i["episode_id"]: i["handling_status"] for i in receipt["issues"]} == states
    assert len(env.provider.calls) == calls
