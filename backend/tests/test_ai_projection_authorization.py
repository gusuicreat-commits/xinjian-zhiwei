from copy import deepcopy

import pytest
from sqlalchemy import select
from test_ai_diagnosis import FakeAIClient, _create_diagnosis
from test_student_write_authorization import account_identity, revoke

from app.core.config import Settings
from app.models import AICallRecord, Device, DiagnosisResult
from app.models.ai_usage_reservation import AIUsageReservation
from app.services.ai_diagnosis import explain_diagnosis
from app.services.auth import AuthorizationDenied


@pytest.mark.parametrize('revocation', ['session', 'role'])
def test_provider_revocation_keeps_actual_cost_but_not_business_projection(api_context, revocation):
    diagnosis_id = _create_diagnosis(api_context)
    with api_context['session_factory']() as db:
        identity = account_identity(db)
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        before = deepcopy(diagnosis.ai_enhancement)
        provider = FakeAIClient({
            'error_type': diagnosis.matched_rules[0]['error_type'], 'summary': 'synthetic',
            'steps': [], 'hint_level': 1, 'need_teacher_help': False,
        })
        original = provider.complete_json

        def revoked_provider(**kwargs):
            with api_context['session_factory']() as revoked_db:
                revoke(revoked_db, identity, revocation)
            return original(**kwargs)

        provider.complete_json = revoked_provider
        with pytest.raises(AuthorizationDenied):
            explain_diagnosis(
                db, db.get(Device, identity.device_id), diagnosis,
                Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                         ai_input_cost_per_1k_tokens=0.01, ai_output_cost_per_1k_tokens=0.02),
                student_actor=identity, ai_client=provider,
            )
        db.rollback()
        db.refresh(diagnosis)
        assert diagnosis.ai_enhancement == before
        audit = db.scalar(select(AICallRecord).where(
            AICallRecord.diagnosis_result_id == diagnosis.id,
        ))
        assert audit is not None and audit.status == 'succeeded'
        assert (audit.input_tokens, audit.output_tokens) == (10, 20)
        usage = db.scalar(select(AIUsageReservation).where(
            AIUsageReservation.diagnosis_result_id == diagnosis.id,
        ))
        assert usage is not None and usage.status == 'succeeded'
        assert usage.input_tokens == 10 and usage.output_tokens == 20
        assert usage.accounted_cost > 0
        assert provider.calls == 1
