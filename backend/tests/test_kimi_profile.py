"""Official Kimi K2.6 transport contract, all configured client entry points."""

import pytest
from pydantic import ValidationError

from app.ai.clients import build_ai_client, build_cloud_ai_client, build_local_ai_client
from app.core.config import Settings


def settings(route="primary", **override):
    args = dict(_env_file=None, ai_enabled=True, ai_api_key=None)
    prefix = "ai" if route == "primary" else "ai_" + route
    args.update(
        {
            prefix + "_provider": "kimi",
            prefix + "_base_url": "https://api.moonshot.cn/v1",
            prefix + "_model": "kimi-k2.6",
            prefix + "_api_key": "synthetic-key",
        }
    )
    if route != "primary":
        args[prefix + "_enabled"] = True
    args.update(override)
    return Settings(**args)


@pytest.mark.parametrize(
    "route,factory",
    [
        ("primary", build_ai_client),
        ("local", build_local_ai_client),
        ("cloud", build_cloud_ai_client),
    ],
)
def test_kimi_request_contract(route, factory):
    client = factory(settings(route))
    body = client.build_request_payload(system_prompt="Return JSON", user_prompt="Synthetic")
    assert body["model"] == "kimi-k2.6"
    assert body.get("thinking") == {"type": "disabled"}
    assert "temperature" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 1000
    assert "synthetic-key" not in str(body)


@pytest.mark.parametrize("route", ["primary", "local", "cloud"])
@pytest.mark.parametrize(
    "field,value", [("base_url", "https://untrusted.invalid/v1"), ("model", "kimi-k3")]
)
def test_kimi_rejects_wrong_destination_or_model(route, field, value):
    prefix = "ai" if route == "primary" else "ai_" + route
    with pytest.raises(ValidationError):
        settings(route, **{prefix + "_" + field: value})


def test_kimi_nonthinking_profile():
    with pytest.raises(ValidationError):
        settings(ai_thinking_enabled=True)


def test_kimi_no_key_or_disabled_never_builds_live_client():
    assert not build_ai_client(settings(ai_api_key=None)).configured
    assert not build_ai_client(settings(ai_enabled=False)).configured


def test_existing_deepseek_contract_is_preserved():
    s = Settings(_env_file=None, ai_enabled=True, ai_api_key="synthetic-key")
    body = build_ai_client(s).build_request_payload(system_prompt="JSON", user_prompt="synthetic")
    assert body["temperature"] == 0
    assert body["thinking"] == {"type": "disabled"}
