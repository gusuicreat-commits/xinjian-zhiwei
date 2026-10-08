"""Serial, resumable synthetic evaluation using the existing graph and usage ledger.

A batch owns one SQLite database. It never opens DATABASE_URL. An interrupted pair
is retained for inspection and cannot be reissued under a new identity on resume.
PostgreSQL/process durability of the query runtime is tested separately.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import time
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.ai.clients import build_ai_client
from app.ai.diagnosis_graph import (
    DiagnosisGraphContext,
    _approved_result,
    ai_explanation,
    ai_reasoning_node,
    build_diagnosis_graph,
    knowledge_validation,
)
from app.ai.evidence_projection import evidence_reports
from app.ai.governance import AIQuotaDenied, GovernedAIInvocation, TaskAttemptLimits
from app.core.config import get_settings
from app.evaluation.query_contract import digest
from app.evaluation.query_graph import GovernedSelector
from app.evaluation.query_runner import (
    FIXTURES,
    clone_material,
    collect,
    records,
    scenario_contract,
)
from app.evaluation.query_storage import QueryStore
from app.evaluation.workflow_environment import workflow_environment
from app.models import Device, DiagnosisEvidence
from app.models.ai_call_record import AICallRecord
from app.models.ai_usage_reservation import AIUsageReservation
from app.services.student_authorization import StudentActorContext, authorize_student_actor

VERSION = "query-real-v1"
COMMON_QUESTION = "请解释已有证据能说明什么、仍不能确认什么，以及允许的下一步。"


class EvaluationBlocked(RuntimeError):
    pass


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temp.replace(path)


@contextmanager
def batch_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "batch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvaluationBlocked("another process owns this evaluation batch") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def usage(db):
    rows = list(db.scalars(select(AIUsageReservation).order_by(AIUsageReservation.created_at)))
    return {
        "physical_attempts": len(rows),
        "accounted_cny": round(sum(r.accounted_cost or 0 for r in rows), 8),
        "usage_estimate_cny": round(
            sum(
                r.accounted_cost or 0
                for r in rows
                if r.status == "succeeded"
                and r.input_tokens is not None
                and r.output_tokens is not None
            ),
            8,
        ),
        "unsettled_reserved_cny": round(
            sum(
                r.accounted_cost or 0
                for r in rows
                if r.status != "succeeded" or r.input_tokens is None or r.output_tokens is None
            ),
            8,
        ),
        "invoice_verified": False,
        "unknown_cost_rows": sum(r.accounted_cost is None for r in rows),
        "reservations": [
            {
                "id": r.id,
                "diagnosis_id": r.diagnosis_result_id,
                "operation_id": r.operation_id,
                "stage": r.call_stage,
                "status": r.status,
                "reserved_cny": r.reserved_cost,
                "accounted_cny": r.accounted_cost,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "error_code": r.error_code,
            }
            for r in rows
        ],
    }


def checked_profile(settings, budget):
    cap = budget.get("cap_cny")
    if (
        budget.get("authorization") != "explicit_new_batch_cap"
        or isinstance(cap, bool)
        or not isinstance(cap, (int, float))
        or not math.isfinite(cap)
        or cap <= 0
    ):
        raise EvaluationBlocked("explicit finite authorized batch cap required")
    if not budget.get("authorized_by_user") or not budget.get("authorization_text"):
        raise EvaluationBlocked("user authorization record required")
    if not budget.get("price_verified_at") or not budget.get("price_source"):
        raise EvaluationBlocked("current official price verification required")
    if (
        settings.ai_provider != "kimi"
        or settings.ai_model != "kimi-k2.6"
        or settings.ai_base_url != "https://api.moonshot.cn/v1"
    ):
        raise EvaluationBlocked("configured kimi-k2.6 official endpoint required")
    if not settings.ai_api_key:
        raise EvaluationBlocked("configured API credential required")
    for field in ("ai_input_cost_per_1k_tokens", "ai_output_cost_per_1k_tokens"):
        if not budget.get(field) or budget[field] != getattr(settings, field):
            raise EvaluationBlocked("verified price and configured price differ")
    # Override only the isolated process, never .env or the business AI switch.
    return settings.model_copy(
        update={
            "ai_enabled": True,
            "ai_max_retries": 0,
            "ai_input_token_limit": min(10000, settings.ai_input_token_limit),
            "ai_price_version": budget["price_version"],
        }
    )


def seed_fixed(env, settings):
    """Actual HTTP ingestion and existing fixed graph; freeze before the AI tail."""
    env.app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"ai_enabled": False}
    )
    now = datetime.now(timezone.utc).isoformat()
    telemetry = [{"type": "heartbeat", "payload": {"metadata": {}}}]
    if env.package == "dht11_temperature_humidity":
        telemetry += [
            {
                "type": "log",
                "payload": {
                    "level": "error",
                    "event_code": "DHT11_READ_FAILED",
                    "message": "合成读取失败",
                    "sensor_snapshot": {"component_id": "dht11"},
                },
            }
            for _ in range(6)
        ]
    else:
        telemetry += [
            {
                "type": "reading",
                "payload": {
                    "sensor_type": "status_led",
                    "metric_key": "gpio_command_level",
                    "value": 1,
                    "metadata": {
                        "measurement_source": "command",
                        "command_id": "synthetic-command",
                    },
                },
            }
        ]
    result = env.request(
        "POST",
        "/api/v1/device/ingest",
        json={
            "protocolVersion": "1.0",
            "schemaVersion": "1",
            "requestId": str(uuid4()),
            "bootId": "synthetic-query-real",
            "sequenceNo": 1,
            "sentAt": now,
            "isTestData": True,
            "records": [{**r, "occurredAt": now} for r in telemetry],
        },
    )
    if result.status_code != 201:
        raise EvaluationBlocked(f"synthetic ingestion failed: {result.status_code}")
    result = env.request(
        "POST",
        f"/api/v1/diagnosis-workflows/devices/{env.device_key}",
        json={"lookback_seconds": 3600, "question": COMMON_QUESTION},
    )
    if result.status_code != 201:
        raise EvaluationBlocked(f"fixed workflow failed: {result.status_code}")
    workflow_id = result.json()["id"]
    graph = env.app.state.diagnosis_graph
    config = {"configurable": {"thread_id": f"diagnosis:{workflow_id}"}}
    # Read the actual fixed graph's knowledge_context boundary, not its AI result.
    snapshot = next(s for s in graph.get_state_history(config) if s.next == ("ai_reasoning",))
    return workflow_id, dict(snapshot.values)


def append_material(db, diagnosis, frozen, rows):
    for row in rows:
        db.add(
            DiagnosisEvidence(
                diagnosis_id=diagnosis.id,
                experiment_record_id=diagnosis.experiment_record_id,
                experiment_version_id=diagnosis.experiment_version_id,
                evidence_type="synthetic_query_report",
                source_type=row["source_kind"],
                source_ref=row["source_id"],
                occurred_at=diagnosis.evaluated_at,
                normalized_value={
                    "kind": "observation",
                    "metric": "synthetic_query_report",
                    "value": row["value"],
                    "status": "unknown" if row["value"] == "unclear" else "observed",
                },
                raw_payload={
                    "is_test_data": True,
                    "source_revision": row["source_revision"],
                    "unit_sha256": digest(row),
                },
            )
        )
    db.commit()
    frozen["evidence_registry"] = evidence_reports(
        db.scalars(select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == diagnosis.id))
    )


def safe_records(db, workflow_id):
    return [
        {
            "stage": r.call_stage,
            "status": r.status,
            "error_code": r.error_code,
            "validation_status": r.validation_status,
            "attempt_count": r.attempt_count,
            "model": r.model,
            "prompt_version": r.prompt_version,
        }
        for r in db.scalars(select(AICallRecord).where(AICallRecord.workflow_run_id == workflow_id))
    ]


def terminal(env, db, workflow, frozen, settings, client, cap, *, query=None, task_id=None):
    """Same frozen material through rules and actual fixed graph AI+validator+explanation."""
    device = db.get(Device, workflow.device_id)
    actor = StudentActorContext(
        device.id, workflow.experiment_session_id, demo_device_hash=device.token_hash
    )
    started = time.monotonic()
    prior_active = query["active_seconds"] if query else 0.0
    store = QueryStore(env.engine)

    def check():
        if prior_active + time.monotonic() - started >= 120:
            raise AIQuotaDenied("AI_DEADLINE_EXCEEDED")
        if task_id is not None:
            doc = store.read(task_id)
            if store.guard(doc, "synthetic-actor"):
                raise AIQuotaDenied("AI_RESULT_STALE")
        authorize_student_actor(db, actor, device.id, workflow.experiment_session_id)

    def bounded(*args, **kwargs):
        args = list(args)
        kwargs["cumulative_budget_limit"] = cap
        callback = kwargs.get("recheck_access")

        def both():
            check()
            if callback:
                callback()

        kwargs["recheck_access"] = both
        kwargs["task_attempt_limits"] = TaskAttemptLimits()
        result = GovernedAIInvocation(*args, **kwargs)
        result.deadline = min(result.deadline, started + max(0, 120 - prior_active))
        return result

    # Rules and AI have distinct audit stages; no cached model result crosses groups.
    import app.ai.reasoning as reasoning_service
    import app.services.ai_diagnosis as explanation_service

    real_reason = reasoning_service.reason_about_causes
    real_explain = explanation_service.explain_diagnosis

    def rules_reason(*args, **kwargs):
        kwargs["call_stage"] = "same_material_rules_reasoning"
        return real_reason(*args, **kwargs)

    def rules_explain(*args, **kwargs):
        kwargs["call_stage"] = "same_material_rules_explanation"
        return real_explain(*args, **kwargs)

    rules = deepcopy(frozen)
    runtime = Runtime(
        context=DiagnosisGraphContext(
            db=db,
            device=device,
            settings=settings.model_copy(update={"ai_enabled": False}),
            student_actor=actor,
        )
    )
    with (
        patch("app.ai.diagnosis_graph.reason_about_causes", side_effect=rules_reason),
        patch("app.ai.diagnosis_graph.explain_diagnosis", side_effect=rules_explain),
    ):
        rules.update(ai_reasoning_node(rules, runtime))
        rules.update(knowledge_validation(rules, runtime))
        if rules["knowledge_validation"]["status"] != "rejected":
            rules.update(ai_explanation(rules, runtime))
    rules_output = _approved_result(rules)
    check()
    db.commit()
    graph = build_diagnosis_graph(InMemorySaver())
    config = {"configurable": {"thread_id": f"diagnosis:{workflow.id}"}}
    graph.update_state(config, frozen, as_node="knowledge_context")
    with ExitStack() as stack:
        for module in ("app.ai.reasoning", "app.services.ai_diagnosis"):
            stack.enter_context(patch(f"{module}.build_ai_client", return_value=client))
            stack.enter_context(patch(f"{module}.GovernedAIInvocation", side_effect=bounded))
        graph.invoke(
            None,
            config,
            context=DiagnosisGraphContext(
                db=db,
                device=device,
                settings=settings,
                student_actor=actor,
            ),
        )
    state = dict(graph.get_state(config).values)
    check()
    db.commit()
    calls = safe_records(db, workflow.id)
    return {
        "material_hash": digest(frozen),
        "rules_material_hash": digest(frozen),
        "ai_material_hash": digest(frozen),
        "rules_output": rules_output,
        "output": _approved_result(state),
        "reasoning_mode": state.get("reasoning_mode"),
        "reasoning_status": state.get("reasoning_status"),
        "knowledge_validation": state.get("knowledge_validation"),
        "node_trace": state.get("node_trace"),
        "call_records": calls,
        "active_seconds": prior_active + time.monotonic() - started,
        "invented_cause_links": 0,
    }


def run_pair(case, answer, engine, settings, client, cap, pair_id):
    package = "dht11_temperature_humidity" if case["kind"] == "configuration" else "gpio_led_output"
    result = {
        "id": case["id"],
        "split": case["split"],
        "repeat": int(pair_id.split("-")[-1]),
        "family": case["family"],
        "arms": {},
    }
    for arm in ("A", "B0", "deterministic"):
        with workflow_environment(package, engine=engine, prefix=pair_id + "-" + arm + "-") as env:
            base_id, state = seed_fixed(env, settings)
            with env.sessions() as db:
                clone, workflow, frozen, _, _ = clone_material(env, db, base_id, state, [])
                contract = scenario_contract(case)
                scope = contract.scope.model_copy(
                    update={
                        "task_id": f"{pair_id}-{arm}",
                        "diagnosis_id": clone.id,
                        "session_id": workflow.experiment_session_id,
                    }
                )
                contract = contract.model_copy(update={"scope": scope})
                query = None
                if arm == "A":
                    rows = records(contract, case["initial_values"], "initial")
                    if case["fault"] in {
                        "revoked",
                        "expired",
                        "revision",
                        "cancel",
                        "withdraw_final",
                    }:
                        result["arms"][arm] = {"status": "unavailable", "output": None}
                        continue
                else:
                    store = QueryStore(engine)

                    device = db.get(Device, workflow.device_id)
                    actor = StudentActorContext(
                        device.id,
                        workflow.experiment_session_id,
                        demo_device_hash=device.token_hash,
                    )

                    def selector_factory(
                        key, clone=clone, store=store, contract=contract, actor=actor
                    ):
                        return GovernedAIInvocation(
                            db,
                            clone,
                            settings,
                            call_stage="query_select",
                            cumulative_budget_limit=cap,
                            operation_key=key,
                            task_attempt_limits=TaskAttemptLimits(),
                            recheck_access=lambda: _query_access(store, contract, db, actor),
                        )

                    def recheck_document(doc, actor=actor, device=device, workflow=workflow):
                        authorize_student_actor(
                            db, actor, device.id, workflow.experiment_session_id
                        )
                        db.commit()

                    selector = GovernedSelector(selector_factory, client)
                    query = collect(
                        case,
                        answer,
                        model_scripted=arm == "B0",
                        engine=engine,
                        contract=contract,
                        selector_override=selector,
                        recheck=recheck_document,
                    )
                    query.pop("real_model_calls", None)
                    query.pop("scripted_selections", None)
                    if query["result"]["status"] not in {
                        "completed_satisfied",
                        "completed_unknown",
                    }:
                        result["arms"][arm] = {
                            "status": query["result"]["status"],
                            "query": query,
                            "output": None,
                        }
                        continue
                    rows = query["result"]["evidence"]
                append_material(db, clone, frozen, rows)
                final = terminal(
                    env,
                    db,
                    workflow,
                    frozen,
                    settings,
                    client,
                    cap,
                    query=query,
                    task_id=scope.task_id if query else None,
                )
                result["arms"][arm] = {
                    "status": "delivered",
                    "query": query,
                    "material_count": len(rows),
                    "material": rows,
                    "material_state": contract.view(
                        {"records": rows, "checked": [], "question": None}
                    )["material"],
                    **final,
                }
    result["semantic_review"] = {"status": "not_run", "judgement": None}
    return result


def _query_access(store, contract, db=None, actor=None):
    if store.guard(store.read(contract.scope.task_id), contract.scope.actor_id):
        raise AIQuotaDenied("AI_RESULT_STALE")
    if actor is not None:
        authorize_student_actor(db, actor, actor.device_id, actor.session_id)


def compatibility_probe(engine, settings, client, cap):
    """One real JSON choice with current contracts and legal synthetic FK identity."""
    case = {
        "id": "compatibility-probe",
        "kind": "led_report",
        "fault": "two_tools",
        "initial_values": [],
        "archive_values": [],
    }
    with workflow_environment("gpio_led_output", engine=engine, prefix="probe-") as env:
        workflow_id, state = seed_fixed(env, settings)
        with env.sessions() as db:
            clone, workflow, _, _, _ = clone_material(env, db, workflow_id, state, [])
            contract = scenario_contract(case)
            contract = contract.model_copy(
                update={
                    "scope": contract.scope.model_copy(
                        update={
                            "diagnosis_id": clone.id,
                            "session_id": workflow.experiment_session_id,
                        }
                    )
                }
            )
            store = QueryStore(engine)
            store.setup()
            store.create(contract, [])
            view = contract.view(store.read(contract.scope.task_id))
            device = db.get(Device, workflow.device_id)
            actor = StudentActorContext(
                device.id, workflow.experiment_session_id, demo_device_hash=device.token_hash
            )
            selector = GovernedSelector(
                lambda key: GovernedAIInvocation(
                    db,
                    clone,
                    settings,
                    call_stage="query_select",
                    cumulative_budget_limit=cap,
                    operation_key=key,
                    task_attempt_limits=TaskAttemptLimits(),
                    recheck_access=lambda: _query_access(store, contract, db, actor),
                ),
                client,
            )
            try:
                action = selector(view, "query-evaluation:compatibility-probe")
                return {
                    "status": "passed" if action in view["eligible_actions"] else "rejected",
                    "action": action,
                    "input_hash": digest(view),
                    "native_function_calling": False,
                }
            except Exception as exc:
                return {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                }


def pair_checks(result, expected):
    checks = {}
    for arm in ("B0", "deterministic"):
        entry = result["arms"][arm]
        query = entry["query"]
        target = (
            expected.get("deterministic_status", expected["query_status"])
            if arm == "deterministic"
            else expected["query_status"]
        )
        checks[arm + "_query_status"] = query["result"]["status"] == target
        checks[arm + "_root_unconfirmed"] = query["result"]["root_cause"] == "unconfirmed"
        checks[arm + "_limits"] = (
            query["counts"]["queries"] <= 4
            and query["counts"]["questions"] <= 1
            and query["counts"]["selection_attempts"] <= 3
        )
        if entry["status"] != "delivered":
            checks[arm + "_no_delivery"] = entry["output"] is None
        else:
            checks[arm + "_same_material"] = (
                entry["ai_material_hash"] == entry["rules_material_hash"]
            )
            checks[arm + "_unmodified_error"] = (
                entry["output"]["error_type"] == entry["rules_output"]["error_type"]
            )
    return checks


def comparison_metrics(pairs):
    """Descriptive software measurements; no automated causal/teaching score."""
    increased, comparable, selection_differences, matched = 0, 0, 0, 0
    satisfaction_gain = 0
    genuine_choices, rules_ai = 0, []
    for pair in pairs:
        arms = pair["arms"]
        baseline, queried, deterministic = (arms[k] for k in ("A", "B0", "deterministic"))
        if baseline["status"] == queried["status"] == "delivered":
            comparable += 1
            increased += queried["material_count"] > baseline["material_count"]
            satisfaction_gain += any(
                m["state"] != "present" for m in baseline["material_state"]
            ) and all(m["state"] == "present" for m in queried["material_state"])
        left, right = queried["query"], deterministic["query"]
        genuine_choices += left["counts"]["selection_attempts"]

        def material_signature(result):
            question = result.get("question") or {}

            # Each arm has an independent task/question identity. Compare the same
            # scripted answer by its approved catalogue/version, preserving distinct
            # archive and initial source identities (including identical text).
            def source(row):
                if row["source_id"] == question.get("id"):
                    return "answer:" + question["catalog_id"] + ":" + question["version"]
                return row["source_id"]

            return sorted(
                (r["source_kind"], source(r), r["source_revision"], r["value"])
                for r in result["evidence"]
            )

        equal = left["result"]["status"] == right["result"]["status"] and material_signature(
            left["result"]
        ) == material_signature(right["result"])
        matched += equal
        selection_differences += not equal
        for name, arm in arms.items():
            if arm["status"] == "delivered":
                rules_ai.append(
                    {
                        "id": pair["id"],
                        "repeat": pair["repeat"],
                        "arm": name,
                        "same_material": arm["rules_material_hash"] == arm["ai_material_hash"],
                        "rules_status": arm["rules_output"]["ai_reasoning"]["status"],
                        "ai_status": arm["output"]["ai_reasoning"]["status"],
                        "semantic_judgement": None,
                    }
                )
    return {
        "paired_runs": len(pairs),
        "A_B0_deliverable_pairs": comparable,
        "B0_more_material_pairs": increased,
        "B0_requirement_satisfaction_gain_pairs": satisfaction_gain,
        "B0_selection_attempts": genuine_choices,
        "B0_deterministic_equal_material_and_status": matched,
        "B0_deterministic_different_material_or_status": selection_differences,
        "same_material_rules_ai": rules_ai,
        "diagnostic_accuracy_gain": None,
        "causal_confirmation_gain": None,
        "teaching_gain": None,
    }


def markdown_report(report, path):
    lines = [
        "# Kimi 受控查询配对评测",
        "",
        f"执行状态：{report.get('execution_status', 'incomplete')}；整体：incomplete。",
        "软件断言、真实 API 响应与人工语义分别记录；人工、硬件、课堂未验收。",
        "",
        "| 样本 | 重复 | A | B0 | 确定性查询 | 软件断言 |",
        "|---|---|---|---|---|---|",
    ]
    for pair in report["pairs"]:
        lines.append(
            f"| {pair['id']} | {pair['repeat']} | "
            + " | ".join(pair["arms"][a]["status"] for a in ("A", "B0", "deterministic"))
            + f" | {all(pair.get('checks', {}).values())} |"
        )
    if report.get("usage"):
        lines += [
            "",
            f"实际尝试 {report['usage']['physical_attempts']}；累计记账估算 "
            f"¥{report['usage']['accounted_cny']}；未核对服务商最终账单。",
        ]
    Path(path).write_text("\n".join(lines) + "\n")


def source_fingerprint():
    root = Path(__file__).resolve().parents[2]
    paths = [
        *sorted((root / "app").rglob("*.py")),
        *sorted((root / "experiment_packages").rglob("*.yaml")),
        root / "requirements.lock",
    ]
    return digest(
        {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    )


def evaluate_real(
    directory,
    budget,
    settings,
    *,
    fixtures=FIXTURES,
    repeats=3,
    client=None,
    split="all",
    max_pairs=None,
):
    directory = Path(directory)
    profile = checked_profile(settings, budget)
    fixtures = Path(fixtures)
    scenarios = json.loads((fixtures / "inputs.json").read_text())
    answers = json.loads((fixtures / "answers.json").read_text())
    expectations = json.loads((fixtures / "expectations.json").read_text())
    if repeats not in {1, 2, 3}:
        raise EvaluationBlocked("repeat count must be 1..3")
    binding = {
        "version": VERSION,
        "provider_execution": "injected_test_double" if client is not None else "real_kimi",
        "source_sha256": source_fingerprint(),
        "fixtures": {
            p.name: digest(json.loads(p.read_text())) for p in sorted(fixtures.glob("*.json"))
        },
        "budget": budget,
        "repeats": repeats,
        "model": profile.ai_model,
        "split": split,
        "common_question": COMMON_QUESTION,
        "settings": {
            k: getattr(profile, k)
            for k in (
                "ai_input_token_limit",
                "ai_output_token_limit",
                "ai_max_retries",
                "ai_total_timeout_seconds",
                "ai_daily_budget",
                "ai_max_cost_per_call",
                "ai_calls_per_episode",
                "ai_calls_per_device_hour",
                "ai_require_knowledge",
                "ai_thinking_enabled",
                "ai_transport",
                "ai_prompt_version",
                "ai_schema_version",
            )
        },
    }
    with batch_lock(directory):
        path = directory / "real.json"
        ledger = directory / "synthetic.sqlite3"
        if path.exists():
            report = json.loads(path.read_text())
            if report["binding"] != binding:
                raise EvaluationBlocked(
                    "batch source/fixtures/profile changed; do not reuse paid results"
                )
            if report.get("running_pair"):
                raise EvaluationBlocked(
                    "interrupted pair retained: inspect existing receipts; no automatic redispatch"
                )
            if not ledger.exists():
                raise EvaluationBlocked("batch ledger missing; cannot reset accumulated usage")
        else:
            if ledger.exists():
                raise EvaluationBlocked("orphan ledger requires inspection")
            report = {
                "report_format": VERSION,
                "binding": binding,
                "status": "incomplete",
                "pairs": [],
                "running_pair": None,
                "semantic_review": {"status": "not_run", "judgement": None},
                "hardware": "not_run",
                "classroom": "not_run",
            }
            atomic_json(path, report)
        engine = create_engine(f"sqlite:///{ledger}", connect_args={"check_same_thread": False})
        event.listen(
            engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
        )
        sessions = sessionmaker(bind=engine)
        client = client or build_ai_client(profile)
        count = 0
        try:
            if "compatibility_probe" not in report:
                report["running_pair"] = "compatibility_probe"
                atomic_json(path, report)
                report["compatibility_probe"] = compatibility_probe(
                    engine, profile, client, budget["cap_cny"]
                )
                report["running_pair"] = None
                with sessions() as db:
                    report["usage"] = usage(db)
                atomic_json(path, report)
            if report["compatibility_probe"]["status"] != "passed":
                report["execution_status"] = "probe_blocked"
                atomic_json(path, report)
                return report
            completed = {(r["id"], r["repeat"]) for r in report["pairs"]}
            for case in scenarios:
                if split != "all" and case["split"] != split:
                    continue
                for repeat in range(1, repeats + 1):
                    if (case["id"], repeat) in completed:
                        continue
                    if max_pairs is not None and count >= max_pairs:
                        return report
                    with sessions() as db:
                        consumed = usage(db)
                    worst_pair = 15 * (
                        profile.ai_input_token_limit / 1000 * profile.ai_input_cost_per_1k_tokens
                        + profile.ai_output_token_limit
                        / 1000
                        * profile.ai_output_cost_per_1k_tokens
                    )
                    if consumed["accounted_cny"] + worst_pair > budget["cap_cny"]:
                        report["execution_status"] = "budget_incomplete"
                        report["usage"] = consumed
                        atomic_json(path, report)
                        markdown_report(report, directory / "real.md")
                        return report
                    pair_id = f"{case['id']}-{repeat}"
                    report["running_pair"] = pair_id
                    atomic_json(path, report)
                    result = run_pair(
                        case,
                        answers.get(case["id"]),
                        engine,
                        profile,
                        client,
                        budget["cap_cny"],
                        pair_id,
                    )
                    result["checks"] = pair_checks(result, expectations[case["id"]])
                    report["pairs"].append(result)
                    report["running_pair"] = None
                    with sessions() as db:
                        report["usage"] = usage(db)
                    report["comparison"] = comparison_metrics(report["pairs"])
                    report["code_checks_passed"] = all(
                        all(p["checks"].values()) for p in report["pairs"]
                    )
                    atomic_json(path, report)
                    markdown_report(report, directory / "real.md")
                    fatal = {
                        "AI_OUTCOME_UNKNOWN",
                        "AI_CUMULATIVE_BUDGET_LIMIT",
                        "AI_CUMULATIVE_COST_UNRESOLVED",
                        "DAILY_BUDGET_LIMIT",
                    }
                    observed = {
                        r.get("error_code")
                        for a in result["arms"].values()
                        for r in a.get("call_records", [])
                    }
                    if observed & fatal:
                        report["execution_status"] = "provider_or_budget_incomplete"
                        atomic_json(path, report)
                        markdown_report(report, directory / "real.md")
                        return report
                    if not report["code_checks_passed"]:
                        report["execution_status"] = "checks_failed"
                        atomic_json(path, report)
                        return report
                    print(
                        f"pair {pair_id}: complete; "
                        f"attempts={report['usage']['physical_attempts']}; "
                        f"accounted_cny={report['usage']['accounted_cny']}",
                        flush=True,
                    )
                    count += 1
            report["execution_status"] = "completed"
            atomic_json(path, report)
            markdown_report(report, directory / "real.md")
            return report
        except BaseException as exc:
            report["execution_status"] = "interrupted"
            report["error_type"] = type(exc).__name__
            try:
                with sessions() as db:
                    report["usage"] = usage(db)
            except Exception:
                pass
            atomic_json(path, report)
            raise
        finally:
            engine.dispose()
