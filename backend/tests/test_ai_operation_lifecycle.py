"""Read-only review reproducer: synthetic SQLite and fake provider only."""

import pytest
from shared_student_authorization import demo_student_actor
from sqlalchemy import select
from test_phase95_runtime_governance import (
    MockDeepSeek,
    _create_sensor_failure,
    _deepseek_settings,
    _structured_output,
)

from app.ai.clients import AIProviderError
from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.models import AICallRecord, Device, DiagnosisResult
from app.models.ai_operation import AIOperation
from app.models.ai_usage_reservation import AIUsageReservation
from app.services.ai_diagnosis import explain_diagnosis


class ProcessLost(BaseException):
    pass


def test_same_stage_reissues_after_unknown_provider_outcome(api_context):
    diagnosis_id = _create_sensor_failure(api_context)
    settings = _deepseek_settings(ai_calls_per_episode=10, ai_calls_per_device_hour=20)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        provider = MockDeepSeek(_structured_output(diagnosis))
    original = provider.complete_json

    def crash_after_provider_received(**kwargs):
        original(**kwargs)
        raise ProcessLost()

    provider.complete_json = crash_after_provider_received
    workflow_id = "00000000-0000-0000-0000-000000000001"
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.get(Device, diagnosis.device_id)
        with pytest.raises(ProcessLost):
            explain_diagnosis(
                db,
                device,
                diagnosis,
                settings,
                student_actor=demo_student_actor(db, device),
                ai_client=provider,
                user_question="请解释本次异常",
                workflow_run_id=workflow_id,
            )
    provider.complete_json = original
    with api_context["session_factory"]() as db:
        pending = list(db.scalars(select(AIUsageReservation)))
        assert len(pending) == 1 and pending[0].status == "reserved"
        assert list(db.scalars(select(AICallRecord))) == []
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.get(Device, diagnosis.device_id)
        explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            student_actor=demo_student_actor(db, device),
            ai_client=provider,
            user_question="请解释本次异常",
            workflow_run_id=workflow_id,
        )
        statuses = [r.status for r in db.scalars(select(AIUsageReservation))]
        print({"provider_calls": provider.calls, "reservation_statuses": statuses})
        assert provider.calls == 1, "same unresolved stage issued another provider request"


@pytest.mark.parametrize("retry_after,total_budget,expected_calls", [(0.05, 1, 2), (5, 0.1, 1)])
def test_rate_limit_obeys_retry_after_and_total_budget(
    api_context,
    retry_after,
    total_budget,
    expected_calls,
):
    import time

    diagnosis_id = _create_sensor_failure(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        provider = MockDeepSeek(_structured_output(diagnosis))
        original = provider.complete_json
        times = []

        def once(**kwargs):
            times.append(time.monotonic())
            if len(times) == 1:
                provider.calls += 1
                raise AIProviderError(
                    "rate limited",
                    code="HTTP_429",
                    status_code=429,
                    retryable=True,
                    retry_after=retry_after,
                    outcome_unknown=False,
                )
            return original(**kwargs)

        provider.complete_json = once
        governor = GovernedAIInvocation(
            db,
            diagnosis,
            _deepseek_settings(
                ai_max_retries=1, ai_total_timeout_seconds=total_budget, ai_calls_per_episode=10
            ),
            call_stage="retry-test",
        )
        with pytest.raises(AIProviderError) as error:
            governor.complete_json(provider, system_prompt="test", user_prompt="test")
        assert governor.retry(error.value)
        if expected_calls == 2:
            governor.complete_json(provider, system_prompt="test", user_prompt="test")
            assert times[1] - times[0] >= retry_after
        else:
            with pytest.raises(AIQuotaDenied, match="AI_DEADLINE_EXCEEDED"):
                governor.complete_json(provider, system_prompt="test", user_prompt="test")
        assert provider.calls == expected_calls
        assert len(list(db.scalars(select(AIUsageReservation)))) == expected_calls


def test_completed_operation_replays_without_second_call_or_reservation(api_context):
    diagnosis_id = _create_sensor_failure(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        provider = MockDeepSeek(_structured_output(diagnosis))
        settings = _deepseek_settings()
        first = GovernedAIInvocation(db, diagnosis, settings, call_stage="replay-test")
        response = first.complete_json(provider, system_prompt="test", user_prompt="test")
        second = GovernedAIInvocation(db, diagnosis, settings, call_stage="replay-test")
        replay = second.complete_json(provider, system_prompt="test", user_prompt="test")
        assert replay == response
        assert provider.calls == 1 and second.attempts == 1
        assert len(list(db.scalars(select(AIUsageReservation)))) == 1
        assert db.scalar(select(AIOperation)).status == "succeeded"
        with pytest.raises(AIQuotaDenied, match="AI_OPERATION_INPUT_CONFLICT"):
            second.complete_json(provider, system_prompt="test", user_prompt="changed")
        assert provider.calls == 1


def test_legacy_unassociated_reservation_blocks_reissue(api_context):
    diagnosis_id = _create_sensor_failure(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        db.add(
            AIUsageReservation(
                diagnosis_result_id=diagnosis.id,
                device_id=diagnosis.device_id,
                call_stage="legacy-test",
                provider="test",
                model="test",
                status="reserved",
                is_test_data=True,
            )
        )
        db.commit()
        provider = MockDeepSeek(_structured_output(diagnosis))
        governor = GovernedAIInvocation(
            db, diagnosis, _deepseek_settings(), call_stage="legacy-test"
        )
        with pytest.raises(AIQuotaDenied, match="AI_LEGACY_OUTCOME_UNRESOLVED"):
            governor.complete_json(provider, system_prompt="test", user_prompt="test")
        assert provider.calls == 0
