"""Student final authorization and session close share one lock order."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from test_migration_r2 import migration_db as _migration_db
from test_shared_authorization_postgres import seed
from test_student_write_authorization import account_identity

from app.models import Device, ExperimentSession, User
from app.services.auth import AuthorizationDenied
from app.services.experiment_sessions import end_session
from app.services.student_authorization import authorize_student_actor

migration_db = _migration_db


@pytest.mark.parametrize('winner', ['authorization', 'close'])
def test_student_authorization_and_close_have_no_lock_cycle(migration_db, winner):
    engine, migrate = migration_db
    migrate('upgrade', 'head')
    factory = sessionmaker(engine, expire_on_commit=False)
    seed(factory)
    with factory() as db:
        identity = account_identity(db)
        version = db.get(ExperimentSession, identity.session_id).version_no
    waiting = Event()

    def close():
        with factory() as db:
            db.execute(text("SET lock_timeout = '3s'"))
            user = db.get(User, identity.account.user_id)
            user._actor_context = identity.account
            waiting.set()
            return end_session(db, user, session_id=identity.session_id, request_id=uuid4(),
                               expected_version=version, reason='completed')

    def authorize():
        with factory() as db:
            db.execute(text("SET lock_timeout = '3s'"))
            waiting.set()
            try:
                authorize_student_actor(db, identity, identity.device_id, identity.session_id)
                db.commit()
                return 'authorized'
            except AuthorizationDenied:
                db.rollback()
                return 'denied'

    with ThreadPoolExecutor(max_workers=1) as executor, factory() as owner:
        owner.execute(text("SET lock_timeout = '3s'"))
        if winner == 'authorization':
            authorize_student_actor(owner, identity, identity.device_id, identity.session_id)
            future = executor.submit(close)
            assert waiting.wait(2)
            owner.commit()
            assert future.result(timeout=5)['status'] == 'completed'
        else:
            owner.scalar(select(User).where(User.id == identity.account.user_id).with_for_update())
            owner.scalar(select(Device).where(Device.id == identity.device_id).with_for_update())
            session = owner.get(ExperimentSession, identity.session_id)
            session.status = 'completed'
            future = executor.submit(authorize)
            assert waiting.wait(2)
            owner.commit()
            assert future.result(timeout=5) == 'denied'
