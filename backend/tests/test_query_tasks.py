"""XJ-004 independent expectations: contract §§6-8 and task acceptance criteria.

Every case uses the explicit disposable PostgreSQL schema, including HTTP cases.
"""

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from test_query_sources import add_case, evidence, make_formal
from test_query_sources import real_task as source_real_task_fixture
from test_query_sources import task as source_task_fixture

from app.core.security import hash_device_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AuthSession,
    Classroom,
    Course,
    Device,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    QueryAnswerReceipt,
    QueryQuestion,
    QueryTask,
    User,
)
from app.services import query_tasks
from app.services.auth import AuthorizationDenied
from app.services.memory import package_source, register_stop

task = source_task_fixture
real_task = source_real_task_fixture

TEST_DEVICE_ID = "phase2-test-device"
TEST_DEVICE_TOKEN = "phase2-test-token-not-for-production"


@pytest.fixture
def api_context() -> Generator[dict[str, Any], None, None]:
    # Required explicit isolated PostgreSQL; missing DSN fails, never skips.
    url = make_url(os.environ["XINJIAN_EVAL_POSTGRES_DSN"]).set(drivername="postgresql+psycopg")
    admin = create_engine(url)
    schema = "xj004_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema},public"}))
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        device = Device(
            device_key=TEST_DEVICE_ID,
            display_name="明确标记的 Phase 2 测试设备",
            device_type="test-fixture",
            token_hash=hash_device_token(TEST_DEVICE_TOKEN, iterations=1_000),
        )
        student = User(
            username="phase2-test-student",
            display_name="Phase 2 合成学生",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        course = Course(
            code="phase2-test-course",
            title="Phase 2 合成课程",
            is_test_data=True,
        )
        db.add_all([device, student, course])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code="phase2-test-class",
            name="Phase 2 合成班级",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        assignment = ExperimentAssignment(
            class_id=classroom.id,
            title="Phase 2 合成实验",
            status="published",
            is_test_data=True,
        )
        db.add(assignment)
        db.flush()
        experiment_session = ExperimentSession(
            experiment_assignment_id=assignment.id,
            student_user_id=student.id,
            device_id=device.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(experiment_session)
        db.commit()
        experiment_session_id = experiment_session.id

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": testing_session,
            "headers": {
                "X-Device-ID": TEST_DEVICE_ID,
                "X-Device-Token": TEST_DEVICE_TOKEN,
                "X-Experiment-Session-ID": experiment_session_id,
            },
            "experiment_session_id": experiment_session_id,
        }
    app.dependency_overrides.clear()
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def begin(task):
    return query_tasks.start_query(task["db"], task["identity"], task["diagnosis"].id)


def answer_payload(result, value="matches_table", request_id=None):
    question = result["question"]
    return dict(
        request_id=request_id or str(uuid4()),
        question_id=question["question_id"],
        question_version=question["version"],
        value=value,
    )


def submit(task, result, payload):
    return query_tasks.submit_answer(task["db"], task["identity"], result["id"], **payload)


def assert_unconsumed(task):
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryAnswerReceipt)) == 0
        assert db.scalar(select(QueryQuestion.status)) == "open"
        assert db.scalar(select(QueryTask.status)) == "waiting_answer"


def test_repeated_start_and_unclear_never_ask_again(task, monkeypatch):
    first = begin(task)
    assert first["query_count"] == 4 and first["question_count"] == 1
    assert first["status"] == "waiting_answer"
    # Revalidation is allowed on replay; no new acquisition/registration is allowed.
    original = query_tasks._acquire_sources

    def unexpected(*args):
        pytest.fail("repeat start acquired sources again")

    monkeypatch.setattr(query_tasks, "_acquire_sources", unexpected)
    assert begin(task) == first
    payload = answer_payload(first, "unclear")
    receipt = submit(task, first, payload)
    assert receipt["value"] == "unclear"
    final = begin(task)
    assert final["status"] == "finish_unknown" and final["question"] is None
    assert final["requirements"]["wiring_observation"]["gap"] == "observation_unknown"
    assert final["question_count"] == 1
    monkeypatch.setattr(query_tasks, "_acquire_sources", original)


def test_request_replay_conflict_and_ended_session_receipt(task):
    result = begin(task)
    payload = answer_payload(result)
    first = submit(task, result, payload)
    assert submit(task, result, payload) == first
    with pytest.raises(query_tasks.QueryConflict):
        submit(task, result, {**payload, "value": "differs"})
    session = task["db"].get(ExperimentSession, task["identity"].session_id)
    session.status = "completed"
    session.ended_at = datetime.now(timezone.utc)
    task["db"].commit()
    assert submit(task, result, payload) == first
    with pytest.raises(AuthorizationDenied):
        submit(task, result, {**payload, "request_id": str(uuid4())})
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryAnswerReceipt)) == 1


def test_waiting_session_ended_rejects_new_answer(task):
    result = begin(task)
    session = task["db"].get(ExperimentSession, task["identity"].session_id)
    session.status = "completed"
    session.ended_at = datetime.now(timezone.utc)
    task["db"].commit()
    with pytest.raises(AuthorizationDenied):
        submit(task, result, answer_payload(result))
    assert_unconsumed(task)


def test_revocation_in_submit_transaction_no_receipt_or_consumption(task, monkeypatch):
    result = begin(task)
    original = query_tasks.authorize_student_actor
    calls = 0

    def revoke_after_authorization(db, *args, **kwargs):
        nonlocal calls
        calls += 1
        current = original(db, *args, **kwargs)
        if calls == 1:
            db.query(Enrollment).update({"status": "withdrawn"})
        return current

    monkeypatch.setattr(query_tasks, "authorize_student_actor", revoke_after_authorization)
    with pytest.raises(AuthorizationDenied):
        submit(task, result, answer_payload(result))
    assert calls >= 2
    assert_unconsumed(task)


def test_other_transaction_revokes_while_submit_waits(task, monkeypatch):
    result = begin(task)
    payload = answer_payload(result)
    identity = task["identity"]
    entered = Event()
    original = query_tasks.authorize_student_actor

    def signal(*args, **kwargs):
        entered.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(query_tasks, "authorize_student_actor", signal)

    def worker():
        with task["factory"]() as db:
            with pytest.raises(AuthorizationDenied):
                query_tasks.submit_answer(db, identity, result["id"], **payload)

    with task["factory"]() as revoker, ThreadPoolExecutor(max_workers=1) as pool:
        revoker.scalar(select(Device).where(Device.id == identity.device_id).with_for_update())
        future = pool.submit(worker)
        assert entered.wait(5)
        # Observe real PG lock waiting before committing withdrawal.
        import time

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with task["factory"]() as observer:
                waiting = observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type='Lock' AND query LIKE '%devices%'"
                    )
                )
            if waiting:
                break
            time.sleep(0.01)
        assert waiting, "submission did not actually wait on PostgreSQL device lock"
        revoker.query(Enrollment).update({"status": "withdrawn"})
        revoker.commit()
        future.result(timeout=10)
    assert_unconsumed(task)


def test_two_concurrent_answers_only_one_is_adopted(task):
    result = begin(task)
    identity = task["identity"]

    def worker(value):
        with task["factory"]() as db:
            try:
                return query_tasks.submit_answer(
                    db, identity, result["id"], **answer_payload(result, value)
                )
            except query_tasks.QueryConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["matches_table", "differs"]))
    assert sum(isinstance(row, dict) for row in results) == 1
    assert results.count("conflict") == 1
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryAnswerReceipt)) == 1
        assert db.scalar(select(QueryQuestion.status)) == "closed"


def test_formal_scope_finishes_unknown_without_question(task):
    make_formal(task)
    result = begin(task)
    assert result["status"] == "finish_unknown"
    assert result["question"] is None and result["question_count"] == 0
    assert result["requirements"]["wiring_observation"]["gap"] == "question_not_approved"


def test_package_stop_returns_stale_without_saved_conclusion(task):
    evidence(task)
    result = begin(task)
    assert result["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "match"
    register_stop(task["db"], package_source(task["version"]), task["student"], "synthetic stop")
    task["db"].commit()
    current = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert current["status"] == "stale" and current["question"] is None
    assert current["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "unknown"
    with pytest.raises(query_tasks.QueryConflict):
        submit(task, result, answer_payload(result))
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryAnswerReceipt)) == 0


def test_revoked_read_and_missing_task_have_identical_denial(task):
    result = begin(task)
    task["db"].query(Enrollment).update({"status": "withdrawn"})
    task["db"].commit()
    errors = []
    for identifier in (result["id"], str(uuid4())):
        with pytest.raises(AuthorizationDenied) as exc:
            query_tasks.read_query(task["db"], task["identity"], identifier)
        errors.append((exc.value.status_code, str(exc.value)))
    assert errors[0] == errors[1] == (403, "current authorization is no longer valid")


def account_headers(context, task):
    from app.core.security import hash_session_token

    raw = "xj004-synthetic-bearer"
    with context["session_factory"]() as db:
        auth = db.get(AuthSession, task["identity"].account.session_id)
        auth.token_hash = hash_session_token(raw)
        db.commit()
    return {
        "Authorization": f"Bearer {raw}",
        "X-Device-ID": TEST_DEVICE_ID,
        "X-Experiment-Session-ID": task["identity"].session_id,
    }


def test_http_ingest_publish_save_start_answer_read_end_to_end(api_context, real_task):
    current = real_task([({"gpio": 5}, "0.2.5", "xj004-boot")])
    headers = account_headers(api_context, current)
    client = api_context["client"]
    started = client.post(
        f"/api/v1/student/diagnoses/{current['diagnosis'].id}/queries", headers=headers
    )
    assert started.status_code == 200, started.text
    result = started.json()
    assert result["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "mismatch"
    payload = answer_payload(result)
    response = client.post(
        f"/api/v1/student/queries/{result['id']}/answers", headers=headers, json=payload
    )
    assert response.status_code == 200, response.text
    assert response.json()["value"] == "matches_table"
    final = client.get(f"/api/v1/student/queries/{result['id']}", headers=headers)
    assert final.status_code == 200, final.text
    assert final.json()["requirements"]["wiring_observation"]["judgement"] == "matches_table"
    assert final.json()["root_cause_status"] == "unconfirmed"
    assert final.headers["cache-control"] == "no-store"
    assert "raw_payload" not in final.text and "source_manifest" not in final.text


def test_two_concurrent_starts_register_one_task_and_question(task):
    identity = task["identity"]
    diagnosis_id = task["diagnosis"].id

    def worker(_):
        with task["factory"]() as db:
            return query_tasks.start_query(db, identity, diagnosis_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert results[0] == results[1]
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryTask)) == 1
        assert db.scalar(select(func.count()).select_from(QueryQuestion)) == 1
        assert db.scalar(select(QueryTask.query_count)) == 4


def test_revocation_at_receipt_flush_rolls_back_answer_and_task(task):
    from sqlalchemy import event

    result = begin(task)
    injected = False

    def revoke(db, flush_context, instances):
        nonlocal injected
        if any(isinstance(row, QueryAnswerReceipt) for row in db.new):
            injected = True
            db.execute(Enrollment.__table__.update().values(status="withdrawn"))

    event.listen(task["db"], "before_flush", revoke)
    try:
        with pytest.raises(AuthorizationDenied):
            submit(task, result, answer_payload(result))
    finally:
        event.remove(task["db"], "before_flush", revoke)
    assert injected
    assert_unconsumed(task)


def test_invalid_question_version_does_not_consume_question(task):
    result = begin(task)
    payload = answer_payload(result)
    with pytest.raises(query_tasks.QueryConflict):
        submit(task, result, {**payload, "question_version": "wrong-version"})
    assert_unconsumed(task)
    receipt = submit(task, result, payload)
    assert receipt["value"] == "matches_table"


def test_http_auth_conflicts_replay_and_revoked_object_non_disclosure(api_context, task):
    headers = account_headers(api_context, task)
    client = api_context["client"]
    path = f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries"
    assert client.post(path).status_code == 401
    started = client.post(path, headers=headers)
    assert started.status_code == 200, started.text
    result = started.json()
    assert client.post(path, headers=headers).json() == result
    answer_path = f"/api/v1/student/queries/{result['id']}/answers"
    payload = answer_payload(result, "differs")
    first = client.post(answer_path, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert client.post(answer_path, headers=headers, json=payload).json() == first.json()
    assert (
        client.post(answer_path, headers=headers, json={**payload, "value": "unclear"}).status_code
        == 409
    )
    with task["factory"]() as db:
        session = db.get(ExperimentSession, task["identity"].session_id)
        session.status = "completed"
        session.ended_at = datetime.now(timezone.utc)
        db.commit()
    assert client.post(answer_path, headers=headers, json=payload).json() == first.json()
    assert (
        client.post(
            answer_path, headers=headers, json={**payload, "request_id": str(uuid4())}
        ).status_code
        == 403
    )
    with task["factory"]() as db:
        db.query(Enrollment).update({"status": "withdrawn"})
        db.commit()
    responses = [
        client.get(f"/api/v1/student/queries/{identifier}", headers=headers)
        for identifier in (result["id"], str(uuid4()))
    ]
    assert responses[0].status_code == responses[1].status_code == 403
    assert responses[0].json() == responses[1].json()
    denied = client.post(answer_path, headers=headers, json=payload)
    assert denied.status_code == 403


def test_revocation_after_protected_write_waits_until_receipt_commits(task, monkeypatch):
    import time

    result = begin(task)
    identity = task["identity"]
    payload = answer_payload(result)
    ready = Event()
    release = Event()
    revoking = Event()
    original = query_tasks._receipt

    def hold_receipt(record):
        ready.set()
        assert release.wait(5)
        return original(record)

    monkeypatch.setattr(query_tasks, "_receipt", hold_receipt)

    def writer():
        with task["factory"]() as db:
            return query_tasks.submit_answer(db, identity, result["id"], **payload)

    def revoke():
        with task["factory"]() as db:
            revoking.set()
            db.query(Enrollment).update({"status": "withdrawn"})
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_future = pool.submit(writer)
        assert ready.wait(5)
        revoke_future = pool.submit(revoke)
        assert revoking.wait(5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with task["factory"]() as observer:
                waiting = observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                        "AND query LIKE '%UPDATE enrollments%'"
                    )
                )
            if waiting:
                break
            time.sleep(0.01)
        release.set()
        assert waiting, "withdrawal did not wait for the protected answer transaction"
        assert write_future.result(timeout=10)["value"] == "matches_table"
        revoke_future.result(timeout=10)
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryAnswerReceipt)) == 1
    with pytest.raises(AuthorizationDenied):
        submit(task, result, payload)


def test_sql_lock_wait_obeys_remaining_execution_budget(task, monkeypatch):
    import time

    identity = task["identity"]
    diagnosis_id = task["diagnosis"].id
    monkeypatch.setattr(query_tasks, "ACTIVE_SECONDS", 0.15)

    def worker():
        with task["factory"]() as db:
            with pytest.raises(query_tasks.QueryUnavailable, match="query_temporarily_unavailable"):
                query_tasks.start_query(db, identity, diagnosis_id)

    with task["factory"]() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.scalar(select(Device).where(Device.id == identity.device_id).with_for_update())
        started = time.monotonic()
        pool.submit(worker).result(timeout=5)
        assert time.monotonic() - started < 2
        blocker.rollback()
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryTask)) == 0
        assert db.scalar(select(func.count()).select_from(QueryQuestion)) == 0
    monkeypatch.setattr(query_tasks, "ACTIVE_SECONDS", 120)
    assert begin(task)["status"] == "waiting_answer"


def test_revocation_after_source_return_adopts_nothing(task, monkeypatch):
    source_type = type(query_tasks.SOURCES["task_evidence"])
    original = source_type.query
    injected = False

    def revoke_on_return(self, db, scope, requirement=None):
        nonlocal injected
        result = original(self, db, scope, requirement)
        if self.kind == "task_evidence" and not injected:
            injected = True
            db.query(Enrollment).update({"status": "withdrawn"})
        return result

    monkeypatch.setattr(source_type, "query", revoke_on_return)
    with pytest.raises(AuthorizationDenied):
        begin(task)
    assert injected
    with task["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(QueryTask)) == 0
        assert db.scalar(select(func.count()).select_from(QueryQuestion)) == 0


def test_source_order_and_question_registration_count(task, monkeypatch):
    order = []
    source_type = type(query_tasks.SOURCES["task_evidence"])
    original = source_type.query

    def observe(self, db, scope, requirement=None):
        if requirement is not None:
            order.append(self.kind)
        return original(self, db, scope, requirement)

    monkeypatch.setattr(source_type, "query", observe)
    result = begin(task)
    assert order == [
        "task_evidence",
        "firmware_reported_config",
        "package_requirement",
        "approved_case",
    ]
    assert result["query_count"] == 4 and result["question_count"] == 1


def test_saved_scope_revision_change_returns_stale_on_read_and_repeat_start(task):
    result = begin(task)
    diagnosis = task["db"].get(type(task["diagnosis"]), task["diagnosis"].id)
    diagnosis.input_fingerprint = "c" * 64
    task["db"].commit()
    current = begin(task)
    assert current["id"] == result["id"] and current["status"] == "stale"
    assert current["question"] is None
    read = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert read == current


def test_completed_known_requirements_and_case_withdrawal_preserves_r1_r2(task):
    evidence(task)
    case = add_case(task)
    before = task["diagnosis"].matched_rules.copy()
    result = begin(task)
    assert result["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "match"
    assert result["requirements"]["approved_reference"]["judgement"] == "present"
    submit(task, result, answer_payload(result))
    current = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert current["status"] == "completed_satisfied"
    case = task["db"].get(type(case), case.id)
    case.review_status = "withdrawn"
    task["db"].commit()
    current = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert current["status"] == "stale"
    assert current["requirements"]["approved_reference"]["judgement"] == "unknown"
    assert current["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "match"
    assert current["requirements"]["wiring_observation"]["judgement"] == "matches_table"
    assert task["db"].get(type(task["diagnosis"]), task["diagnosis"].id).matched_rules == before
    register_stop(task["db"], package_source(task["version"]), task["student"], "later stop")
    task["db"].commit()
    # Already-stale tasks still revalidate surviving requirements on every read.
    current = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert current["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "unknown"


def test_answer_uses_remaining_task_execution_budget_and_does_not_consume_question(task):
    result = begin(task)
    record = task["db"].get(QueryTask, result["id"])
    record.elapsed_ms = 120000
    task["db"].commit()
    with pytest.raises(query_tasks.QueryConflict, match="query_execution_timeout"):
        submit(task, result, answer_payload(result))
    assert_unconsumed(task)
    # Viewing an already recorded task does not spend execution quota or ask again.
    viewed = query_tasks.read_query(task["db"], task["identity"], result["id"])
    assert viewed["query_count"] == 4 and viewed["question_count"] == 1


def test_find_query_null_is_authorized_and_has_no_writes_or_queries(task, monkeypatch):
    from sqlalchemy import event

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    def unexpected(*args, **kwargs):
        raise AssertionError("GET must not acquire sources or register a question")

    monkeypatch.setattr(query_tasks, "_acquire_sources", unexpected)
    event.listen(task["db"].bind, "before_cursor_execute", capture)
    try:
        assert query_tasks.find_query(task["db"], task["identity"], task["diagnosis"].id) is None
    finally:
        event.remove(task["db"].bind, "before_cursor_execute", capture)
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE"}
    with task["factory"]() as db:
        for model in (QueryTask, QueryQuestion, QueryAnswerReceipt):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_find_query_revalidates_stale_projection_without_persisting(task, monkeypatch):
    from sqlalchemy import event

    evidence(task)
    result = begin(task)
    register_stop(task["db"], package_source(task["version"]), task["student"], "synthetic stop")
    task["db"].commit()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    def unexpected(*args, **kwargs):
        raise AssertionError("GET must not acquire sources")

    monkeypatch.setattr(query_tasks, "_acquire_sources", unexpected)
    event.listen(task["db"].bind, "before_cursor_execute", capture)
    try:
        current = query_tasks.find_query(task["db"], task["identity"], task["diagnosis"].id)
    finally:
        event.remove(task["db"].bind, "before_cursor_execute", capture)
    assert current["id"] == result["id"] and current["status"] == "stale"
    assert current["question"] is None
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE"}
    with task["factory"]() as db:
        record = db.get(QueryTask, result["id"])
        assert record.status == result["status"]
        assert record.requirements == result["requirements"]
        assert record.query_count == 4 and record.question_count == 1
        assert db.scalar(select(QueryQuestion.status)) == "open"


def test_http_find_query_null_restore_and_revocation_non_disclosure(api_context, task):
    headers = account_headers(api_context, task)
    client = api_context["client"]
    path = f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries"
    assert client.get(path).status_code == 401
    empty = client.get(path, headers=headers)
    assert empty.status_code == 200 and empty.json() is None
    assert empty.headers["cache-control"] == "no-store"
    result = client.post(path, headers=headers).json()
    assert client.get(path, headers=headers).json() == result
    with task["factory"]() as db:
        db.query(Enrollment).update({"status": "withdrawn"})
        db.commit()
    responses = [client.get(path, headers=headers), client.get(
        f"/api/v1/student/diagnoses/{uuid4()}/queries", headers=headers)]
    assert all(response.status_code == 403 for response in responses)
    assert responses[0].json() == responses[1].json()
