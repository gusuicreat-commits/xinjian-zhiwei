from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AICompletion:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIClient(Protocol):
    provider: str
    model: str
    configured: bool

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion: ...


class DisabledAIClient:
    provider = "unconfigured"
    model = "unconfigured"
    configured = False

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        del system_prompt, user_prompt
        raise AIProviderError("AI Provider is not configured")


class OpenAICompatibleClient:
    configured = True

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
        max_output_tokens: int | None = None,
        thinking_enabled: bool | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._thinking_enabled = thinking_enabled

    def build_request_payload(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        if self._max_output_tokens is not None:
            payload["max_tokens"] = self._max_output_tokens
        if self._thinking_enabled is not None:
            payload["thinking"] = {"type": "enabled" if self._thinking_enabled else "disabled"}
        return payload

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        payload = self.build_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        response = self._post("/chat/completions", payload)
        return self._parse_completion(response)

    def complete_json_once(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        """Issue one physical request; the governed caller owns retry quotas."""
        payload = self.build_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return self._parse_completion(self._post_once("/chat/completions", payload))

    @staticmethod
    def _parse_completion(response: dict[str, Any]) -> AICompletion:
        try:
            content = response["choices"][0]["message"]["content"]
            usage = response.get("usage")
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("AI Provider returned an unsupported response shape") from exc
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError("AI Provider returned empty content")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise AIProviderError("AI Provider returned unsupported usage metadata")
        return AICompletion(
            content=content,
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(self._max_retries + 1):
            try:
                return self._post_once(path, payload)
            except AIProviderError as exc:
                last_error = exc
        raise AIProviderError("AI Provider request failed after configured retries") from last_error

    def _post_once(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(f"{self._base_url}{path}", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError("AI Provider request failed") from exc
        if not isinstance(body, dict):
            raise AIProviderError("Provider response must be a JSON object")
        return body


def build_ai_client(settings: Settings) -> AIClient:
    if not settings.ai_configured:
        return DisabledAIClient()
    if settings.production_ai_configured:
        return OpenAICompatibleClient(
            provider=settings.ai_provider or "",
            base_url=settings.ai_base_url or "",
            model=settings.ai_model or "",
            api_key=settings.ai_api_key or "",
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            max_output_tokens=settings.ai_output_token_limit,
            thinking_enabled=(
                settings.ai_thinking_enabled if settings.ai_provider == "deepseek" else None
            ),
        )
    if settings.local_ai_configured:
        return build_local_ai_client(settings)
    if settings.cloud_ai_configured:
        return build_cloud_ai_client(settings)
    return DisabledAIClient()


def build_local_ai_client(settings: Settings) -> AIClient:
    if not settings.local_ai_configured:
        return DisabledAIClient()
    return OpenAICompatibleClient(
        provider=settings.ai_local_provider or "",
        base_url=settings.ai_local_base_url or "",
        model=settings.ai_local_model or "",
        api_key=settings.ai_local_api_key or "",
        timeout_seconds=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        max_output_tokens=settings.ai_output_token_limit,
    )


def build_cloud_ai_client(settings: Settings) -> AIClient:
    if not settings.cloud_ai_configured:
        return DisabledAIClient()
    return OpenAICompatibleClient(
        provider=settings.ai_cloud_provider or "",
        base_url=settings.ai_cloud_base_url or "",
        model=settings.ai_cloud_model or "",
        api_key=settings.ai_cloud_api_key or "",
        timeout_seconds=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        max_output_tokens=settings.ai_output_token_limit,
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()))
        or value < 0
    ):
        raise AIProviderError("AI Provider returned invalid token usage")
    return int(value)
