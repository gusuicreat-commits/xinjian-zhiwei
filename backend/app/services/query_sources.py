"""DHT11 archived sources. Runtime-only scope; no model, receipts or graph writes.

Transactions and final adoption belong to the caller: revalidate in its protected
transaction immediately before use. Manifests cover all inspected eligible units,
including omitted units; only units are the bounded material projection.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.errors import StaleError
from app.knowledge.applicability import context_from_diagnosis, evaluate_case_applicability
from app.models import (
    Classroom,
    Device,
    DeviceHeartbeat,
    DeviceLog,
    DiagnosisEvidence,
    DiagnosisResult,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentVersion,
    GuidanceHistory,
    KnowledgeCase,
    User,
)
from app.services.auth import AuthorizationDenied
from app.services.data_scope import ScopeConflict, ScopeViolation, diagnosis_session, is_demo_device
from app.services.experiment_packages import load_experiment_package_runtime
from app.services.memory import (
    approved_case,
    case_source,
    current_source,
    diagnosis_sources_available,
    package_source,
)
from app.services.memory import (
    digest as source_digest,
)
from app.services.provenance import derive_test_flag
from app.services.student_authorization import StudentActorContext, authorize_student_actor

SourceStatus = Literal[
    "present", "checked_empty", "conflicting", "not_available", "denied", "error"
]
Revalidation = Literal["ok", "stale", "denied", "error"]
SourceKind = Literal[
    "task_evidence", "firmware_reported_config", "package_requirement", "approved_case"
]
ReasonCode = Literal[
    "not_reported",
    "no_approved_case",
    "no_task_evidence",
    "requirement_missing",
    "package_not_bound",
    "source_stale",
    "source_error",
    "access_denied",
    "reported_conflict",
    "material_omitted",
]
EXPERIMENT = "dht11_temperature_humidity"
ERROR = "SENSOR_READ_FAILED"
R1 = "firmware_gpio_vs_requirement"
R2 = "wiring_observation"
R3 = "approved_reference"
PROJECTION_BYTES = 8192


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def project_units(rows, limit):
    selected = set()
    # The serialized omission count is part of the 8 KiB limit. Revisit a
    # skipped unit when later inclusions shrink that count across a digit edge.
    while True:
        changed = False
        for index in range(len(rows)):
            if index in selected:
                continue
            candidate_indices = selected | {index}
            candidate = {
                "rows": [row for i, row in enumerate(rows) if i in candidate_indices],
                "omitted_count": len(rows) - len(candidate_indices),
            }
            if len(encoded(candidate)) <= limit:
                selected.add(index)
                changed = True
        if not changed:
            break
    return {
        "rows": [row for i, row in enumerate(rows) if i in selected],
        "omitted_count": len(rows) - len(selected),
    }


@dataclass(frozen=True)
class SourceManifest:
    source_kind: SourceKind
    source_id: str
    source_revision: str
    unit_sha256: str
    is_test_data: bool


@dataclass(frozen=True)
class SourceResult:
    status: SourceStatus
    units: tuple[dict[str, Any], ...] = ()
    omitted_count: int = 0
    manifest: tuple[SourceManifest, ...] = ()
    reason_code: ReasonCode | None = None
    is_test_data: bool = True


@dataclass(frozen=True, init=False)
class QueryScope:
    """Built only by build_scope, never deserialize this as caller input."""

    _identity: StudentActorContext = field(repr=False)
    _session_id: str
    _device_id: str
    _diagnosis_id: str
    _session_binding: tuple
    _diagnosis_revision: str
    _package_source: dict | None
    is_test_data: bool


class _Stale(StaleError):
    def __init__(self):
        super().__init__("source_stale")


def _diagnosis_revision(diagnosis):
    return source_digest(
        {
            name: getattr(diagnosis, name)
            for name in (
                "device_id",
                "experiment_id",
                "experiment_record_id",
                "experiment_version_id",
                "input_fingerprint",
                "context_snapshot",
                "matched_rules",
                "is_test_data",
            )
        }
    )


def _session_binding(session):
    return (
        session.student_user_id,
        session.device_id,
        session.experiment_assignment_id,
        session.experiment_version_id,
        session.is_test_data,
    )


def _authorized_rows(db, identity, session_id, device_id, diagnosis_id):
    # Authenticate before any diagnosis/source lookup. All refusal shapes are identical.
    try:
        session = authorize_student_actor(db, identity, device_id, session_id)
    except (ScopeViolation, ScopeConflict) as exc:
        raise AuthorizationDenied(403) from exc
    diagnosis = db.scalar(
        select(DiagnosisResult)
        .where(DiagnosisResult.id == diagnosis_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if diagnosis is None or diagnosis_session(db, diagnosis) != session:
        raise AuthorizationDenied(403)
    student = db.get(User, session.student_user_id, populate_existing=True)
    assignment = db.get(
        ExperimentAssignment, session.experiment_assignment_id, populate_existing=True
    )
    classroom = (
        db.get(Classroom, assignment.class_id, populate_existing=True) if assignment else None
    )
    device = db.get(Device, device_id, populate_existing=True)
    flags = derive_test_flag(
        session.is_test_data,
        student.is_test_data if student else None,
        assignment.is_test_data if assignment else None,
        classroom.is_test_data if classroom else None,
        is_demo_device(device),
        diagnosis.is_test_data,
    )
    if flags and not session.is_test_data:
        raise AuthorizationDenied(403)
    if session.experiment_version_id != diagnosis.experiment_version_id:
        raise _Stale()
    version = (
        db.get(ExperimentVersion, session.experiment_version_id, populate_existing=True)
        if session.experiment_version_id
        else None
    )
    if version and derive_test_flag(version.is_test_data) and not session.is_test_data:
        raise AuthorizationDenied(403)
    if session.experiment_version_id and version is None:
        raise _Stale()
    if version:
        snapshot = diagnosis.context_snapshot
        if (
            version.experiment_id != diagnosis.experiment_record_id
            or snapshot.get("experiment_version_id") != version.id
            or snapshot.get("experiment_version") != version.version
            or snapshot.get("experiment_package_hash") != version.package_hash
        ):
            raise _Stale()
    return session, diagnosis, version


def build_scope(
    db, identity: StudentActorContext, session: ExperimentSession, diagnosis: DiagnosisResult
) -> QueryScope:
    """Use only persisted authorized session/diagnosis; accept no owner/version overrides.

    Missing or foreign diagnoses produce the same AuthorizationDenied. A mismatched
    pinned package is stale, never rebound to a current assignment or device version.
    """
    current, recorded, version = _authorized_rows(
        db, identity, session.id, session.device_id, diagnosis.id
    )
    if recorded.experiment_id != EXPERIMENT or not any(
        row.get("error_type") == ERROR for row in recorded.matched_rules
    ):
        raise ValueError("unsupported_query_scenario")
    result = object.__new__(QueryScope)
    values = dict(
        _identity=identity,
        _session_id=current.id,
        _device_id=current.device_id,
        _diagnosis_id=recorded.id,
        _session_binding=_session_binding(current),
        _diagnosis_revision=_diagnosis_revision(recorded),
        _package_source=package_source(version) if version else None,
        is_test_data=derive_test_flag(current.is_test_data),
    )
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result


def _resolve(db, scope):
    if not isinstance(scope, QueryScope) or not hasattr(scope, "_identity"):
        raise AuthorizationDenied(403)
    session, diagnosis, version = _authorized_rows(
        db,
        scope._identity,
        scope._session_id,
        scope._device_id,
        scope._diagnosis_id,
    )
    if (
        _session_binding(session) != scope._session_binding
        or _diagnosis_revision(diagnosis) != scope._diagnosis_revision
    ):
        raise _Stale()
    if (package_source(version) if version else None) != scope._package_source:
        raise _Stale()
    return diagnosis, version


def _evidence_rows(db, diagnosis):
    return list(
        db.scalars(
            select(DiagnosisEvidence)
            .where(
                DiagnosisEvidence.diagnosis_id == diagnosis.id,
            )
            .order_by(DiagnosisEvidence.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )


def _flag(scope, diagnosis, version, *extra):
    result = derive_test_flag(
        scope.is_test_data,
        diagnosis.is_test_data,
        version.is_test_data if version else None,
        *extra,
    )
    if result and not scope.is_test_data:
        raise AuthorizationDenied(403)
    return result


def _result(kind, entries, flag, *, empty_reason, conflicting=False):
    units = [unit for _, _, unit in entries]
    projection = project_units(units, PROJECTION_BYTES)
    manifest = tuple(
        SourceManifest(kind, source_id, revision, digest(unit), unit["is_test_data"])
        for source_id, revision, unit in entries
    )
    return SourceResult(
        "conflicting" if conflicting else ("present" if entries else "checked_empty"),
        tuple(deepcopy(projection["rows"])),
        projection["omitted_count"],
        manifest,
        "reported_conflict" if conflicting else (empty_reason if not entries else None),
        flag,
    )


def _evidence_unit(row, flag):
    return {
        "evidence_id": row.id,
        "evidence_type": row.evidence_type,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "normalized_value": row.normalized_value,
        "raw_payload": row.raw_payload,
        "occurred_at": row.occurred_at.isoformat(),
        "is_test_data": flag,
    }


def _config_metadata(db, scope, diagnosis, version, source_ref):
    """Exact scoped log/batch only; live payloads never supply GPIO or event identity."""
    log = db.scalar(
        select(DeviceLog)
        .where(
            DeviceLog.id == source_ref,
            DeviceLog.device_id == scope._device_id,
            DeviceLog.experiment_session_id == scope._session_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if log is None:
        return None, None, [], ()
    log_flag = _flag(scope, diagnosis, version, log.is_test_data)
    heartbeats = (
        list(
            db.scalars(
                select(DeviceHeartbeat)
                .where(
                    DeviceHeartbeat.ingestion_request_id == log.ingestion_request_id,
                    DeviceHeartbeat.device_id == scope._device_id,
                    DeviceHeartbeat.experiment_session_id == scope._session_id,
                )
                .order_by(DeviceHeartbeat.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        if log.ingestion_request_id
        else []
    )
    flags = [log_flag]
    for heartbeat in heartbeats:
        flags.append(_flag(scope, diagnosis, version, heartbeat.is_test_data))
    # Multiple heartbeats are legal in a batch; disagreement cannot identify one
    # firmware version. Missing metadata is null, never current device state.
    firmware_versions = {heartbeat.firmware_version for heartbeat in heartbeats}
    firmware_version = next(iter(firmware_versions)) if len(firmware_versions) == 1 else None
    revision = {
        "log_id": log.id,
        "boot_id": log.boot_id,
        "ingestion_request_id": log.ingestion_request_id,
        "is_test_data": log.is_test_data,
        "heartbeats": [
            {
                "id": heartbeat.id,
                "firmware_version": heartbeat.firmware_version,
                "is_test_data": heartbeat.is_test_data,
            }
            for heartbeat in heartbeats
        ],
    }
    return log.boot_id, firmware_version, revision, tuple(flags)


def _query_evidence(db, scope, diagnosis, version, *, config=False):
    flag = _flag(scope, diagnosis, version)
    mapped_type = None
    if config:
        runtime = _runtime(db, scope, version)
        if runtime is None:
            return SourceResult("not_available", reason_code="package_not_bound", is_test_data=flag)
        mapped_type = next(
            (
                item.evidence_type
                for item in runtime.bundle.hardware.evidence_mapping
                if item.source.type == "device_error_code"
                and item.source.value == "DHT11_READ_FAILED"
            ),
            None,
        )
    entries = []
    for row in _evidence_rows(db, diagnosis):
        if (
            row.experiment_version_id != diagnosis.experiment_version_id
            or row.experiment_record_id != diagnosis.experiment_record_id
        ):
            raise _Stale()
        payload = row.raw_payload
        # Absent per-event provenance inherits the verified frozen diagnosis; an
        # explicit unknown/true per-event flag conservatively upgrades the result.
        row_flag = _flag(
            scope, diagnosis, version, payload.get("is_test_data", diagnosis.is_test_data)
        )
        full = _evidence_unit(row, row_flag)
        revision = digest(full)
        if config:
            if (
                row.source_type != "device_log"
                or payload.get("event_code") != "DHT11_READ_FAILED"
                or mapped_type is None
                or row.evidence_type != mapped_type
            ):
                continue
            snapshot = payload.get("sensor_snapshot")
            gpio = snapshot.get("gpio") if isinstance(snapshot, dict) else None
            if type(gpio) is not int:
                continue
            boot_id, firmware_version, metadata_revision, metadata_flags = _config_metadata(
                db, scope, diagnosis, version, row.source_ref
            )
            row_flag = _flag(scope, diagnosis, version, row_flag, *metadata_flags)
            revision = digest({"frozen_evidence": full, "metadata": metadata_revision})
            unit = {
                "evidence_id": row.id,
                "source_ref": row.source_ref,
                "gpio": gpio,
                "firmware_version": firmware_version,
                "boot_id": boot_id,
                "is_test_data": row_flag,
            }
        else:
            unit = full
        entries.append((row.id, revision, unit))
    return _result(
        "firmware_reported_config" if config else "task_evidence",
        entries,
        flag,
        empty_reason="not_reported" if config else "no_task_evidence",
        conflicting=config and len({unit["gpio"] for _, _, unit in entries}) > 1,
    )


def _runtime(db, scope, version):
    if version is None:
        return None
    if not current_source(db, package_source(version), is_test_data=scope.is_test_data):
        raise _Stale()
    return load_experiment_package_runtime(db, version.id)


def _query_requirement(db, scope, diagnosis, version):
    flag = _flag(scope, diagnosis, version)
    runtime = _runtime(db, scope, version)
    if runtime is None:
        return SourceResult("not_available", reason_code="package_not_bound", is_test_data=flag)
    entries = []
    for interface in runtime.bundle.hardware.interfaces:
        if interface.id != "dht11_gpio" or "dht11" not in interface.component_ids:
            continue
        gpio = interface.pins.get("data")
        if type(gpio) is not int:
            continue
        unit = {
            "interface_id": interface.id,
            "pins": interface.pins,
            "gpio": gpio,
            "package_version_id": version.id,
            "package_version": version.version,
            "is_test_data": flag,
            "physical_verification": "not_asserted",
        }
        entries.append(
            (f"{version.id}:{interface.id}", source_digest(package_source(version)), unit)
        )
    return _result("package_requirement", entries, flag, empty_reason="requirement_missing")


def _query_cases(db, scope, diagnosis, version):
    flag = _flag(scope, diagnosis, version)
    runtime = _runtime(db, scope, version)
    guidance = list(
        db.scalars(
            select(GuidanceHistory)
            .where(
                GuidanceHistory.diagnosis_result_id == diagnosis.id,
            )
            .execution_options(populate_existing=True)
        )
    )
    context = context_from_diagnosis(diagnosis, guidance)
    rows = list(
        db.scalars(
            select(KnowledgeCase)
            .where(
                KnowledgeCase.experiment_type == EXPERIMENT,
                KnowledgeCase.error_type == ERROR,
            )
            .order_by(KnowledgeCase.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    candidates = [(row, case_source(row), "case") for row in rows]
    if runtime:
        for row in sorted(runtime.bundle.cases.cases, key=lambda item: item.id):
            candidates.append(
                (
                    row,
                    {
                        "kind": "package_case",
                        "id": row.id,
                        "version": row.version,
                        "hash": version.package_hash,
                        "package_id": version.id,
                    },
                    "package_case",
                )
            )
    entries = []
    for case, source, kind in candidates:
        if (
            case.experiment_type != EXPERIMENT
            or case.error_type != ERROR
            or not approved_case(case, is_test_data=scope.is_test_data)
            or not current_source(db, source, is_test_data=scope.is_test_data)
        ):
            continue
        applicability = evaluate_case_applicability(case.solution_record, context)
        if applicability.projection is None:
            continue
        case_flag = _flag(scope, diagnosis, version, case.is_test_data)
        unit = {
            "case_id": case.id,
            "version": case.version,
            "origin": kind,
            "symptom": case.symptom,
            "normal_state": case.normal_state,
            "evidence": case.evidence,
            "possible_causes": case.possible_causes,
            "solution_steps": case.solution_steps,
            "source_ref": case.source_ref,
            "applicability": applicability.projection.model_dump(mode="json"),
            "root_cause_for_this_task": "unconfirmed",
            "is_test_data": case_flag,
        }
        # Prefix the owning package only for package cases to avoid global ID collisions.
        source_id = (
            f"{version.id}:{case.id}:{case.version}"
            if kind == "package_case"
            else f"{case.id}:{case.version}"
        )
        entries.append((source_id, source_digest(source), unit))
    return _result("approved_case", entries, flag, empty_reason="no_approved_case")


@dataclass(frozen=True)
class ArchivedSource:
    kind: SourceKind
    requirement: str

    def query(self, db, scope: QueryScope, requirement: str | None = None) -> SourceResult:
        if requirement is not None and requirement != self.requirement:
            raise ValueError("unsupported_source_requirement")
        try:
            diagnosis, version = _resolve(db, scope)
            if self.kind in {"task_evidence", "firmware_reported_config"}:
                return _query_evidence(
                    db, scope, diagnosis, version, config=self.kind == "firmware_reported_config"
                )
            if self.kind == "package_requirement":
                return _query_requirement(db, scope, diagnosis, version)
            return _query_cases(db, scope, diagnosis, version)
        except (AuthorizationDenied, ScopeViolation, ScopeConflict):
            return SourceResult("denied", reason_code="access_denied")
        except _Stale:
            return SourceResult("not_available", reason_code="source_stale")
        except DBAPIError:
            # Preserve SQLSTATE: after a timeout PostgreSQL aborts the transaction.
            # The command boundary must roll it back before any further SQL.
            raise
        except Exception:
            # Neither database details nor inaccessible object identities leave the service.
            return SourceResult("error", reason_code="source_error")

    def revalidate(
        self, db, scope: QueryScope, manifest: tuple[SourceManifest, ...]
    ) -> Revalidation:
        result = self.query(db, scope)
        if result.status == "denied":
            return "denied"
        if result.status == "error":
            return "error"
        if result.status == "not_available":
            return "stale"
        return "ok" if result.manifest == tuple(manifest) else "stale"


SOURCES = {
    "task_evidence": ArchivedSource("task_evidence", R1),
    "firmware_reported_config": ArchivedSource("firmware_reported_config", R1),
    "package_requirement": ArchivedSource("package_requirement", R1),
    "approved_case": ArchivedSource("approved_case", R3),
}


@dataclass(frozen=True)
class GPIOComparison:
    status: Literal["match", "mismatch", "unknown"]
    reason_code: ReasonCode | None = None
    checked: bool = True
    root_cause_status: Literal["unconfirmed"] = "unconfirmed"
    physical_verification: Literal["not_asserted"] = "not_asserted"


def compare_gpio(reported: SourceResult, requirement: SourceResult) -> GPIOComparison:
    """Only projected integers can support the comparison; conflict precedes projection."""
    for result in (reported, requirement):
        if result.status in {"denied", "error"} or result.reason_code == "source_stale":
            return GPIOComparison("unknown", result.reason_code, checked=False)
    if reported.status == "conflicting":
        return GPIOComparison("unknown", "reported_conflict")
    if reported.status != "present":
        return GPIOComparison("unknown", reported.reason_code or "not_reported")
    if requirement.status != "present":
        return GPIOComparison("unknown", requirement.reason_code or "requirement_missing")
    if reported.omitted_count or requirement.omitted_count:
        return GPIOComparison("unknown", "material_omitted")
    actual = {u.get("gpio") for u in reported.units if type(u.get("gpio")) is int}
    expected = {u.get("gpio") for u in requirement.units if type(u.get("gpio")) is int}
    if len(actual) != 1 or len(expected) != 1:
        return GPIOComparison("unknown", "not_reported" if not actual else "requirement_missing")
    return GPIOComparison("match" if actual == expected else "mismatch")


def approved_reference(result: SourceResult) -> Literal["present", "checked_empty"]:
    if result.status == "checked_empty":
        return "checked_empty"
    if result.status == "present" and result.units:
        return "present"
    raise ValueError("reference_not_adoptable")


def revalidate_r1(db, scope, reported_manifest, requirement_manifest) -> Revalidation:
    checks = [
        SOURCES["firmware_reported_config"].revalidate(db, scope, reported_manifest),
        SOURCES["package_requirement"].revalidate(db, scope, requirement_manifest),
    ]
    if "denied" in checks:
        return "denied"
    if "error" in checks:
        return "error"
    return "stale" if "stale" in checks else "ok"


def revalidate_delivery(
    db, scope, manifests: dict[str, tuple[SourceManifest, ...]]
) -> Revalidation:
    """Future product adoption/old-result reads must call inside the final transaction."""
    try:
        diagnosis, _ = _resolve(db, scope)
        checks = [
            SOURCES[kind].revalidate(db, scope, manifest) for kind, manifest in manifests.items()
        ]
        if "denied" in checks:
            return "denied"
        if "error" in checks:
            return "error"
        if "stale" in checks or not diagnosis_sources_available(db, diagnosis):
            return "stale"
        return "ok"
    except (AuthorizationDenied, ScopeViolation, ScopeConflict):
        return "denied"
    except _Stale:
        return "stale"
    except DBAPIError:
        raise
    except Exception:
        return "error"


@dataclass(frozen=True)
class QuestionDefinition:
    id: str
    version: str
    requirement: Literal["wiring_observation"] = R2
    experiment: str = EXPERIMENT
    error_type: str = ERROR
    options: tuple[str, ...] = ("matches_table", "differs", "unclear")
    synthetic: Literal[True] = True


# Structural synthetic catalog only; teaching wording awaits teacher approval.
QUESTIONS = (QuestionDefinition("synthetic.dht11.wiring_observation", "synthetic-1"),)


def eligible_question(
    scope: QueryScope, r1: GPIOComparison | None, asked_requirements: frozenset[str]
) -> QuestionDefinition | None:
    if not scope.is_test_data or r1 is None or not r1.checked or R2 in asked_requirements:
        return None
    return QUESTIONS[0]


@dataclass(frozen=True)
class ObservationAnswer:
    value: Literal["matches_table", "differs", "unclear"]
    satisfied: bool
    gap: Literal["observation_unknown"] | None
    requirement: Literal["wiring_observation"] = R2
    closed: Literal[True] = True
    root_cause_status: Literal["unconfirmed"] = "unconfirmed"


def validate_answer(question_id: str, version: str, answer: Any) -> ObservationAnswer:
    question = next((q for q in QUESTIONS if q.id == question_id and q.version == version), None)
    if question is None or not isinstance(answer, str) or answer not in question.options:
        raise ValueError("invalid_observation_answer")
    return ObservationAnswer(
        answer, answer != "unclear", "observation_unknown" if answer == "unclear" else None
    )
