"""Paid-run harness checks use a synthetic provider; no real endpoint is contacted."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.clients import AICompletion
from app.core.config import Settings
from app.evaluation.query_real import (
    EvaluationBlocked,
    checked_profile,
    evaluate_real,
)
from app.evaluation.query_runner import FIXTURES
from app.evaluation.workflow_environment import ScriptedProvider
from app.models.ai_usage_reservation import AIUsageReservation


class SyntheticProvider(ScriptedProvider):
    def __init__(self):
        super().__init__("unknown")

    def complete_json(self, *, system_prompt, user_prompt):
        data = json.loads(user_prompt)
        if "eligible_actions" in data:
            self.calls.append({"stage": "query_select", "data": data})
            return AICompletion(
                json.dumps(data["eligible_actions"][0]), input_tokens=50, output_tokens=30
            )
        response = super().complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        parsed = json.loads(response.content)
        if "candidate_causes" in data:
            parsed["conflict"] = bool(data.get("evidence_conflict"))
        return AICompletion(
            json.dumps(parsed, ensure_ascii=False), input_tokens=50, output_tokens=30
        )


def config():
    return Settings(
        _env_file=None,
        ai_provider="kimi",
        ai_model="kimi-k2.6",
        ai_base_url="https://api.moonshot.cn/v1",
        ai_api_key="synthetic-not-a-key",
        ai_input_token_limit=10000,
        ai_max_retries=0,
        ai_input_cost_per_1k_tokens=0.0065,
        ai_output_cost_per_1k_tokens=0.027,
        ai_daily_budget=10,
        ai_max_cost_per_call=0.1,
    )


def budget():
    return {
        "authorization": "explicit_new_batch_cap",
        "cap_cny": 10,
        "authorized_by_user": True,
        "authorization_text": "synthetic test authorization",
        "price_verified_at": "2026-10-07",
        "price_source": "https://platform.kimi.com/docs/pricing/chat",
        "price_version": "synthetic-test",
        "ai_input_cost_per_1k_tokens": 0.0065,
        "ai_output_cost_per_1k_tokens": 0.027,
    }


def fixture_subset(tmp_path, ids):
    target = tmp_path / "fixtures"
    target.mkdir()
    for name in ("inputs", "expectations", "answers"):
        data = json.loads((FIXTURES / f"{name}.json").read_text())
        data = (
            [c for c in data if c["id"] in ids]
            if isinstance(data, list)
            else {k: v for k, v in data.items() if k in ids}
        )
        (target / f"{name}.json").write_text(json.dumps(data))
    return target


def test_real_full_tail_same_material_and_resume_no_redispatch(tmp_path):
    provider = SyntheticProvider()
    fixtures = fixture_subset(tmp_path, {"d01", "d11"})
    result = evaluate_real(
        tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
    )
    assert result["execution_status"] == "completed"
    assert len(result["pairs"]) == 2
    for arm in result["pairs"][0]["arms"].values():
        assert arm["ai_material_hash"] == arm["rules_material_hash"]
        assert {"ai_reasoning", "knowledge_validation", "ai_explanation"} <= set(arm["node_trace"])
        assert arm["reasoning_mode"] == "ai"
        assert arm["invented_cause_links"] == 0
    count = len(provider.calls)
    assert (
        count == 5
    )  # probe + 3 reasoning + one genuine action choice; draft knowledge blocks explanation
    assert all(
        any(r["error_code"] == "KNOWLEDGE_NOT_READY" for r in a["call_records"])
        for a in result["pairs"][0]["arms"].values()
    )
    resumed = evaluate_real(
        tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
    )
    assert len(provider.calls) == count == resumed["usage"]["physical_attempts"]
    assert all("answer" not in call.get("data", {}) for call in provider.calls)


def test_missing_or_invalid_budget_cannot_enable_provider():
    for cap in (None, -1, float("inf"), True):
        value = budget()
        value["cap_cny"] = cap
        with pytest.raises(EvaluationBlocked):
            checked_profile(config(), value)


def test_cumulative_allowance_keeps_old_and_unknown_reservations(tmp_path):
    provider = SyntheticProvider()
    fixtures = fixture_subset(tmp_path, {"d01"})
    evaluate_real(
        tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'batch/synthetic.sqlite3'}")
    with Session(engine) as db:
        rows = list(db.scalars(select(AIUsageReservation)))
        for row in rows:
            row.created_at = datetime.now(timezone.utc) - timedelta(days=3)
            row.status = "reserved"
            row.accounted_cost = 0.1
        db.commit()
        from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
        from app.models import DiagnosisResult

        before = len(provider.calls)
        diagnosis = db.get(DiagnosisResult, rows[1].diagnosis_result_id)
        with pytest.raises(AIQuotaDenied, match="AI_CUMULATIVE_BUDGET_LIMIT"):
            GovernedAIInvocation(
                db,
                diagnosis,
                checked_profile(config(), budget()),
                call_stage="late",
                cumulative_budget_limit=0.01,
            ).complete_json(provider, system_prompt="json", user_prompt="{}")
        assert len(provider.calls) == before
    engine.dispose()


def test_full_explanation_service_runs_with_explicit_synthetic_no_knowledge_profile(tmp_path):
    provider = SyntheticProvider()
    fixtures = fixture_subset(tmp_path, {"d01"})
    profile = config().model_copy(update={"ai_require_knowledge": False})
    result = evaluate_real(
        tmp_path / "batch", budget(), profile, fixtures=fixtures, repeats=1, client=provider
    )
    assert result["execution_status"] == "completed"
    for arm in result["pairs"][0]["arms"].values():
        explanation = next(r for r in arm["call_records"] if r["stage"] == "explanation")
        assert explanation["status"] == "succeeded"
        assert explanation["attempt_count"] == 1
        assert arm["output"]["ai_reasoning"]["ranked_causes"] == []
    assert result["usage"]["physical_attempts"] == 7


def test_interrupted_paid_pair_cannot_be_reissued_on_restart(tmp_path):
    class Interrupted(SyntheticProvider):
        def complete_json(self, **kwargs):
            if len(self.calls) == 1:
                raise KeyboardInterrupt("simulated process loss after probe")
            return super().complete_json(**kwargs)

    provider = Interrupted()
    fixtures = fixture_subset(tmp_path, {"d01"})
    with pytest.raises(KeyboardInterrupt):
        evaluate_real(
            tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
        )
    before = len(provider.calls)
    with pytest.raises(EvaluationBlocked, match="interrupted pair"):
        evaluate_real(
            tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
        )
    assert len(provider.calls) == before
    report = json.loads((tmp_path / "batch/real.json").read_text())
    assert report["running_pair"] == "d01-1"
    assert report["usage"]["physical_attempts"] == 2
    assert report["usage"]["unsettled_reserved_cny"] > 0


def test_changed_profile_cannot_reuse_paid_batch(tmp_path):
    fixtures = fixture_subset(tmp_path, {"d01"})
    provider = SyntheticProvider()
    evaluate_real(
        tmp_path / "batch", budget(), config(), fixtures=fixtures, repeats=1, client=provider
    )
    before = len(provider.calls)
    changed = budget()
    changed["cap_cny"] = 20
    with pytest.raises(EvaluationBlocked, match="changed"):
        evaluate_real(
            tmp_path / "batch", changed, config(), fixtures=fixtures, repeats=1, client=provider
        )
    assert len(provider.calls) == before


def test_zero_budget_probe_has_no_physical_request(tmp_path):
    fixtures = fixture_subset(tmp_path, {"d01"})
    provider = SyntheticProvider()
    value = budget()
    value["cap_cny"] = 0.000001
    result = evaluate_real(
        tmp_path / "batch", value, config(), fixtures=fixtures, repeats=1, client=provider
    )
    assert result["execution_status"] == "probe_blocked"
    assert result["usage"]["physical_attempts"] == 0
    assert provider.calls == []


def test_rules_and_ai_receive_identical_live_material_not_just_report_hash(tmp_path, monkeypatch):
    import app.ai.diagnosis_graph as graph_module
    import app.ai.reasoning as reasoning_module
    from app.evaluation.query_contract import digest

    seen = []
    original = reasoning_module.reason_about_causes

    def inspect(db, diagnosis, state, settings, **kwargs):
        seen.append(
            (
                diagnosis.id,
                settings.ai_enabled,
                digest(
                    {
                        k: state.get(k)
                        for k in (
                            "evidence_registry",
                            "fault_tree_candidates",
                            "evidence_conflict",
                            "allowed_verification_actions",
                            "knowledge_constraints",
                        )
                    }
                ),
            )
        )
        return original(db, diagnosis, state, settings, **kwargs)

    monkeypatch.setattr(reasoning_module, "reason_about_causes", inspect)
    monkeypatch.setattr(graph_module, "reason_about_causes", inspect)
    fixtures = fixture_subset(tmp_path, {"d03"})
    result = evaluate_real(
        tmp_path / "batch",
        budget(),
        config(),
        fixtures=fixtures,
        repeats=1,
        client=SyntheticProvider(),
    )
    assert result["code_checks_passed"]
    ai_calls = [(identity, value) for identity, enabled, value in seen if enabled]
    assert len(ai_calls) == 3
    for identity, material in ai_calls:
        assert (identity, False, material) in seen
    assert result["comparison"]["B0_more_material_pairs"] == 1


def test_probe_revoked_credential_after_response_is_not_adopted(tmp_path):
    from app.evaluation.query_real import compatibility_probe, usage
    from app.models import Device

    engine = create_engine(f"sqlite:///{tmp_path / 'scope.sqlite3'}")

    class Revoking(SyntheticProvider):
        def complete_json(self, **kwargs):
            response = super().complete_json(**kwargs)
            with Session(engine) as db:
                device = db.scalar(select(Device))
                device.token_hash = "synthetic-revoked-credential"
                db.commit()
            return response

    provider = Revoking()
    result = compatibility_probe(engine, checked_profile(config(), budget()), provider, 10)
    assert result["status"] == "failed"
    assert "action" not in result
    with Session(engine) as db:
        assert usage(db)["physical_attempts"] == 1
    assert len(provider.calls) == 1
    engine.dispose()


def test_equivalent_answers_in_independent_scopes_are_not_selection_gain(tmp_path):
    fixtures = fixture_subset(tmp_path, {"d05", "d06"})
    result = evaluate_real(
        tmp_path / "batch",
        budget(),
        config(),
        fixtures=fixtures,
        repeats=1,
        client=SyntheticProvider(),
    )
    assert result["comparison"]["B0_deterministic_different_material_or_status"] == 0
    assert result["comparison"]["B0_requirement_satisfaction_gain_pairs"] == 1
