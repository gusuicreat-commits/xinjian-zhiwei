"""Cross-entry timing regressions: revocation completed before provider dispatch."""

import pytest
from sqlalchemy import func, select
from test_knowledge_case_drafting import persisted_draft as persisted_draft
from test_memory_lifecycle import memory_task as memory_task
from test_phase95_runtime_governance import (
    MockDeepSeek,
    _create_sensor_failure,
    _deepseek_settings,
    _structured_output,
)

from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.models import DiagnosisResult, ExperimentSession
from app.models.ai_usage_reservation import AIUsageReservation


@pytest.mark.parametrize('replay', [False, True], ids=['new-dispatch', 'saved-completion'])
def test_scope_revoked_during_wait_blocks_dispatch_and_replay(api_context, monkeypatch, replay):
    diagnosis_id = _create_sensor_failure(api_context)
    with api_context['session_factory']() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        provider = MockDeepSeek(_structured_output(diagnosis))
        settings = _deepseek_settings()
        if replay:
            GovernedAIInvocation(db, diagnosis, settings, call_stage='wait-scope').complete_json(
                provider, system_prompt='test', user_prompt='test',
            )
        before_calls = provider.calls
        governor = GovernedAIInvocation(db, diagnosis, settings, call_stage='wait-scope')
        original_wait = governor._wait_retry

        def revoke_after_wait():
            original_wait()
            db.commit()
            with api_context['session_factory']() as revoked:
                session = revoked.get(ExperimentSession, api_context['experiment_session_id'])
                session.status = 'cancelled'
                revoked.commit()

        monkeypatch.setattr(governor, '_wait_retry', revoke_after_wait)
        with pytest.raises(AIQuotaDenied):
            governor.complete_json(provider, system_prompt='test', user_prompt='test')
        assert provider.calls == before_calls, 'revoked scope must not dispatch another request'
        assert db.scalar(select(func.count(AIUsageReservation.id))) == int(replay)


@pytest.mark.parametrize('kind', ['session', 'role', 'enrollment', 'device_token'])
def test_student_authority_revoked_in_dispatch_wait_never_sends(api_context, monkeypatch, kind):
    from shared_student_authorization import demo_student_actor
    from test_student_write_authorization import account_identity, revoke

    from app.models import Device
    from app.services.ai_diagnosis import explain_diagnosis
    from app.services.auth import AuthorizationDenied
    from app.services.data_scope import ScopeViolation

    diagnosis_id = _create_sensor_failure(api_context)
    with api_context['session_factory']() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.get(Device, diagnosis.device_id)
        identity = (demo_student_actor(db, device) if kind == 'device_token'
                    else account_identity(db))
        provider = MockDeepSeek(_structured_output(diagnosis))
        original_wait = GovernedAIInvocation._wait_retry

        def revoked_wait(governor):
            original_wait(governor)
            db.commit()
            with api_context['session_factory']() as revoked:
                revoke(revoked, identity, kind)

        monkeypatch.setattr(GovernedAIInvocation, '_wait_retry', revoked_wait)
        with pytest.raises((AuthorizationDenied, ScopeViolation)):
            explain_diagnosis(db, device, diagnosis, _deepseek_settings(),
                              student_actor=identity, ai_client=provider)
        assert provider.calls == 0
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 0


@pytest.mark.parametrize('change', ['withdrawn', 'version'])
@pytest.mark.parametrize('replay', [False, True])
def test_source_changed_during_wait_blocks_new_and_saved_result(memory_task, monkeypatch,  # noqa: F811
                                                               change, replay):
    from test_ai_quota_concurrency import CountingProvider

    db, _, case, diagnosis, _, _ = memory_task
    provider = CountingProvider()
    settings = _deepseek_settings()
    kwargs = dict(call_stage='source-wait', knowledge_case_ids=(case.id,))
    if replay:
        GovernedAIInvocation(db, diagnosis, settings, **kwargs).complete_json(
            provider, system_prompt='test', user_prompt='test',
        )
    governor = GovernedAIInvocation(db, diagnosis, settings, **kwargs)
    before_calls = provider.calls

    def source_changes():
        if change == 'withdrawn':
            case.review_status = 'withdrawn'
        else:
            case.version = 'changed'
        db.commit()

    monkeypatch.setattr(governor, '_wait_retry', source_changes)
    with pytest.raises(AIQuotaDenied, match='AI_KNOWLEDGE_'):
        governor.complete_json(provider, system_prompt='test', user_prompt='test')
    assert provider.calls == before_calls
    assert db.scalar(select(func.count(AIUsageReservation.id))) == int(replay)


def test_polish_revoked_while_waiting_never_sends(persisted_draft, monkeypatch):  # noqa: F811
    from test_knowledge_case_drafting import FakePolishClient

    from app.knowledge.case_drafting import generate_ai_assisted_polish
    from app.models.base import utc_now
    from app.models.classroom import AuthSession
    from app.services.auth import AuthorizationDenied

    db, draft = persisted_draft
    identity = db.info['case_actor']
    provider = FakePolishClient()
    version = draft.version_no

    def revoke_after_wait(governor):
        db.get(AuthSession, identity.session_id).revoked_at = utc_now()
        db.commit()

    monkeypatch.setattr(GovernedAIInvocation, '_wait_retry', revoke_after_wait)
    with pytest.raises(AuthorizationDenied):
        generate_ai_assisted_polish(db, draft, _deepseek_settings(), ai_client=provider,
                                   actor_context=identity)
    assert provider.prompts == []
    assert db.scalar(select(func.count(AIUsageReservation.id))) == 0
    db.refresh(draft)
    assert draft.version_no == version and draft.polished_payload is None
    from app.models import AuditEvent

    assert db.scalar(select(func.count(AuditEvent.id)).where(
        AuditEvent.action == "ai.delivery_denied")) == 0


def test_fixed_graph_reasoning_revalidates_runtime_actor(api_context, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from test_ai_quota_concurrency import CountingProvider
    from test_diagnosis_workflow import _add_failure_log, _settings
    from test_student_write_authorization import account_identity, revoke

    from app.ai.diagnosis_graph import build_diagnosis_graph
    from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
    from app.models import Device
    from app.services.auth import AuthorizationDenied
    from app.services.diagnosis_workflow import start_workflow

    _add_failure_log(api_context)
    with api_context['session_factory']() as db:
        identity = account_identity(db)
        provider = CountingProvider()
        monkeypatch.setattr('app.ai.reasoning.build_ai_client', lambda settings: provider)
        stages = []

        def revoked_wait(governor):
            stages.append(governor.call_stage)
            revoke(db, identity, 'session')

        monkeypatch.setattr(GovernedAIInvocation, '_wait_retry', revoked_wait)
        with pytest.raises(AuthorizationDenied):
            start_workflow(
                db, build_diagnosis_graph(InMemorySaver()), db.get(Device, identity.device_id),
                _settings(ai_enabled=True, ai_require_knowledge=False),
                DiagnosisWorkflowStartRequest(lookback_seconds=60), student_actor=identity,
            )
        assert stages == ['reasoning']
        assert provider.calls == 0
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 0


def test_process_quota_lock_obeys_deadline_without_leaving_transaction(api_context):
    from concurrent.futures import ThreadPoolExecutor

    from app.ai.governance import _reservation_lock

    diagnosis_id = _create_sensor_failure(api_context)
    providers = []

    def worker():
        with api_context['session_factory']() as db:
            diagnosis = db.get(DiagnosisResult, diagnosis_id)
            provider = MockDeepSeek(_structured_output(diagnosis))
            providers.append(provider)
            governor = GovernedAIInvocation(
                db, diagnosis, _deepseek_settings(ai_total_timeout_seconds=0.15),
                call_stage='thread-deadline',
            )
            with pytest.raises(AIQuotaDenied, match='AI_DEADLINE_EXCEEDED'):
                governor.complete_json(provider, system_prompt='s', user_prompt='u')
            assert not db.in_transaction()
            assert db.scalar(select(func.count(AIUsageReservation.id))) == 0

    with ThreadPoolExecutor(max_workers=1) as pool:
        _reservation_lock.acquire()
        try:
            pool.submit(worker).result(timeout=1.5)
        finally:
            _reservation_lock.release()
    assert len(providers) == 1 and providers[0].calls == 0


def test_saved_completion_replays_after_original_dispatch_deadline(api_context):
    from datetime import timedelta

    from app.models.ai_operation import AIOperation
    from app.models.base import utc_now

    diagnosis_id = _create_sensor_failure(api_context)
    with api_context['session_factory']() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        provider = MockDeepSeek(_structured_output(diagnosis))
        settings = _deepseek_settings()
        result = GovernedAIInvocation(
            db, diagnosis, settings, call_stage='expired-replay',
        ).complete_json(
            provider, system_prompt='s', user_prompt='u',
        )
        db.scalar(select(AIOperation)).deadline_at = utc_now() - timedelta(hours=1)
        db.commit()
        replay = GovernedAIInvocation(
            db, diagnosis, settings, call_stage='expired-replay',
        ).complete_json(
            provider, system_prompt='s', user_prompt='u',
        )
        assert replay == result and provider.calls == 1
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 1
