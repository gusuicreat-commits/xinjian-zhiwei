"""Two real connections exercise receipt/sequence/rate admission together."""

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, local
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_device_protocol_v1 import _batch

from app.core.config import get_settings
from app.evaluation.workflow_environment import workflow_environment
from app.models import DeviceHeartbeat, DeviceLog, IngestionRequest, SensorReading


@pytest.mark.parametrize("mode", ["replay", "payload_conflict", "sequence", "rate"])
def test_concurrent_ingestion_contract(mode):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        settings = env.app.dependency_overrides[get_settings]()
        settings.device_ingest_requests_per_minute = 1 if mode == "rate" else 100
        one = _batch()
        two = (
            deepcopy(one)
            if mode in {"replay", "payload_conflict"}
            else _batch(sequence_no=2 if mode == "rate" else 1)
        )
        if mode == "payload_conflict":
            two["records"][1]["payload"]["value"] = 43
        gate, worker = Barrier(2), local()

        def synchronize(conn, cursor, statement, parameters, context, many):
            boundary = ("FROM devices" in statement and "FOR UPDATE" in statement) or (
                statement.startswith("INSERT INTO ingestion_requests ")
            )
            if boundary and not getattr(worker, "entered", False):
                worker.entered = True
                gate.wait(timeout=15)

        event.listen(env.engine, "before_cursor_execute", synchronize)

        def send(payload):
            with TestClient(env.app, raise_server_exceptions=False) as client:
                response = client.post("/api/v1/device/ingest", headers=env.headers, json=payload)
                return response.status_code, response.json()

        try:
            with patch("app.api.v1.routes.device.get_settings", return_value=settings):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(send, [one, two]))
        finally:
            event.remove(env.engine, "before_cursor_execute", synchronize)
        expected = [201, 201] if mode == "replay" else [201, 429 if mode == "rate" else 409]
        assert sorted(status for status, _ in results) == expected, results
        if mode == "replay":
            assert sorted(body["idempotentReplay"] for _, body in results) == [False, True]
            assert results[0][1]["records"] == results[1][1]["records"]
        with env.sessions() as db:
            for model in (IngestionRequest, DeviceHeartbeat, DeviceLog, SensorReading):
                assert db.scalar(select(func.count()).select_from(model)) == 1
        # A replay remains free even when the one-request budget is used up.
        accepted_payload = one if results[0][0] == 201 else two
        with patch("app.api.v1.routes.device.get_settings", return_value=settings):
            status, body = send(accepted_payload)
        assert status == 201 and body["idempotentReplay"]


@pytest.mark.parametrize("revocation", ["disabled", "rotated_token"])
@pytest.mark.parametrize("endpoint", ["ingest", "logs", "readings", "heartbeat"])
def test_device_permission_is_rechecked_after_waiting_for_lock(revocation, endpoint):
    from threading import Event

    from app.models import Device

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        waiting = Event()

        def observe(conn, cursor, statement, parameters, context, many):
            if "FROM devices" in statement and "FOR UPDATE" in statement:
                waiting.set()

        def send():
            with TestClient(env.app, raise_server_exceptions=False) as client:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).isoformat()
                payloads = {
                    "ingest": _batch(),
                    "logs": {
                        "occurred_at": now,
                        "level": "error",
                        "message": "test",
                        "is_test_data": True,
                    },
                    "readings": {
                        "observed_at": now,
                        "sensor_type": "test",
                        "metric_key": "test",
                        "value": 1,
                        "is_test_data": True,
                    },
                    "heartbeat": {"observed_at": now, "is_test_data": True},
                }
                return client.post(
                    "/api/v1/device/" + endpoint, headers=env.headers, json=payloads[endpoint]
                )

        with env.sessions() as owner:
            device = owner.scalar(select(Device).with_for_update())
            event.listen(env.engine, "before_cursor_execute", observe)
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(send)
                    try:
                        assert waiting.wait(10), "request never reached transaction admission"
                        if revocation == "disabled":
                            device.is_active = False
                        else:
                            device.token_hash = "revoked-test-token-hash"
                    finally:
                        owner.commit()  # Always release before joining the worker.
                    response = future.result(timeout=10)
            finally:
                event.remove(env.engine, "before_cursor_execute", observe)
        assert response.status_code == 401, response.text
        with env.sessions() as db:
            assert db.scalar(select(func.count()).select_from(IngestionRequest)) == 0


def test_busy_device_does_not_block_another_device():
    from threading import Event

    from app.core.security import hash_device_token
    from app.models import Device

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        with env.sessions() as db:
            original = db.scalar(select(Device)).id
            db.add(
                Device(
                    device_key="second-test-device",
                    display_name="Second test device",
                    token_hash=hash_device_token("second-test-token", iterations=1000),
                )
            )
            db.commit()
        waiting = Event()

        def observe(conn, cursor, statement, parameters, context, many):
            if "FROM devices" in statement and "FOR UPDATE" in statement:
                waiting.set()

        def send(headers):
            with TestClient(env.app, raise_server_exceptions=False) as client:
                return client.post("/api/v1/device/ingest", headers=headers, json=_batch())

        with env.sessions() as owner:
            owner.scalar(select(Device).where(Device.id == original).with_for_update())
            event.listen(env.engine, "before_cursor_execute", observe)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    blocked = pool.submit(send, env.headers)
                    try:
                        assert waiting.wait(10)
                        independent = pool.submit(
                            send,
                            {
                                "X-Device-ID": "second-test-device",
                                "X-Device-Token": "second-test-token",
                            },
                        )
                        assert independent.result(timeout=10).status_code == 201
                        assert not blocked.done()
                    finally:
                        owner.rollback()
                    assert blocked.result(timeout=10).status_code == 201
            finally:
                event.remove(env.engine, "before_cursor_execute", observe)


def test_mixed_legacy_and_batch_compete_for_one_shared_slot():
    from datetime import datetime, timezone

    from app.models.ingestion_request import LegacyIngestionAdmission

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        settings = env.app.dependency_overrides[get_settings]()
        settings.device_ingest_requests_per_minute = 1
        gate, worker = Barrier(2), local()

        def synchronize(conn, cursor, statement, parameters, context, many):
            if (
                "FROM devices" in statement
                and "FOR UPDATE" in statement
                and not getattr(worker, "entered", False)
            ):
                worker.entered = True
                gate.wait(timeout=15)

        event.listen(env.engine, "before_cursor_execute", synchronize)

        def send(endpoint):
            payload = (
                _batch()
                if endpoint == "ingest"
                else {"observed_at": datetime.now(timezone.utc).isoformat(), "is_test_data": True}
            )
            with TestClient(env.app, raise_server_exceptions=False) as client:
                return client.post(
                    "/api/v1/device/" + endpoint, headers=env.headers, json=payload
                ).status_code

        try:
            with patch("app.api.v1.routes.device.get_settings", return_value=settings):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    assert sorted(pool.map(send, ["ingest", "heartbeat"])) == [201, 429]
        finally:
            event.remove(env.engine, "before_cursor_execute", synchronize)
        with env.sessions() as db:
            assert (
                sum(
                    db.scalar(select(func.count(model.id)))
                    for model in (IngestionRequest, LegacyIngestionAdmission)
                )
                == 1
            )
