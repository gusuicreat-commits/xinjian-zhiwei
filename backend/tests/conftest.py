from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_device_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Device

TEST_DEVICE_ID = "phase2-test-device"
TEST_DEVICE_TOKEN = "phase2-test-token-not-for-production"


@pytest.fixture
def api_context() -> Generator[dict[str, Any], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add(
            Device(
                device_key=TEST_DEVICE_ID,
                display_name="明确标记的 Phase 2 测试设备",
                device_type="test-fixture",
                token_hash=hash_device_token(TEST_DEVICE_TOKEN, iterations=1_000),
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": testing_session,
            "headers": {
                "X-Device-ID": TEST_DEVICE_ID,
                "X-Device-Token": TEST_DEVICE_TOKEN,
            },
        }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
