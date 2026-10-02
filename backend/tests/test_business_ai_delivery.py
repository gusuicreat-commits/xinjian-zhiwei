import pytest
from test_knowledge_case_drafting import FakePolishClient

from app.ai.governance import AIQuotaDenied
from app.core.config import Settings
from app.knowledge.case_drafting import CaseDraftError, generate_ai_assisted_polish
from app.models import DiagnosisEpisode, DiagnosisResult
from app.models.ai_usage_reservation import AIUsageReservation

pytest_plugins = ["test_knowledge_case_drafting"]


def test_one_model_attempt_is_charged_once_and_attributed_to_both_problems(api_context):
    from test_business_issues import two_issues

    from app.ai.clients import AICompletion
    from app.ai.governance import GovernedAIInvocation

    result = two_issues(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, result["id"])

        class Provider:
            configured = True
            provider = model = "synthetic"

            def complete_json(self, **kwargs):
                return AICompletion("{}", input_tokens=1, output_tokens=1)

        settings = Settings(ai_enabled=True, ai_calls_per_episode=1)
        governor = GovernedAIInvocation(db, diagnosis, settings, call_stage="synthetic")
        governor.complete_json(Provider(), system_prompt="s", user_prompt="u")
        reservation = db.query(AIUsageReservation).one()
        assert set(reservation.attribution["episode_ids"]) == {i["id"] for i in result["issues"]}
        assert all(db.get(DiagnosisEpisode, i["id"]).ai_call_count == 1 for i in result["issues"])
        replay = governor.complete_json(Provider(), system_prompt="s", user_prompt="u")
        assert replay.content == "{}"
        independent = GovernedAIInvocation(
            db, diagnosis, settings, call_stage="synthetic",
            operation_key="explicit-new-business-operation",
        )
        with pytest.raises(AIQuotaDenied, match="EPISODE_CALL_LIMIT"):
            independent.complete_json(Provider(), system_prompt="s", user_prompt="u")
        assert db.query(AIUsageReservation).count() == 1


def test_late_polish_is_discarded_but_actual_call_remains_charged(persisted_draft):
    db, draft = persisted_draft
    diagnosis = db.get(DiagnosisResult, draft.diagnosis_result_id)

    class ResolvingProvider(FakePolishClient):
        def complete_json(self, **kwargs):
            result = super().complete_json(**kwargs)
            episode = db.get(DiagnosisEpisode, diagnosis.episode_id)
            episode.evidence_revision += 1  # a new diagnosis arrives while I/O is pending
            db.commit()
            return result

    provider = ResolvingProvider()
    with pytest.raises(CaseDraftError) as caught:
        generate_ai_assisted_polish(
            db,
            draft,
            Settings(ai_enabled=True),
            ai_client=provider,
            actor_context=db.info["case_actor"],
        )
    assert isinstance(caught.value.__cause__, AIQuotaDenied)
    assert caught.value.__cause__.code == "AI_RESULT_STALE"
    assert len(provider.prompts) == 1
    assert db.query(AIUsageReservation).count() == 1
    assert db.query(AIUsageReservation).one().status == "succeeded"
    db.refresh(draft)
    assert draft.polished_payload is None
