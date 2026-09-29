"""Runtime boundaries for package applicability; all data are synthetic."""

import json
from copy import deepcopy

from app.ai.context_builder import select_knowledge
from app.ai.context_contract import CONTEXT_POLICY_VERSION
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.services.ai_diagnosis import serialize_ai_call


def test_private_authorized_source_secrets_are_removed_before_projection():
    ref = AIKnowledgeReference(
        chunk_id="case-1", source_key="case-1", source_title="合成",
        source_type="structured_case", source_uri=None, source_version="1",
        content=json.dumps({"applicability": {"limits_text": "仅适用 secret-fixture"}}),
        similarity=1, is_test_data=True,
    )
    ref._sensitive_sources = ({"confirmation_material": {"password": "secret-fixture"}},)
    selected, _ = select_knowledge([ref], Settings(_env_file=None), set())
    assert "secret-fixture" not in selected[0].content
    assert "_sensitive_sources" not in selected[0].model_dump()


def test_context_policy_identifies_applicability_contract():
    assert CONTEXT_POLICY_VERSION == "whole-unit-applicability-v1"


def test_old_explanation_cannot_replay_as_current_suggestion(monkeypatch):
    from app.ai.output_contract import OUTPUT_CONTRACT_VERSION
    from app.ai.schemas import AIExplanationResponse
    from app.models.ai_call_record import AICallRecord

    # Isolate policy from the existing separate database-availability guard.
    def response(record, explanation, knowledge, settings, notice, **kwargs):
        return AIExplanationResponse(
            call_record_id=record.id, diagnosis_result_id=record.diagnosis_result_id,
            status="succeeded", mode="ai_enhanced", provider_configured=False,
            explanation=explanation, knowledge_references=knowledge, notice=notice,
        )
    monkeypatch.setattr("app.services.ai_diagnosis._response", response)

    record = AICallRecord(
        id="synthetic-call", diagnosis_result_id="synthetic-diagnosis",
        status="succeeded", knowledge_references=[],
        input_snapshot={"output_contract": {
            "version": OUTPUT_CONTRACT_VERSION, "allowed_steps": [],
            "summary": "旧建议", "limitations": [],
        }},
        output_json={"error_type": "SAMPLE", "summary": "旧建议", "evidence": [],
                     "possible_causes": [], "steps": [], "hint_level": 1,
                     "need_teacher_help": False, "limitations": []},
    )
    response = serialize_ai_call(record, Settings(_env_file=None))
    assert response.mode == "rules_only"
    assert response.explanation is None
    assert record.output_json["summary"] == "旧建议"


def test_package_conditions_reach_actual_two_stage_requests_without_private_review(monkeypatch):
    from test_teaching_materials import start

    from app.evaluation import workflow_environment as fixture
    from app.experiment_packages.loader import load_experiment_package_payload, package_documents
    from app.models import AICallRecord

    original_loader = fixture.load_experiment_package
    limits = ("仅适用合成接线；secret-fixture、private-reviewer、private-recovery "
              "尚不能证明实际电压，需独立核验。")

    def controlled_package(path):
        bundle, report = original_loader(path)
        if path.name != "dht11_temperature_humidity":
            return bundle, report
        docs = package_documents(bundle)
        case = docs["knowledge/cases.yaml"]["cases"][0]
        # Independent controlled fixture, never changes the draft sample on disk.
        case.update(sourceType="controlled_test", reviewStatus="approved", factsLocked=True,
                    qualityCheckPassed=True, rootCauseStatus="confirmed",
                    rootCauseValue="wiring.data_pin_mismatch", normalState={}, evidence=[],
                    possibleCauses=["wiring.data_pin_mismatch"], solutionSteps=[],
                    symptom="合成故障 secret-fixture private-reviewer", teacherNotes=None,
                    confirmedBy="private-reviewer")
        case["solutionRecord"] = {"confirmation_material": {
            "applicability_limits": limits, "password": "secret-fixture",
            "confirmed_by": "private-reviewer", "recovery_diagnosis_id": "private-recovery",
        }}
        return load_experiment_package_payload(docs)

    monkeypatch.setattr(fixture, "load_experiment_package", controlled_package)
    with fixture.workflow_environment("dht11_temperature_humidity") as env:
        original_call = env.provider.complete_json
        prompts = []

        def capture(**kwargs):
            prompts.append(json.loads(kwargs["user_prompt"]))
            return original_call(**kwargs)

        env.provider.complete_json = capture
        result = start(env)
        reasoning = next(p for p in prompts if "candidate_causes" in p)
        explanation = next(p for p in prompts if "input" in p)
        expected = limits
        for secret in ("secret-fixture", "private-reviewer", "private-recovery"):
            expected = expected.replace(secret, "[REDACTED]")
        applicability = reasoning["knowledge_constraints"]["standard_fault_mappings"][0][
            "applicability"
        ]
        assert applicability["limits_text"] == expected
        assert applicability["condition_status"] == "text_only"
        ref = explanation["input"]["knowledge"][0]
        assert json.loads(ref["content"])["applicability"] == applicability
        assert any("尚未自动核验" in text for text in explanation["output_contract"]["limitations"])
        assert all(secret not in json.dumps(prompts) for secret in
                   ("secret-fixture", "private-reviewer", "private-recovery"))
        checkpoint = env.app.state.diagnosis_graph.get_state({"configurable": {
            "thread_id": f"diagnosis:{result['id']}",
        }}).values
        assert "_sensitive_sources" not in json.dumps(checkpoint, default=str)
        assert all(secret not in json.dumps(checkpoint, default=str) for secret in
                   ("secret-fixture", "private-reviewer", "private-recovery"))
        with env.sessions() as db:
            records = db.query(AICallRecord).filter_by(workflow_run_id=result["id"]).all()
            assert len(records) == 2
            assert all(row.status == "succeeded" for row in records)
            assert all(row.input_snapshot["context_manifest"]["policy_version"] ==
                       CONTEXT_POLICY_VERSION for row in records)
            assert all(secret not in json.dumps([r.input_snapshot for r in records])
                       for secret in ("secret-fixture", "private-reviewer", "private-recovery"))


def test_global_limits_change_prompt_and_source_fingerprints(api_context):
    from test_ai_diagnosis import FakeAIClient, _create_diagnosis

    from app.ai.context_builder import prepare_explanation
    from app.models import AICallRecord, Device, DiagnosisResult, KnowledgeCase
    from app.services.ai_diagnosis import (
        _build_input,
        _match_structured_knowledge,
        explain_diagnosis,
    )
    from app.services.memory import case_source

    diagnosis_id = _create_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        error = diagnosis.matched_rules[0]["error_type"]
        case = KnowledgeCase(
            id="limit-case", experiment_type="synthetic", error_type=error,
            symptom="受控夹具", root_cause_status="confirmed", facts_locked=True,
            quality_check_passed=True, review_status="approved", source_ref="limit-case",
            version="1", is_test_data=True,
            solution_record={"confirmation_material": {
                "applicability_limits": "仅为合成输入条件 secret-fixture。",
                "password": "secret-fixture",
            }},
        )
        db.add(case)
        db.commit()
        settings = Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=True,
                            ai_max_retries=0, ai_input_token_limit=20000,
                            ai_calls_per_episode=10, ai_calls_per_device_hour=10)
        provider = FakeAIClient({
            "error_type": error, "summary": "测试", "evidence": [], "possible_causes": [],
            "steps": [], "hint_level": 1, "need_teacher_help": False, "limitations": [],
        })
        first = explain_diagnosis(db, device, diagnosis, settings, ai_client=provider)
        assert first.status == "succeeded"
        assert "secret-fixture" not in first.knowledge_references[0].content
        before = deepcopy(db.get(AICallRecord, first.call_record_id).input_snapshot)
        before_source = case_source(case)
        before_input = _build_input(
            diagnosis, [], _match_structured_knowledge(db, diagnosis, [], settings), settings,
            episode_id=None, user_question=None, workflow_state=None,
        )
        before_prompt = prepare_explanation(before_input, settings)[3]
        case.solution_record = {"confirmation_material": {
            "applicability_limits": "仅为新的合成输入条件，要求额外独立观测。",
        }}
        db.commit()
        assert before_source["hash"] != case_source(case)["hash"]
        after_input = _build_input(
            diagnosis, [], _match_structured_knowledge(db, diagnosis, [], settings), settings,
            episode_id=None, user_question=None, workflow_state=None,
        )
        assert before_prompt != prepare_explanation(after_input, settings)[3]
        second = explain_diagnosis(db, device, diagnosis, settings, ai_client=provider)
        # The original diagnosis has immutable provenance: changed source content
        # cannot silently refresh or incur another charge on the same old advice.
        assert second.status == "skipped"
        assert provider.calls == 1
        assert db.get(AICallRecord, first.call_record_id).input_snapshot == before


def test_global_case_limits_reach_actual_graph_reasoning_and_explanation(api_context, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from test_diagnosis_workflow import _add_failure_log, _settings

    from app.ai.diagnosis_graph import build_diagnosis_graph
    from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
    from app.evaluation.workflow_environment import ScriptedProvider
    from app.models import Device, KnowledgeCase
    from app.services.diagnosis_workflow import start_workflow

    _add_failure_log(api_context)
    provider = ScriptedProvider("valid")
    prompts = []
    original = provider.complete_json

    def capture(**kwargs):
        prompts.append(json.loads(kwargs["user_prompt"]))
        return original(**kwargs)

    provider.complete_json = capture
    for module in ("app.ai.reasoning", "app.services.ai_diagnosis"):
        monkeypatch.setattr(f"{module}.build_ai_client", lambda _settings: provider)
    limits = "仅用于全局案例合成回归，不证明本次接线异常。"
    with api_context["session_factory"]() as db:
        db.add(KnowledgeCase(
            id="global-two-stage", experiment_type="synthetic", error_type="SENSOR_READ_FAILED",
            symptom="合成失败", root_cause_status="confirmed", facts_locked=True,
            quality_check_passed=True, review_status="approved", source_ref="global-two-stage",
            version="1", is_test_data=True,
            solution_record={"confirmation_material": {"applicability_limits": limits}},
        ))
        db.commit()
        workflow = start_workflow(
            db, build_diagnosis_graph(InMemorySaver()), db.query(Device).one(),
            _settings(ai_enabled=True, ai_require_knowledge=True, ai_input_token_limit=20000),
            DiagnosisWorkflowStartRequest(lookback_seconds=60, question="解释合成异常"),
        )
        assert workflow.experiment_version_id is None
        reasoning = next(p for p in prompts if "candidate_causes" in p)
        explanation = next(p for p in prompts if "input" in p)
        assert reasoning["knowledge_constraints"]["standard_fault_mappings"][0][
            "applicability"
        ]["limits_text"] == limits
        assert json.loads(explanation["input"]["knowledge"][0]["content"])[
            "applicability"
        ]["limits_text"] == limits
        assert len(prompts) == 2
