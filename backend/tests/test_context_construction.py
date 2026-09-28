import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.ai.context_builder import (
    audit_manifest,
    payload_digest,
    prepare_explanation,
    select_knowledge,
    select_reasoning_constraints,
    selected_sources,
)
from app.ai.context_sanitizer import ProviderInputError, _safe_knowledge, sanitize_provider_payload
from app.ai.reasoning import _reasoning_prompt
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings


def reference(content, **changes):
    return AIKnowledgeReference(
        **(
            {
                "chunk_id": "ctx-case",
                "case_id": "ctx-case",
                "source_key": "ctx-case",
                "source_title": "合成案例",
                "source_type": "structured_case",
                "source_uri": None,
                "source_version": "1",
                "content": json.dumps(content, ensure_ascii=False),
                "similarity": 1,
                "is_test_data": True,
            }
            | changes
        )
    )


def test_long_case_is_whole_or_omitted_never_cut_json():
    item = reference(
        {
            "caseId": "ctx-case",
            "symptom": "合成条件" * 300,
            "teacherNotes": "命令 HIGH 不证明实际电压为 3.3 V，也不证明 LED 已亮。",
        }
    )
    selected = _safe_knowledge([item], Settings(_env_file=None), set())
    assert selected == []


def test_required_51st_evidence_cannot_silently_disappear():
    state = {
        "evidence_registry": [
            {"id": f"e-{i}", "fact": "独立观测", "source": "sensor", "status": "observed"}
            for i in range(51)
        ],
        "fault_tree_candidates": [{"cause_id": "c", "name": "候选", "evidence_refs": ["e-50"]}],
        "evidence_conflict": True,
    }
    with pytest.raises(ProviderInputError):
        _reasoning_prompt(state)


def test_safe_case_keeps_units_negation_and_identity():
    body = {
        "caseId": "ctx-case",
        "normalState": {"voltage": "3.3 V"},
        "teacherNotes": "仅适用合成板；没有独立观测时不能确认 LED 发光。",
    }
    selected, omissions = select_knowledge([reference(body)], Settings(_env_file=None), set())
    assert json.loads(selected[0].content) == body
    assert selected[0].source_version == "1"
    assert omissions == {}


def test_optional_normal_state_does_not_change_matcher_priority():
    constraints = {
        "normal_conditions": [{"case_id": "second", "normal_state": {"unit": "V"}}],
        "standard_fault_mappings": [{"case_id": "first"}, {"case_id": "second"}],
        "teacher_confirmed_cases": [],
    }
    selected, ids, omissions = select_reasoning_constraints(
        constraints, Settings(_env_file=None, ai_knowledge_limit=1), (),
    )
    assert ids == ["first"]
    assert selected["standard_fault_mappings"] == [{"case_id": "first"}]
    assert omissions == {"policy_omitted": 1}


def test_secrets_in_omitted_case_still_redact_retained_case():
    huge = reference({"password": "xx", "symptom": "长" * 2000}, chunk_id="omit", case_id="omit")
    selected, _ = select_knowledge(
        [huge, reference({"note": "xx"})], Settings(_env_file=None), set()
    )
    assert len(selected) == 1
    assert json.loads(selected[0].content)["note"] == "[REDACTED]"


def test_redaction_growth_is_measured_after_cleaning():
    item = reference({"note": "xx" * 40})
    selected, omissions = select_knowledge(
        [item], Settings(_env_file=None, ai_knowledge_content_max_chars=200), {"xx"}
    )
    assert selected == []
    assert omissions == {"budget_omitted": 1}


@pytest.mark.parametrize("field", ["source_version", "source_key", "case_id", "chunk_id"])
def test_identity_secret_is_rejected_not_forged(field):
    item = reference({"note": "合成"}, **{field: "private-value"})
    with pytest.raises(ProviderInputError, match="AI_INPUT_UNSAFE_REFERENCE"):
        select_knowledge([item], Settings(_env_file=None), {"private-value"})


def test_dedupe_is_request_local_and_versions_stay_distinct():
    item = reference({"note": "相同文字"})
    other_version = item.model_copy(update={"source_version": "2"})
    settings = Settings(_env_file=None)
    first, omissions = select_knowledge([item, item, other_version], settings, set())
    assert [ref.source_version for ref in first] == ["1", "2"]
    assert omissions == {"duplicate": 1}
    assert select_knowledge([item], settings, set())[0] == [
        item.model_copy(update={"content": '{"note":"相同文字"}', "source_uri": None})
    ]


def test_distinct_observations_are_not_text_deduplicated():
    state = {
        "evidence_registry": [
            {"id": "one", "fact": "相同读数", "status": "unknown"},
            {"id": "two", "fact": "相同读数", "status": "unknown"},
        ],
        "allowed_verification_actions": [],
    }
    _, user, _, evidence = _reasoning_prompt(state)
    assert [item["id"] for item in evidence] == ["one", "two"]
    assert json.loads(user)["allowed_verification_actions"] == []


def test_required_text_and_reference_never_silently_cut():
    with pytest.raises(ProviderInputError, match="AI_CONTEXT_INCOMPLETE"):
        sanitize_provider_payload(
            {"condition": "a" * 1001}, allowed_fields=["condition"], strict=True
        )
    with pytest.raises(ProviderInputError, match="AI_CONTEXT_INCOMPLETE"):
        _reasoning_prompt({"fault_tree_candidates": [{"cause_id": "c", "evidence_refs": ["x"]}]})


def test_oversize_required_action_and_cause_can_fall_back_without_schema_error():
    from app.ai.reasoning import _fallback_reasoning

    state = {
        "evidence_registry": [{"id": "e", "fact": "合成", "status": "observed"}],
        "fault_tree_candidates": [{"cause_id": "c", "name": "长" * 501, "evidence_refs": ["e"]}],
        "allowed_verification_actions": [{"text": "长" * 1001}],
        "evidence_conflict": True,
    }
    with pytest.raises(ProviderInputError, match="AI_CONTEXT_INCOMPLETE"):
        _reasoning_prompt(state)
    result = _fallback_reasoning(state, limitation="完整材料无法外发。")
    assert result.conclusion == "unknown"
    assert result.ranked_causes == []
    assert result.next_verification_action is None
    assert result.conflict


def test_snapshot_filter_and_attempt_states_do_not_rebind_sources():
    sources = [
        {"kind": "case", "id": "a", "version": "1", "hash": "old"},
        {"kind": "case", "id": "b", "version": "1", "hash": "omit"},
    ]
    selected = selected_sources(sources, {"a"})
    sources[0]["hash"] = "changed"
    base = {"prepared_source_refs": selected}
    assert audit_manifest(base, attempts=0)["submitted_source_refs"] == []
    assert audit_manifest(base, attempts=1)["submitted_source_refs"][0]["hash"] == "old"
    cached = audit_manifest(base, cache_origin="fingerprint")
    assert cached["cache_origin"] == "fingerprint"
    assert cached["provider_attempted"] is False


def test_graph_reads_full_temporary_registry_without_growing_checkpoint(api_context):
    from test_ai_diagnosis import _create_diagnosis

    from app.ai.diagnosis_graph import _persisted_evidence_registry
    from app.ai.reasoning import build_evidence_registry
    from app.models import DiagnosisEvidence

    diagnosis_id = _create_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        # Fake DB iterator exercises the real graph projection's quantity boundary.
        rows = [
            SimpleNamespace(
                id=f"event-{i}",
                evidence_type="observation",
                normalized_value={
                    "kind": "observation",
                    "metric": "voltage",
                    "value": i,
                    "unit": "V",
                    "status": "unknown",
                },
                source_type="sensor_reading",
            )
            for i in range(51)
        ]
        runtime = SimpleNamespace(
            context=SimpleNamespace(db=SimpleNamespace(scalars=lambda _: rows))
        )
        full = _persisted_evidence_registry(runtime, diagnosis_id)
        assert len(full) == 51
        assert full[-1]["id"] == "event-50"
        assert len(build_evidence_registry({"evidence_registry": full})) == 50
        assert db.query(DiagnosisEvidence).count() > 0
        with pytest.raises(ProviderInputError):
            _reasoning_prompt({"evidence_registry": full, "evidence_conflict": True})


@pytest.mark.parametrize("retry", [False, True])
def test_explanation_actual_requests_manifest_cache_and_retry(api_context, monkeypatch, retry):
    from test_ai_diagnosis import FakeAIClient, _create_diagnosis

    from app.models import AICallRecord, Device, DiagnosisResult, KnowledgeCase, MemoryUse
    from app.services.ai_diagnosis import explain_diagnosis

    diagnosis_id = _create_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        primary = diagnosis.matched_rules[0]
        for key in ("ctx-case", "omitted-case"):
            db.add(
                KnowledgeCase(
                    id=key,
                    experiment_type="synthetic",
                    error_type=primary["error_type"],
                    symptom="合成",
                    review_status="approved",
                    facts_locked=True,
                    quality_check_passed=True,
                    root_cause_status="confirmed",
                    source_ref=key,
                    version="1",
                    is_test_data=True,
                )
            )
        db.commit()
        refs = [
            reference({"caseId": "ctx-case", "note": "合成完整条件"}),
            reference({"symptom": "长" * 1500}, chunk_id="omitted-case", case_id="omitted-case"),
        ]

        class Capture(FakeAIClient):
            def __init__(self):
                super().__init__(
                    {
                        "error_type": primary["error_type"],
                        "summary": "合成",
                        "evidence": [],
                        "possible_causes": [],
                        "steps": [],
                        "hint_level": 1,
                        "need_teacher_help": False,
                        "limitations": [],
                    }
                )
                self.requests = []

            def complete_json(self, **kwargs):
                self.requests.append(kwargs)
                if retry and len(self.requests) == 1:
                    from app.ai.clients import AICompletion

                    return AICompletion("{}", input_tokens=1, output_tokens=1)
                return super().complete_json(**kwargs)

        provider = Capture()
        settings = Settings(
            _env_file=None,
            ai_enabled=True,
            ai_require_knowledge=False,
            ai_input_token_limit=20000,
            ai_max_retries=1,
            ai_calls_per_episode=10,
            ai_calls_per_device_hour=10,
        )
        result = explain_diagnosis(
            db, device, diagnosis, settings, ai_client=provider, retrieved_knowledge=refs
        )
        assert result.status == "succeeded"
        record = db.get(AICallRecord, result.call_record_id)
        manifest = record.input_snapshot["context_manifest"]
        submitted = json.loads(provider.requests[0]["user_prompt"])["input"]
        assert manifest["payload_sha256"] == payload_digest(submitted)
        assert (
            manifest["prompt_hash"]
            == hashlib.sha256(
                (
                    provider.requests[0]["system_prompt"]
                    + "\n"
                    + provider.requests[0]["user_prompt"]
                ).encode()
            ).hexdigest()
        )
        assert manifest["selected_ids"]["case_ids"] == ["ctx-case"]
        assert manifest["omission_counts"] == {"budget_omitted": 1}
        uses = db.query(MemoryUse).filter_by(target_id=record.id).all()
        assert {use.source["id"] for use in uses if use.use_kind == "matched"} == {
            "ctx-case",
            "omitted-case",
        }
        assert {use.source["id"] for use in uses if use.use_kind == "provided"} == {"ctx-case"}
        cached = explain_diagnosis(
            db, device, diagnosis, settings, ai_client=provider, retrieved_knowledge=refs
        )
        assert cached.enhancement_status == "cache_hit"
        assert len(provider.requests) == (2 if retry else 1)
        assert all(request == provider.requests[0] for request in provider.requests)
        cache_record = db.get(AICallRecord, cached.call_record_id)
        audit = cache_record.input_snapshot["context_manifest"]
        assert audit["submitted_source_refs"] == []
        assert audit["cache_origin"]
        assert (
            not db.query(MemoryUse).filter_by(target_id=cache_record.id, use_kind="provided").all()
        )
        # Private packing metadata never enlarges the public input Schema.
        assert "context_manifest" not in submitted

        # A policy-only upgrade must not hit the previous cache identity.
        monkeypatch.setattr("app.services.ai_diagnosis.CONTEXT_POLICY_VERSION", "test-next-policy")
        prior_attempts = len(provider.requests)
        changed = explain_diagnosis(
            db, device, diagnosis, settings, ai_client=provider, retrieved_knowledge=refs
        )
        assert changed.enhancement_status != "cache_hit"
        assert len(provider.requests) == prior_attempts + 1
        # Known damaged legacy reference JSON is not delivered or rewritten.
        from app.services.ai_diagnosis import serialize_ai_call

        record.knowledge_references = [{**record.knowledge_references[0], "content": '{"cut":'}]
        record.input_snapshot = {
            key: value for key, value in record.input_snapshot.items() if key != "context_manifest"
        }
        db.commit()
        history = deepcopy(record.input_snapshot)
        old = serialize_ai_call(record, settings)
        assert old.mode == "rules_only"
        assert old.status == "failed"
        assert record.input_snapshot == history
        assert len(provider.requests) == prior_attempts + 1


def test_required_oversize_explanation_has_zero_attempts(api_context):
    from test_ai_diagnosis import FakeAIClient, _create_diagnosis

    from app.models import AICallRecord, Device, DiagnosisResult
    from app.services.ai_diagnosis import explain_diagnosis

    diagnosis_id = _create_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        fake = FakeAIClient({})
        result = explain_diagnosis(
            db,
            db.query(Device).one(),
            db.get(DiagnosisResult, diagnosis_id),
            Settings(
                _env_file=None, ai_enabled=True, ai_require_knowledge=False, ai_input_token_limit=10
            ),
            ai_client=fake,
            retrieved_knowledge=[],
        )
        record = db.get(AICallRecord, result.call_record_id)
        assert fake.calls == record.attempt_count == 0
        assert result.mode == "rules_only"
        assert record.input_snapshot["context_manifest"]["required_complete"] is False


def test_pure_packing_does_not_mutate_input_or_include_private_schema():
    from app.ai.schemas import AIDiagnosisInput

    payload = AIDiagnosisInput(
        diagnosis_result_id="d",
        anonymous_device_id="anon-1234567890abcdef",
        device_state={},
        logs=[],
        sensor_readings=[],
        heartbeats=[],
        rule_matches=[],
        fault_tree_guidance=[],
        allowed_evidence=[],
        knowledge=[reference({"note": "合成"})],
        is_test_data=True,
    )
    before = deepcopy(payload.model_dump())
    prepared, _, _, _ = prepare_explanation(
        payload, Settings(_env_file=None, ai_input_token_limit=10)
    )
    assert prepared.knowledge == []
    assert payload.model_dump() == before
    assert "_context_manifest" not in payload.model_json_schema()["properties"]
