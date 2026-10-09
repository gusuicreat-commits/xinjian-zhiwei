"""Deterministic archived queries and business-transaction answer receipts.

The existing student guard locks user/grants, device, session and membership.
All operations acquire that guard before task rows and commit once. No I/O,
model, checkpoint, diagnosis graph mutation or raw material delivery occurs here.
"""

from copy import deepcopy
from dataclasses import asdict
from functools import wraps
from time import monotonic

from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.errors import ConflictError, TemporarilyUnavailable
from app.models import DiagnosisResult, QueryAnswerReceipt, QueryQuestion, QueryTask
from app.models.base import utc_now
from app.services.auth import AuthorizationDenied
from app.services.data_scope import ScopeConflict, ScopeViolation, diagnosis_session
from app.services.memory import digest
from app.services.provenance import derive_test_flag
from app.services.query_sources import (
    QUESTIONS,
    R1,
    R2,
    R3,
    SOURCES,
    SourceManifest,
    approved_reference,
    build_scope,
    compare_gpio,
    eligible_question,
    revalidate_delivery,
    revalidate_r1,
    validate_answer,
)
from app.services.student_authorization import authorize_student_actor

CONTRACT_VERSION = "dht11-query-v1"
ACTIVE_SECONDS = 120
SOURCE_ORDER = ("task_evidence", "firmware_reported_config", "package_requirement", "approved_case")


class QueryConflict(ConflictError):
    pass


class QueryUnavailable(TemporarilyUnavailable):
    error_code = "query_temporarily_unavailable"

    def __init__(self):
        super().__init__("query_temporarily_unavailable")


def _bounded_command(operation):
    """Bound every SQL statement/lock wait by the command's remaining budget.

    SET LOCAL is limited to this transaction. A connection hook updates the
    remaining timeout before each statement, including source revalidation.
    No waiting for a human answer retains a connection or deadline.
    """

    @wraps(operation)
    def run(db, *args, **kwargs):
        db.rollback()
        started = monotonic()
        budget = {"started": started, "deadline": started + ACTIVE_SECONDS}
        db.info["query_command_budget"] = budget
        connection = None

        def before_statement(conn, cursor, statement, parameters, context, executemany):
            remaining_ms = int((budget["deadline"] - monotonic()) * 1000)
            if remaining_ms <= 0:
                raise QueryUnavailable()
            if conn.dialect.name == "postgresql":
                cursor.execute(f"SET LOCAL statement_timeout = '{remaining_ms}ms'")
                cursor.execute(f"SET LOCAL lock_timeout = '{remaining_ms}ms'")

        try:
            connection = db.connection()
            event.listen(connection, "before_cursor_execute", before_statement)
            return operation(db, *args, **kwargs)
        except DBAPIError as exc:
            db.rollback()
            state = getattr(exc.orig, "sqlstate", None) or ""
            if (
                state in {"57014", "55P03", "40P01", "40001"}
                or state.startswith("08")
                or exc.connection_invalidated
                or (not state and isinstance(exc, OperationalError))
            ):
                raise QueryUnavailable() from exc
            raise
        except QueryUnavailable:
            db.rollback()
            raise
        finally:
            if connection is not None and event.contains(
                connection, "before_cursor_execute", before_statement
            ):
                event.remove(connection, "before_cursor_execute", before_statement)
            db.info.pop("query_command_budget", None)

    return run


def _remaining_task_budget(db, task):
    budget = db.info["query_command_budget"]
    remaining = ACTIVE_SECONDS - task.elapsed_ms / 1000
    budget["deadline"] = min(budget["deadline"], budget["started"] + remaining)
    if monotonic() >= budget["deadline"]:
        # A persisted, exhausted task quota is a command conflict, not a
        # recoverable source/SQL fault. Retrying cannot replenish this quota.
        raise QueryConflict("query_execution_timeout")


def _authorize(db, identity, *, require_active=True, permission="dashboard.read"):
    try:
        return authorize_student_actor(
            db,
            identity,
            identity.device_id,
            identity.session_id,
            require_active=require_active,
            permission=permission,
        )
    except (ScopeViolation, ScopeConflict) as exc:
        raise AuthorizationDenied(403) from exc


def _snapshot(scope):
    return {
        "session_binding": list(scope._session_binding),
        "diagnosis_revision": scope._diagnosis_revision,
        "package_source": scope._package_source,
    }


def _scope(db, identity, session, diagnosis_id):
    diagnosis = db.get(DiagnosisResult, diagnosis_id, populate_existing=True)
    if diagnosis is None:
        raise AuthorizationDenied(403)
    return build_scope(db, identity, session, diagnosis)


def _task(db, identity, task_id):
    # Never lookup objects before authentication/scope authorization.
    session = _authorize(db, identity, require_active=False)
    task = db.scalar(
        select(QueryTask)
        .where(
            QueryTask.id == task_id,
            QueryTask.session_id == session.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise AuthorizationDenied(403)
    return session, task


def _manifests(task):
    return {
        kind: tuple(SourceManifest(**entry) for entry in entries)
        for kind, entries in task.source_manifest.items()
    }


def _stale(task, reason="source_stale", affected=(R1, R2, R3)):
    task.status = "stale"
    task.terminal_reason = reason
    task.completed_at = task.completed_at or utc_now()
    # Invalidate only dependent requirements; independent validated facts survive.
    requirements = deepcopy(task.requirements)
    for requirement in affected:
        requirements[requirement] = {"status": "stale", "judgement": "unknown", "gap": reason}
    if requirements[R2]["status"] == "waiting_answer":
        requirements[R2] = {
            "status": "unknown",
            "judgement": "unknown",
            "gap": "observation_unknown",
        }
    task.requirements = requirements


def _question(db, task):
    return db.scalar(select(QueryQuestion).where(QueryQuestion.task_id == task.id))


def _project(db, task):
    question = _question(db, task) if task.status == "waiting_answer" else None
    definition = next(
        (
            q
            for q in QUESTIONS
            if question
            and (q.id, q.version, q.requirement)
            == (question.question_id, question.version, question.requirement)
        ),
        None,
    )
    return {
        "id": task.id,
        "contract_version": task.contract_version,
        "status": task.status,
        "terminal_reason": task.terminal_reason,
        "requirements": deepcopy(task.requirements),
        "question": (
            {
                "question_id": definition.id,
                "version": definition.version,
                "requirement": definition.requirement,
                "options": list(definition.options),
                "synthetic": definition.synthetic,
            }
            if definition and question.status == "open"
            else None
        ),
        "query_count": task.query_count,
        "question_count": task.question_count,
        "is_test_data": task.is_test_data,
        "root_cause_status": "unconfirmed",
        "physical_verification": "not_asserted",
    }


def _deliver(db, identity, session, task):
    _authorize(db, identity)
    try:
        scope = _scope(db, identity, session, task.diagnosis_id)
    except ValueError as exc:
        if str(exc) not in {"source_stale", "unsupported_query_scenario"}:
            raise
        _stale(task)
        return _project(db, task)
    if task.contract_version != CONTRACT_VERSION or _snapshot(scope) != task.scope_snapshot:
        _stale(task)
        return _project(db, task)
    manifests = _manifests(task)
    checks = [
        revalidate_delivery(db, scope, manifests),
        revalidate_r1(
            db,
            scope,
            manifests.get("firmware_reported_config", ()),
            manifests.get("package_requirement", ()),
        ),
    ]
    if "denied" in checks:
        raise AuthorizationDenied(403)
    # A source may fail after its initial authorization. Refusal still wins;
    # no stale mutation or public projection occurs until faults are ruled out.
    _authorize(db, identity)
    if "error" in checks:
        raise QueryUnavailable()
    if "stale" in checks:
        invalid = []
        for kind, manifest in manifests.items():
            current = SOURCES[kind].revalidate(db, scope, manifest)
            if current == "denied":
                raise AuthorizationDenied(403)
            if current == "error":
                _authorize(db, identity)
                raise QueryUnavailable()
            if current == "stale":
                invalid.append(kind)
        # A stale diagnosis dependency outside this query manifest has no safe
        # narrower mapping. Otherwise invalidate precisely R1 or R3.
        _stale(task, affected=_affected(invalid) if invalid else (R1, R2, R3))
    question = _question(db, task)
    if question and (
        question.experiment_version_id != task.experiment_version_id
        or not any(
            (q.id, q.version, q.requirement)
            == (question.question_id, question.version, question.requirement)
            for q in QUESTIONS
        )
    ):
        _stale(task, "question_version_stale")
    _authorize(db, identity)
    return _project(db, task)


def _affected(kinds):
    affected = set()
    for kind in kinds:
        affected.add(R3 if kind == "approved_case" else R1)
    return tuple(affected)


def _acquire_sources(db, scope, started):
    results = {}
    invalid = []
    # The contract fixes S1 -> S2 -> S3 -> S4, independent of catalog expansion.
    for kind in SOURCE_ORDER:
        source = SOURCES[kind]
        if monotonic() - started >= ACTIVE_SECONDS:
            raise QueryUnavailable()
        result = source.query(db, scope, source.requirement)
        if result.status == "denied":
            raise AuthorizationDenied(403)
        checked = source.revalidate(db, scope, result.manifest)
        if checked == "denied":
            raise AuthorizationDenied(403)
        _authorize(db, scope._identity)
        if result.status == "error" or checked == "error":
            raise QueryUnavailable()
        if checked == "stale":
            invalid.append(kind)
        results[kind] = result
        if monotonic() - started >= ACTIVE_SECONDS:
            raise QueryUnavailable()
    return results, invalid


@_bounded_command
def start_query(db, identity, diagnosis_id):
    # The decorator has released dependency reads before this protected transaction.
    started = monotonic()
    try:
        session = _authorize(db, identity)
        task = db.scalar(
            select(QueryTask)
            .where(
                QueryTask.session_id == session.id,
                QueryTask.diagnosis_id == diagnosis_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is not None:
            result = _deliver(db, identity, session, task)
            db.commit()
            return result
        scope = _scope(db, identity, session, diagnosis_id)
        sources, invalid = _acquire_sources(db, scope, started)
        r1 = compare_gpio(sources["firmware_reported_config"], sources["package_requirement"])
        try:
            r3 = approved_reference(sources["approved_case"])
            r3_result = {
                "status": "satisfied" if r3 == "present" else "checked_empty",
                "judgement": r3,
                "gap": sources["approved_case"].reason_code,
            }
        except ValueError:
            r3_result = {
                "status": "unknown",
                "judgement": "unknown",
                "gap": sources["approved_case"].reason_code or "material_omitted",
            }
        question = eligible_question(scope, r1, frozenset()) if not invalid else None
        _authorize(db, identity)
        task = QueryTask(
            session_id=session.id,
            diagnosis_id=diagnosis_id,
            experiment_version_id=session.experiment_version_id,
            contract_version=CONTRACT_VERSION,
            scope_snapshot=_snapshot(scope),
            status="waiting_answer" if question else "finish_unknown",
            terminal_reason=None if question else "observation_unknown",
            requirements={
                R1: {
                    "status": "satisfied" if r1.status != "unknown" else "unknown",
                    "judgement": r1.status,
                    "gap": r1.reason_code,
                },
                R2: {
                    "status": "waiting_answer" if question else "unknown",
                    "judgement": "unknown",
                    "gap": "observation_unknown"
                    if question
                    else (
                        "question_not_approved" if not scope.is_test_data else "observation_unknown"
                    ),
                },
                R3: r3_result,
            },
            source_manifest={
                kind: [asdict(m) for m in result.manifest] for kind, result in sources.items()
            },
            query_count=len(sources),
            question_count=int(question is not None),
            elapsed_ms=int((monotonic() - started) * 1000),
            is_test_data=derive_test_flag(
                scope.is_test_data, *(r.is_test_data for r in sources.values())
            ),
            completed_at=None if question else utc_now(),
        )
        if invalid:
            _stale(task, affected=_affected(invalid))
        db.add(task)
        db.flush()
        if question:
            _authorize(db, identity)
            db.add(
                QueryQuestion(
                    task_id=task.id,
                    requirement=question.requirement,
                    question_id=question.id,
                    version=question.version,
                    experiment_version_id=task.experiment_version_id,
                    status="open",
                )
            )
        db.flush()
        result = _deliver(db, identity, session, task)
        task.elapsed_ms = int((monotonic() - started) * 1000)
        if monotonic() - started >= ACTIVE_SECONDS:
            raise QueryUnavailable()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@_bounded_command
def find_query(db, identity, diagnosis_id):
    """Read an existing authorized task without persisting delivery invalidation."""
    try:
        session = _authorize(db, identity)
        diagnosis = db.get(DiagnosisResult, diagnosis_id, populate_existing=True)
        if diagnosis is None or diagnosis_session(db, diagnosis) != session:
            raise AuthorizationDenied(403)
        task = db.scalar(
            select(QueryTask)
            .where(QueryTask.session_id == session.id, QueryTask.diagnosis_id == diagnosis_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # _deliver may mark ORM rows stale. Suppress autoflush and roll back even
        # on success: this GET must not update tasks/questions or spend quota.
        with db.no_autoflush:
            result = _deliver(db, identity, session, task) if task is not None else None
            _authorize(db, identity)
        return result
    finally:
        db.rollback()


@_bounded_command
def read_query(db, identity, task_id):
    try:
        session, task = _task(db, identity, task_id)
        result = _deliver(db, identity, session, task)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _receipt(record):
    return {
        "id": record.id,
        "request_id": record.request_id,
        "value": record.value,
        "created_at": record.created_at,
        "is_test_data": record.is_test_data,
    }


@_bounded_command
def submit_answer(db, identity, task_id, *, request_id, question_id, question_version, value):
    try:
        # Allow ended sessions only as far as the original successful receipt lookup.
        session = _authorize(db, identity, require_active=False, permission="feedback.create")
        _, task = _task(db, identity, task_id)
        requested_hash = digest(
            {
                "task_id": task.id,
                "question_id": question_id,
                "question_version": question_version,
                "value": value,
            }
        )
        record = db.scalar(
            select(QueryAnswerReceipt).where(
                QueryAnswerReceipt.task_id == task.id,
                QueryAnswerReceipt.request_id == str(request_id),
            )
        )
        if record is not None:
            if requested_hash != record.payload_hash:
                raise QueryConflict("request_id_payload_conflict")
            _authorize(db, identity, require_active=False, permission="feedback.create")
            result = _receipt(record)
            db.commit()
            return result
        _authorize(db, identity, permission="feedback.create")
        _remaining_task_budget(db, task)
        _deliver(db, identity, session, task)
        if task.status != "waiting_answer":
            raise QueryConflict("query_not_waiting_answer")
        question = _question(db, task)
        if (
            question is None
            or question.status != "open"
            or (question.question_id, question.version, question.experiment_version_id)
            != (question_id, question_version, session.experiment_version_id)
        ):
            raise QueryConflict("question_version_conflict")
        parsed = validate_answer(question_id, question_version, value)
        _authorize(db, identity, permission="feedback.create")
        record = QueryAnswerReceipt(
            task_id=task.id,
            question_record_id=question.id,
            request_id=str(request_id),
            payload_hash=requested_hash,
            value=parsed.value,
            submitted_by_user_id=session.student_user_id,
            is_test_data=task.is_test_data,
        )
        db.add(record)
        question.status = "closed"
        question.closed_at = utc_now()
        requirements = deepcopy(task.requirements)
        requirements[R2] = {
            "status": "satisfied" if parsed.satisfied else "unknown",
            "judgement": parsed.value,
            "gap": parsed.gap,
        }
        task.requirements = requirements
        satisfied = all(r["status"] == "satisfied" for r in requirements.values())
        task.status = "completed_satisfied" if satisfied else "finish_unknown"
        task.terminal_reason = None if satisfied else "requirements_unknown"
        task.completed_at = utc_now()
        db.flush()
        # A same-transaction hook or a wait cannot bypass final adoption authorization.
        _authorize(db, identity, permission="feedback.create")
        delivered = _deliver(db, identity, session, task)
        if delivered["status"] == "stale":
            raise QueryConflict("query_sources_stale")
        task.elapsed_ms += int((monotonic() - db.info["query_command_budget"]["started"]) * 1000)
        result = _receipt(record)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
