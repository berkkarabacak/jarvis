from __future__ import annotations

from app.llm.openrouter_attribution import openrouter_attribution_headers

import asyncio
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import httpx

from app.executive.safety import ExecutiveSafetyError, require_public_identifier
from app.executive.telemetry import GenerationTelemetry, GenerationTelemetryError

OPENROUTER_GENERATION_URL = "https://openrouter.ai/api/v1/generation"


@runtime_checkable
class GenerationTelemetryResolver(Protocol):
    """Resolve one safe generation id to provider-accounted scalar metadata."""

    async def resolve(self, generation_id: str) -> GenerationTelemetry: ...


class OpenRouterGenerationClient:
    """Fail-closed adapter for OpenRouter's owner-charge generation endpoint.

    The API key and raw provider response remain inside this adapter. Only a
    strict scalar allowlist crosses into the executive runtime.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 4.0,
        retry_delays_seconds: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5),
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        key = str(api_key or "").strip()
        if (
            not key
            or len(key) > 512
            or any(character.isspace() or ord(character) < 32 for character in key)
        ):
            raise GenerationTelemetryError(
                "OpenRouter generation accounting is unavailable"
            )
        self._api_key = key
        self._timeout_seconds = max(0.1, min(float(timeout_seconds), 10.0))
        delays = tuple(
            max(0.0, min(float(value), 2.0)) for value in retry_delays_seconds
        )
        self._retry_delays = delays[:6] or (0.0,)
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._timeout_seconds)
        )

    async def resolve(self, generation_id: str) -> GenerationTelemetry:
        try:
            safe_id = require_public_identifier(generation_id)
        except ExecutiveSafetyError as exc:
            raise GenerationTelemetryError(
                "generation metadata is unavailable"
            ) from exc

        try:
            return await asyncio.wait_for(
                self._resolve_with_client(safe_id),
                timeout=self._timeout_seconds,
            )
        except (asyncio.TimeoutError, GenerationTelemetryError):
            pass

        raise GenerationTelemetryError("OpenRouter generation metadata is unavailable")

    async def _resolve_with_client(self, safe_id: str) -> GenerationTelemetry:
        async with self._client_factory() as client:
            for attempt, delay in enumerate(self._retry_delays):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await client.get(
                        OPENROUTER_GENERATION_URL,
                        params={"id": safe_id},
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Accept": "application/json",
                            **openrouter_attribution_headers(),
                        },
                    )
                except (httpx.HTTPError, RuntimeError):
                    response = None

                if response is None:
                    if attempt + 1 < len(self._retry_delays):
                        continue
                    break
                if response.status_code == 200:
                    parsed = self._parse_response(response, requested_id=safe_id)
                    if parsed is not None:
                        return parsed
                elif response.status_code not in {404, 429} and not (
                    500 <= response.status_code < 600
                ):
                    break
                if attempt + 1 >= len(self._retry_delays):
                    break
        raise GenerationTelemetryError("OpenRouter generation metadata is unavailable")

    @staticmethod
    def _parse_response(
        response: httpx.Response,
        *,
        requested_id: str,
    ) -> GenerationTelemetry | None:
        try:
            payload: Any = response.json()
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        returned_id = data.get("id")
        if returned_id != requested_id:
            return None
        input_tokens = data.get("native_tokens_prompt")
        output_tokens = data.get("native_tokens_completion")
        if input_tokens is None:
            input_tokens = data.get("tokens_prompt")
        if output_tokens is None:
            output_tokens = data.get("tokens_completion")
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool):
            return None
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            return None
        try:
            return GenerationTelemetry.build(
                generation_id=requested_id,
                selected_model=data.get("model"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                actual_cost_usd=data.get("total_cost"),
            )
        except (ExecutiveSafetyError, GenerationTelemetryError):
            return None
