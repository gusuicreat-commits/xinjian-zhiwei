"""Provider I/O holds no authorization rows; revocation preserves actual usage."""
from copy import deepcopy

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from test_ai_diagnosis import FakeAIClient
from test_migration_r2 import migration_db as _migration_db
from test_shared_authorization_postgres import seed
from test_student_write_authorization import account_identity, revoke

from app.core.config import Settings
from app.models import AICallRecord, Device, DiagnosisResult
from app.models.ai_usage_reservation import AIUsageReservation
from app.services.ai_diagnosis import explain_diagnosis
from app.services.auth import AuthorizationDenied

migration_db = _migration_db


def test_provider_has_no_auth_lock_and_revocation_preserves_usage(migration_db):
    engine, migrate = migration_db
    migrate('upgrade', 'head')
    factory = sessionmaker(engine, expire_on_commit=False)
    seed(factory)
    with factory() as db:
        identity = account_identity(db)
        diagnosis = db.scalar(select(DiagnosisResult))
        before = deepcopy(diagnosis.ai_enhancement)
        provider = FakeAIClient({
            'error_type': (diagnosis.matched_rules[0]['error_type']
                           if diagnosis.matched_rules else 'UNCLASSIFIED_ANOMALY'),
            'summary': 'synthetic',
                                 'steps': [], 'hint_level': 1, 'need_teacher_help': False})
        original = provider.complete_json

        def revoked_provider(**kwargs):
            with factory() as revoked_db:
                revoked_db.execute(text("SET lock_timeout = '1s'"))
                revoke(revoked_db, identity, 'session')
            return original(**kwargs)

        provider.complete_json = revoked_provider
        with pytest.raises(AuthorizationDenied):
            explain_diagnosis(
                db, db.get(Device, identity.device_id), diagnosis,
                Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                         ai_max_retries=0,
                         ai_input_cost_per_1k_tokens=0.01, ai_output_cost_per_1k_tokens=0.02),
                student_actor=identity, ai_client=provider, user_question='解释当前证据不足',
            )
        db.rollback()
        db.refresh(diagnosis)
        assert diagnosis.ai_enhancement == before
        assert provider.calls == 1
        assert db.scalar(select(AICallRecord).where(
            AICallRecord.diagnosis_result_id == diagnosis.id,
            AICallRecord.input_tokens == 10,
        )) is not None
        usage = db.scalar(select(AIUsageReservation).where(
            AIUsageReservation.diagnosis_result_id == diagnosis.id,
        ))
        assert usage.status == 'succeeded' and usage.accounted_cost > 0
