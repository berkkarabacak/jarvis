from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app.executive.adapters.openrouter_generation import (
    OPENROUTER_GENERATION_URL,
    OpenRouterGenerationClient,
)
from app.executive.telemetry import GenerationTelemetryError


@pytest.mark.asyncio
async def test_openrouter_generation_uses_owner_cost_and_native_tokens_only():
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["id"] = request.url.params["id"]
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "gen-safe-1",
                    "model": "openai/gpt-5-nano",
                    "native_tokens_prompt": 101,
                    "native_tokens_completion": 22,
                    "tokens_prompt": 999,
                    "tokens_completion": 999,
                    "total_cost": "0.0012345",
                    "upstream_inference_cost": "999.99",
                    "content": "SYNTHETIC_PRIVATE_RESPONSE_BODY",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterGenerationClient(
        api_key="SYNTHETIC_SAFE_TEST_KEY",
        client_factory=lambda: httpx.AsyncClient(transport=transport),
    )
    telemetry = await client.resolve("gen-safe-1")

    assert seen == {
        "path": "/api/v1/generation",
        "id": "gen-safe-1",
        "authorization": "Bearer SYNTHETIC_SAFE_TEST_KEY",
    }
    assert str(httpx.URL(OPENROUTER_GENERATION_URL).path) == "/api/v1/generation"
    assert telemetry.input_tokens == 101
    assert telemetry.output_tokens == 22
    assert telemetry.total_tokens == 123
    assert telemetry.actual_cost_usd == telemetry.actual_cost_usd.__class__("0.0012345")
    serialized = json.dumps(telemetry.to_dict())
    assert "SYNTHETIC_PRIVATE_RESPONSE_BODY" not in serialized
    assert "999.99" not in serialized
    assert "SYNTHETIC_SAFE_TEST_KEY" not in repr(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_id", [None, "gen-unrelated"])
async def test_generation_metadata_requires_exact_returned_id_and_hides_raw_body(
    returned_id,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": returned_id,
                    "model": "openai/gpt-5-nano",
                    "native_tokens_prompt": 1,
                    "native_tokens_completion": 1,
                    "total_cost": "0.001",
                    "content": "Bearer SYNTHETIC_PRIVATE_PROVIDER_BODY",
                }
            },
        )

    client = OpenRouterGenerationClient(
        api_key="SYNTHETIC_SAFE_TEST_KEY",
        retry_delays_seconds=(0.0,),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )
    with pytest.raises(GenerationTelemetryError) as caught:
        await client.resolve("gen-expected")
    assert str(caught.value) == "OpenRouter generation metadata is unavailable"
    assert "SYNTHETIC" not in str(caught.value)


@pytest.mark.asyncio
async def test_generation_retry_has_one_total_deadline():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        await asyncio.sleep(0.2)
        return httpx.Response(404, json={"error": "SYNTHETIC_PRIVATE_ERROR"})

    client = OpenRouterGenerationClient(
        api_key="SYNTHETIC_SAFE_TEST_KEY",
        timeout_seconds=0.03,
        retry_delays_seconds=(0.0, 0.0, 0.0, 0.0),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )
    started = time.monotonic()
    with pytest.raises(GenerationTelemetryError):
        await client.resolve("gen-timeout")
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    assert calls == 1


@pytest.mark.parametrize(
    "api_key",
    ["", "has whitespace", "line\nbreak", "x" * 513],
)
def test_generation_client_rejects_unsafe_header_keys(api_key):
    with pytest.raises(
        GenerationTelemetryError,
        match="generation accounting is unavailable",
    ):
        OpenRouterGenerationClient(api_key=api_key)
