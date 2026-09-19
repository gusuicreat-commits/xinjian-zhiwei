"""All intervention entrypoints use the recorded owner and audience projection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import event
from sqlalchemy.orm import Session
from test_knowledge_case_concurrency import race_scope as _race_scope
from test_knowledge_case_scope import _login

from app.models import Classroom, DeviceBinding, DiagnosisResult, InterventionCase
from app.models.intervention import InterventionEvent
from app.models.knowledge import KnowledgeCaseDraft

race_scope = _race_scope


def _diagnosis_id(ctx):
    with ctx["session_factory"]() as db:
        return db.get(KnowledgeCaseDraft, ctx["draft_id"]).diagnosis_result_id


def test_reused_intervention_projects_legacy_private_summary_and_enforces_owner(race_scope):
    ctx = race_scope
    client = ctx["client"]
    teacher = _login(client, "own-teacher")
    other = _login(client, "other-teacher")
    student = _login(client, "phase2-test-student")
    diagnosis_id = _diagnosis_id(ctx)
    path = f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention"
    assert client.post(path, headers=other).status_code == 403
    opened = client.post(path, headers=teacher)
    assert opened.status_code == 201
    case_id = opened.json()["id"]
    case_path = f"/api/v1/teacher-workflow/interventions/{case_id}"
    assert (
        client.post(
            case_path + "/actions", headers=teacher, json={"action": "claim", "expected_version": 1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            case_path + "/actions",
            headers=teacher,
            json={
                "action": "resolve",
                "expected_version": 2,
                "note": "SYNTHETIC-LEGACY-PRIVATE",
                "is_private": True,
            },
        ).status_code
        == 200
    )
    with ctx["session_factory"]() as db:
        case = db.get(InterventionCase, case_id)
        case.resolution_summary = "SYNTHETIC-LEGACY-PRIVATE"
        # Today's binding is not authority to replace historical diagnosis ownership.
        db.query(DeviceBinding).filter_by(class_id=case.class_id).update({"is_active": False})
        db.commit()
    for method, endpoint in [("GET", case_path), ("POST", path)]:
        response = client.request(method, endpoint, headers=student)
        assert response.status_code in (200, 201)
        assert response.json()["id"] == case_id
        assert response.json()["resolution_summary"] is None
        assert client.request(method, endpoint, headers=other).status_code == 403
    assert client.post(path, headers=teacher).status_code == 201
    assert client.get("/api/v1/teacher-workflow/interventions", headers=other).json() == []
    events = client.get(case_path + "/timeline", headers=teacher)
    assert events.status_code == 200
    assert any(x["note"] == "SYNTHETIC-LEGACY-PRIVATE" for x in events.json())


def test_unowned_diagnosis_cannot_borrow_current_binding_to_create_case(race_scope):
    ctx = race_scope
    client = ctx["client"]
    diagnosis_id = _diagnosis_id(ctx)
    with ctx["session_factory"]() as db:
        db.get(DiagnosisResult, diagnosis_id).context_snapshot = {"is_test_data": True}
        db.commit()
    path = f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention"
    for username in ("own-teacher", "other-teacher", "phase2-test-student"):
        assert client.post(path, headers=_login(client, username)).status_code == 403
    with ctx["session_factory"]() as db:
        assert db.query(InterventionCase).count() == 0


def test_conflicting_legacy_case_class_is_denied_on_every_entrypoint(race_scope):
    ctx = race_scope
    client = ctx["client"]
    teacher = _login(client, "own-teacher")
    other = _login(client, "other-teacher")
    path = f"/api/v1/teacher-workflow/diagnoses/{_diagnosis_id(ctx)}/intervention"
    response = client.post(path, headers=teacher)
    assert response.status_code == 201
    case_id = response.json()["id"]
    case_path = f"/api/v1/teacher-workflow/interventions/{case_id}"
    with ctx["session_factory"]() as db:
        case = db.get(InterventionCase, case_id)
        case.class_id = db.query(Classroom).filter_by(code="other-class").one().id
        case.resolution_summary = "SYNTHETIC-WRONG-CLASS-SECRET"
        db.commit()
    for headers in (teacher, other):
        assert client.get(case_path, headers=headers).status_code == 403
        assert client.post(path, headers=headers).status_code == 403
        assert client.get(case_path + "/timeline", headers=headers).status_code == 403
        assert (
            client.post(
                case_path + "/actions",
                headers=headers,
                json={"action": "claim", "expected_version": 1},
            ).status_code
            == 403
        )
        queue = client.get("/api/v1/teacher-workflow/interventions", headers=headers)
        assert queue.status_code == 200
        assert queue.json() == []
    with ctx["session_factory"]() as db:
        assert db.get(InterventionCase, case_id).version_no == 1


def test_concurrent_creation_returns_one_owned_case_and_one_help_event(race_scope):
    ctx = race_scope
    client = ctx["client"]
    headers = _login(client, "own-teacher")
    diagnosis_id = _diagnosis_id(ctx)
    path = f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention"
    engine = ctx["session_factory"].kw["bind"]
    barrier = Barrier(2)
    sessions = []

    def pause_before_insert(db, *_):
        if db.get_bind() is engine and any(isinstance(obj, InterventionCase) for obj in db.new):
            sessions.append(db)
            barrier.wait(timeout=10)

    def send(_):
        return client.post(path, headers=headers)

    if engine.dialect.name == "postgresql":
        event.listen(Session, "before_flush", pause_before_insert)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(send, range(2)))
        finally:
            event.remove(Session, "before_flush", pause_before_insert)
        assert len(sessions) == 2 and sessions[0] is not sessions[1]
    else:
        # The regular fixture uses one SQLite connection; exercise deterministic replay here.
        responses = [send(0), send(1)]
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with ctx["session_factory"]() as db:
        assert db.query(InterventionCase).count() == 1
        assert db.query(InterventionEvent).filter_by(action="request_help").count() == 1
