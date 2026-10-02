from __future__ import annotations

import asyncio
import json
import math
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import anyio
import httpx

from app.core.config import Settings


class AIProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code="PROVIDER_UNKNOWN",
        status_code=None,
        retryable=False,
        retry_after=None,
        outcome_unknown=True,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.outcome_unknown = outcome_unknown


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


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
        response_max_bytes: int = 1048576,
    ) -> None:
        self.provider = provider
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._thinking_enabled = thinking_enabled
        self._response_max_bytes = response_max_bytes

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
        # Retry belongs to the durable governor, including direct callers.
        return self.complete_json_once(system_prompt=system_prompt, user_prompt=user_prompt)

    def complete_json_once(
        self, *, system_prompt: str, user_prompt: str, timeout_seconds: float | None = None
    ) -> AICompletion:
        payload = self.build_request_payload(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._parse_completion(
            self._post_once(
                "/chat/completions",
                payload,
                timeout_seconds=timeout_seconds,
            )
        )

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
        return self._post_once(path, payload)

    def _post_once(
        self, path: str, payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        limit = min(self._timeout_seconds, timeout_seconds or self._timeout_seconds)
        return asyncio.run(self._post_bounded(path, payload, limit))

    async def _post_bounded(self, path, payload, limit):
        deadline = time.monotonic() + limit
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        try:
            with anyio.fail_after(limit):
                async with httpx.AsyncClient(timeout=limit) as client:
                    async with client.stream(
                        "POST", f"{self._base_url}{path}", headers=headers, json=payload
                    ) as response:
                        status = response.status_code
                        if status >= 400:
                            known = status < 500
                            raise AIProviderError(
                                "AI Provider HTTP rejection",
                                code=f"HTTP_{status}",
                                status_code=status,
                                retryable=status == 429,
                                retry_after=retry_after_seconds(
                                    response.headers.get("retry-after")
                                ),
                                outcome_unknown=not known,
                            )
                        encoding = response.headers.get("content-encoding", "identity").lower()
                        if encoding not in {"identity", "gzip", "deflate"}:
                            raise AIProviderError(
                                "Unsupported response encoding", code="RESPONSE_ENCODING"
                            )
                        decoder = (
                            zlib.decompressobj(31 if encoding == "gzip" else 15)
                            if encoding != "identity"
                            else None
                        )
                        body = bytearray()
                        wire_size = 0
                        async for chunk in response.aiter_raw(chunk_size=16384):
                            wire_size += len(chunk)
                            if wire_size > self._response_max_bytes:
                                raise AIProviderError(
                                    "AI response too large", code="RESPONSE_LIMIT"
                                )
                            available = self._response_max_bytes - len(body)
                            decoded = decoder.decompress(chunk, available + 1) if decoder else chunk
                            if len(decoded) > available or (decoder and decoder.unconsumed_tail):
                                raise AIProviderError(
                                    "AI response too large", code="RESPONSE_LIMIT"
                                )
                            body.extend(decoded)
                        if decoder and not decoder.eof:
                            raise AIProviderError(
                                "AI response truncated", code="RESPONSE_TRUNCATED"
                            )
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        result = json.loads(body)
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        if not isinstance(result, dict):
                            raise ValueError()
                        return result
        except AIProviderError:
            raise
        except (
            TimeoutError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ) as exc:
            raise AIProviderError("AI Provider outcome unknown", code="OUTCOME_UNKNOWN") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise AIProviderError(
                "AI Provider not connected", code="NOT_SENT", retryable=True, outcome_unknown=False
            ) from exc
        except (ValueError, zlib.error, RecursionError) as exc:
            raise AIProviderError(
                "AI Provider invalid JSON",
                code="INVALID_RESPONSE",
                retryable=True,
                outcome_unknown=False,
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError("AI Provider transport failed", code="OUTCOME_UNKNOWN") from exc


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
            response_max_bytes=settings.ai_response_max_bytes,
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
        response_max_bytes=settings.ai_response_max_bytes,
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
        response_max_bytes=settings.ai_response_max_bytes,
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
