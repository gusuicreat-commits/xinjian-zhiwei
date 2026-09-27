from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from test_device_protocol_v1 import _batch

from app.core.config import get_settings


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("logs", {"level": "error", "message": "test", "sensor_snapshot": {}}),
        ("readings", {"sensor_type": "test", "metric_key": "test", "value": 1, "metadata": {}}),
        ("heartbeat", {"metadata": {}}),
    ],
)
def test_legacy_body_and_shared_rate_limits(api_context, endpoint, payload):
    payload = {
        **payload,
        "is_test_data": True,
        "occurred_at" if endpoint == "logs" else "observed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
    settings = get_settings().model_copy(update={"device_ingest_requests_per_minute": 1})
    with patch("app.api.v1.routes.device.get_settings", return_value=settings):
        response = api_context["client"].post(
            "/api/v1/device/" + endpoint, headers=api_context["headers"], json=payload
        )
        assert response.status_code == 201
        response = api_context["client"].post(
            "/api/v1/device/ingest", headers=api_context["headers"], json=_batch()
        )
        assert response.status_code == 429
    key = "sensor_snapshot" if endpoint == "logs" else "metadata"
    payload[key] = {"oversized": "x" * 300000}
    response = api_context["client"].post(
        "/api/v1/device/" + endpoint, headers=api_context["headers"], json=payload
    )
    assert response.status_code == 413


def test_streamed_body_limit_does_not_trust_content_length(api_context):
    def chunks():
        yield b'{"padding":"'
        yield b"x" * 270000
        yield b'"}'

    response = api_context["client"].post(
        "/api/v1/device/heartbeat",
        headers={
            **api_context["headers"],
            "content-type": "application/json",
            "content-length": "1",
        },
        content=chunks(),
    )
    assert response.status_code == 413
