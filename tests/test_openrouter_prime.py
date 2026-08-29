from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.executive.adapters.openrouter_prime import (
    OpenRouterPrimeAgent,
    build_openrouter_prime_agent,
)
from app.executive.adapters.prime import PrimeRuntimeError, PrimeUnavailableError

SAFE_TEST_KEY = "SYNTHETIC_SAFE_TEST_KEY"


def _sse(*events: str) -> bytes:
    return ("".join(f"data: {event}\n\n" for event in events) + "data: [DONE]\n\n").encode()


def _agent(handler, **kwargs) -> OpenRouterPrimeAgent:
    transport = httpx.MockTransport(handler)
    return OpenRouterPrimeAgent(
        api_key=SAFE_TEST_KEY,
        client_factory=lambda: httpx.AsyncClient(transport=transport),
        **kwargs,
    )


def _stream_response(*, text: str = "hello", cost: float = 0.0021) -> httpx.Response:
    body = _sse(
        '{"id":"gen-abc123","model":"openai/gpt-5-nano",'
        '"choices":[{"delta":{"content":"' + text + '"}}]}',
        '{"id":"gen-abc123","model":"openai/gpt-5-nano","choices":[],'
        '"usage":{"prompt_tokens":40,"completion_tokens":10,"total_tokens":50,'
        '"cost":' + str(cost) + "}}",
    )
    return httpx.Response(200, content=body)


@pytest.mark.asyncio
async def test_send_message_returns_streamed_receipt_telemetry():
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.content)
        return _stream_response()

    agent = _agent(handler)
    session = await agent.start_session(role_name="executive")
    result = await agent.send_message(session.session_id, message="plan the mission")

    assert result.text == "hello"
    assert result.generation is not None
    telemetry = result.generation
    # Only the authoritative streamed receipt may settle a generation.
    assert telemetry.source == "openrouter_stream"
    assert telemetry.generation_id == "gen-abc123"
    assert telemetry.selected_model == "openai/gpt-5-nano"
    assert telemetry.input_tokens == 40
    assert telemetry.output_tokens == 10
    assert telemetry.total_tokens == 50
    assert telemetry.actual_cost_usd == Decimal("0.0021")

    payload = seen["payload"]
    assert payload["stream"] is True
    assert payload["usage"] == {"include": True}
    # Bounded policy ceilings must reach the provider, not just the ledger.
    assert payload["max_tokens"] == 600
    assert payload["provider"]["allow_fallbacks"] is False
    assert payload["provider"]["sort"] == "price"
    assert payload["provider"]["max_price"]["prompt"] == 1.0
    assert payload["provider"]["max_price"]["completion"] == 5.0


@pytest.mark.asyncio
async def test_missing_usage_receipt_fails_closed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                '{"id":"gen-no-usage","model":"openai/gpt-5-nano",'
                '"choices":[{"delta":{"content":"text without a receipt"}}]}'
            ),
        )

    agent = _agent(handler)
    session = await agent.start_session(role_name="executive")
    # An unsettled generation must never look free to the ledger.
    with pytest.raises(PrimeRuntimeError):
        await agent.send_message(session.session_id, message="hi")


@pytest.mark.asyncio
async def test_rejected_credentials_surface_as_unavailable_without_leaking():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": SAFE_TEST_KEY}})

    agent = _agent(handler)
    session = await agent.start_session(role_name="executive")
    with pytest.raises(PrimeUnavailableError) as excinfo:
        await agent.send_message(session.session_id, message="hi")
    assert SAFE_TEST_KEY not in str(excinfo.value)


@pytest.mark.asyncio
async def test_empty_assistant_text_is_an_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                '{"id":"gen-empty","model":"m","choices":[],'
                '"usage":{"prompt_tokens":1,"completion_tokens":0,'
                '"total_tokens":1,"cost":0.0001}}'
            ),
        )

    agent = _agent(handler)
    session = await agent.start_session(role_name="executive")
    with pytest.raises(PrimeRuntimeError):
        await agent.send_message(session.session_id, message="hi")


@pytest.mark.asyncio
async def test_health_is_live_but_not_rpc_and_hides_credentials():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _stream_response()

    agent = _agent(handler)
    health = await agent.health()
    assert health["live"] is True
    assert health["available"] is True
    assert health["credentials_configured"] is True
    # This adapter is not the pinned external binary path.
    assert health["rpc"] is False
    assert health["prime_binary"] is False
    assert SAFE_TEST_KEY not in repr(health)


@pytest.mark.asyncio
async def test_unknown_or_stopped_session_is_rejected():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _stream_response()

    agent = _agent(handler)
    with pytest.raises(PrimeUnavailableError):
        await agent.send_message("or-does-not-exist", message="hi")

    session = await agent.start_session(role_name="executive")
    await agent.stop_session(session.session_id, reason="stopped")
    with pytest.raises(PrimeUnavailableError):
        await agent.send_message(session.session_id, message="hi")


def test_builder_returns_none_without_a_key():
    assert build_openrouter_prime_agent(api_key="") is None
    assert build_openrouter_prime_agent(api_key="   ") is None
    assert build_openrouter_prime_agent(api_key=SAFE_TEST_KEY) is not None


def test_adapter_selection_prefers_openrouter_then_null(monkeypatch):
    from app.config import Settings
    from app.main import build_executive_prime_agent

    monkeypatch.delenv("PRIME_AGENT_ENABLED", raising=False)
    monkeypatch.delenv("EXECUTIVE_PRIME_ADAPTER", raising=False)

    with_key = Settings(API_SECRET="x", OPENROUTER_API_KEY=SAFE_TEST_KEY)
    assert build_executive_prime_agent(with_key).name == "openrouter-prime"

    without_key = Settings(API_SECRET="x", OPENROUTER_API_KEY="")
    assert build_executive_prime_agent(without_key).name == "null"

    # An explicit pin always wins over auto-selection.
    monkeypatch.setenv("EXECUTIVE_PRIME_ADAPTER", "null")
    assert build_executive_prime_agent(with_key).name == "null"


@pytest.mark.asyncio
async def test_settings_put_rebuilds_and_retires_the_executive_adapter(
    tmp_path, monkeypatch
):
    """Rotating the OpenRouter key must not leave public chat on the old one."""
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "rotate.db"))
    monkeypatch.setenv("API_SECRET", "rotation-test-secret-at-least-32-bytes-long")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", SAFE_TEST_KEY)
    monkeypatch.delenv("PRIME_AGENT_ENABLED", raising=False)
    monkeypatch.delenv("EXECUTIVE_PRIME_ADAPTER", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    auth = {"X-Api-Key": "rotation-test-secret-at-least-32-bytes-long"}
    async with app.router.lifespan_context(app):
        runtime = app.state.executive_runtime
        assert runtime.prime.name == "openrouter-prime"
        original = runtime.prime

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Clearing the key must retire the live adapter, not keep serving on it.
            r = await ac.put(
                "/api/settings/llm", headers=auth, json={"openrouter_api_key": ""}
            )
            assert r.status_code == 200, r.text
            assert r.json()["executive_adapter_rebuilt"] is True
            assert r.json()["openrouter_api_key_set"] is False
            assert runtime.prime is not original
            assert runtime.prime.name == "null"

            # Supplying a key again brings the live adapter back.
            r = await ac.put(
                "/api/settings/llm",
                headers=auth,
                json={"openrouter_api_key": SAFE_TEST_KEY},
            )
            assert r.status_code == 200, r.text
            assert runtime.prime.name == "openrouter-prime"
    get_settings.cache_clear()
