import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.core.config import Settings
from app.diagnosis.schemas import ExperimentTemplateContext, MetricRange
from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
from app.models import AICallRecord, Device, DeviceLog, SensorReading
from app.services import diagnosis_workflow as workflow_service
from app.services.diagnosis import build_diagnosis_context, diagnose
from app.services.diagnosis_workflow import start_workflow

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "golden_cases.json"
GOLDEN_CASES = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]
EVALUATED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FrozenWorkflowDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return EVALUATED_AT if tz is not None else EVALUATED_AT.replace(tzinfo=None)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[item["id"] for item in GOLDEN_CASES])
def test_graph_matches_legacy_diagnosis_for_every_golden_case(
    api_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, Any],
) -> None:
    """Keep the 30-case graph shell aligned with every deterministic rule fact.

    The graph deliberately projects raw evidence details into stable IDs so
    checkpoint/API state does not retain log messages. Authority, ordering,
    measured values and exact source references must still match the rule engine.
    """

    monkeypatch.setattr(workflow_service, "datetime", FrozenWorkflowDatetime)
    template = ExperimentTemplateContext(
        template_id="synthetic-template",
        metric_ranges={"synthetic_metric": MetricRange(minimum=0, maximum=100)},
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        device.last_seen_at = EVALUATED_AT - timedelta(seconds=case["seconds_since_seen"])
        if case["event"] is not None:
            db.add(
                DeviceLog(
                    device_id=device.id,
                    level="error",
                    message="synthetic graph equivalence event",
                    event_code=case["event"],
                    occurred_at=EVALUATED_AT,
                    raw_payload={},
                    is_test_data=True,
                )
            )
        db.add(
            SensorReading(
                device_id=device.id,
                sensor_type="synthetic-sensor",
                metric_key="synthetic_metric",
                value=case["value"],
                unit="synthetic-unit",
                observed_at=EVALUATED_AT,
                raw_payload={},
                is_test_data=True,
            )
        )
        db.commit()

        direct_context = build_diagnosis_context(
            db,
            device,
            evaluated_at=EVALUATED_AT,
            lookback_seconds=60,
            experiment_template=template,
        )
        direct = diagnose(direct_context)
        graph = build_diagnosis_graph(InMemorySaver())
        workflow = start_workflow(
            db,
            graph,
            device,
            Settings(
                _env_file=None,
                ai_enabled=False,
                diagnosis_rag_trigger_score=0,
                diagnosis_teacher_review_score=0,
            ),
            DiagnosisWorkflowStartRequest(
                lookback_seconds=60,
                experiment_template=template,
            ),
        )

        direct_facts = [item.model_dump(mode="json") for item in direct.matches]
        assert workflow.status == "completed"
        graph_facts = workflow.final_result["rule_hits"]
        assert [
            (item["rule_id"], item["error_type"], item["priority"], item["summary"])
            for item in graph_facts
        ] == [
            (item["rule_id"], item["error_type"], item["priority"], item["summary"])
            for item in direct_facts
        ]
        for graph_hit, direct_hit in zip(graph_facts, direct_facts):
            assert [(item["fact"], item["observed_value"]) for item in graph_hit["evidence"]] == [
                (item["fact"], item["observed_value"]) for item in direct_hit["evidence"]
            ]
            expected_refs = [
                f"{kind}:{detail[key]}"
                for evidence in direct_hit["evidence"]
                for detail in evidence["details"]
                for key, kind in (("log_id", "log"), ("reading_id", "reading"))
                if detail.get(key)
            ]
            assert [
                ref for evidence in graph_hit["evidence"] for ref in evidence["evidence_refs"]
            ] == expected_refs
        assert [item["error_type"] for item in direct_facts] == case["expected"]
        assert workflow.rule_engine_version == direct.ruleset_version
        assert workflow.final_result["rules_preserved"] is True
        assert db.query(AICallRecord).filter(AICallRecord.status == "succeeded").count() == 0
