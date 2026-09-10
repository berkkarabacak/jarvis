"""PR0 spike: OpenAI Agents API thin client (issue #26).

Mocked tests always run in CI. The live test is skipped unless both
``JARVIS_AGENTS_API_LIVE=1`` and ``OPENAI_API_KEY`` are set.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.jarvis.agents_api import (
    AGENTS_BETA_HEADER,
    DEFAULT_MAX_CONCURRENT_SUBAGENTS,
    LIVE_FLAG_ENV,
    AgentsApiClient,
    AgentsApiError,
    agents_api_live_enabled,
    build_create_session_body,
    cancel_event,
    cap_max_concurrent_subagents,
    collect_notable_events,
    consume_until_turn_end,
    input_message_event,
    is_coordinator_turn_end,
    iter_sse_events,
    session_id_from_payload,
)

TEST_KEY = "sk-test-agents-api-not-a-real-key"


def _client(handler) -> AgentsApiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.openai.com/v1")
    return AgentsApiClient(api_key=TEST_KEY, client=http)


def test_build_create_session_body_spike_defaults():
    body = build_create_session_body(input="hello", stream=True)
    assert body["environment"] == {"type": "none"}
    assert body["agent"]["multi_agent"]["enabled"] is True
    assert body["agent"]["multi_agent"]["max_concurrent_subagents"] == 4
    assert body["agent"]["model"]
    assert body["input"] == "hello"
    assert body["stream"] is True


def test_cap_max_concurrent_subagents_defaults_and_ceiling():
    assert cap_max_concurrent_subagents() == DEFAULT_MAX_CONCURRENT_SUBAGENTS
    assert cap_max_concurrent_subagents(2) == 2
    assert cap_max_concurrent_subagents(99) == 4
    with pytest.raises(ValueError):
        cap_max_concurrent_subagents(0)


def test_create_session_sends_beta_header_env_none_and_cap_four():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["beta"] = request.headers.get("OpenAI-Beta")
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"id": "sess_mock_1", "object": "agent.session", "status": "in_progress"},
        )

    result = _client(handler).create_session(input="Reply with ok.")
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/agents/sessions"
    assert seen["beta"] == AGENTS_BETA_HEADER
    assert seen["authorization"] == f"Bearer {TEST_KEY}"
    body = seen["body"]
    assert body["environment"] == {"type": "none"}
    assert body["agent"]["multi_agent"]["enabled"] is True
    assert body["agent"]["multi_agent"]["max_concurrent_subagents"] == 4
    assert result.session_id == "sess_mock_1"
    assert result.payload["id"] == "sess_mock_1"
    assert TEST_KEY not in json.dumps(result.payload)


def test_create_session_stream_collects_notable_events():
    sse = (
        "event: agent.session.created\n"
        'data: {"type":"agent.session.created","session_id":"sess_stream","session":{"id":"sess_stream"}}\n'
        "\n"
        "event: agent.session.subagent.created\n"
        'data: {"type":"agent.session.subagent.created","subagent_id":"sa_1"}\n'
        "\n"
        "event: agent.session.turn.item.added\n"
        'data: {"type":"agent.session.turn.item.added","item":{"type":"create_subagent_call"}}\n'
        "\n"
        "event: agent.session.turn.item.done\n"
        'data: {"type":"agent.session.turn.item.done","item":{"type":"wait_for_subagents_call"}}\n'
        "\n"
        "event: agent.session.turn.completed\n"
        'data: {"type":"agent.session.turn.completed","turn":{"subagent_id":null}}\n'
        "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["stream"] is True
        assert request.headers.get("Accept") == "text/event-stream"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse,
        )

    result = _client(handler).create_session(input="Split two facts.", stream=True)
    assert result.session_id == "sess_stream"
    types = [event["type"] for event in result.events]
    assert "agent.session.subagent.created" in types
    notable_types = [event["type"] for event in result.notable]
    assert "agent.session.subagent.created" in notable_types
    assert "agent.session.turn.completed" in notable_types
    item_types = [
        (event.get("item") or {}).get("type")
        for event in result.notable
        if (event.get("item") or {}).get("type")
    ]
    assert "create_subagent_call" in item_types
    assert "wait_for_subagents_call" in item_types


def test_post_events_continue_and_cancel():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "beta": request.headers.get("OpenAI-Beta"),
                "body": json.loads(request.content.decode()) if request.content else None,
            }
        )
        return httpx.Response(200, json={"ok": True})

    api = _client(handler)
    api.send_message("sess_abc", "continue")
    api.cancel_turn("sess_abc")
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/v1/agents/sessions/sess_abc/events"
    assert calls[0]["beta"] == AGENTS_BETA_HEADER
    assert calls[0]["body"]["events"][0]["type"] == "agent.session.input.message"
    assert calls[1]["body"]["events"] == [cancel_event()]


def test_delete_session():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["beta"] = request.headers.get("OpenAI-Beta")
        return httpx.Response(
            200,
            json={"id": "sess_del", "object": "agent.session.deleted", "deleted": True},
        )

    result = _client(handler).delete_session("sess_del")
    assert seen == {
        "method": "DELETE",
        "path": "/v1/agents/sessions/sess_del",
        "beta": AGENTS_BETA_HEADER,
    }
    assert result["deleted"] is True


def test_stream_events_get():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/agents/sessions/sess_get/events"
        assert request.url.params["stream"] == "true"
        assert request.headers.get("OpenAI-Beta") == AGENTS_BETA_HEADER
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"type":"agent.session.idle"}\n\n'
                'data: {"type":"agent.session.turn.completed","turn":{"subagent_id":null}}\n\n'
            ),
        )

    events = _client(handler).stream_events("sess_get")
    assert [event["type"] for event in events] == [
        "agent.session.idle",
        "agent.session.turn.completed",
    ]


def test_rejects_unsafe_session_id():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={})

    api = _client(handler)
    with pytest.raises(AgentsApiError, match="invalid session id"):
        api.delete_session("../secret")
    with pytest.raises(AgentsApiError, match="invalid session id"):
        api.post_events("", [cancel_event()])


def test_http_error_redacts_secrets():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            401,
            text='{"error":"invalid_api_key","hint":"Bearer sk-proj-leaked-value"}',
        )

    with pytest.raises(AgentsApiError) as caught:
        _client(handler).create_session(input="x")
    assert caught.value.status_code == 401
    message = str(caught.value)
    assert "sk-proj-leaked-value" not in message
    assert "leaked-value" not in message


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HOSTED_OPENAI_KEY", raising=False)
    with pytest.raises(AgentsApiError, match="not set"):
        AgentsApiClient(api_key="")


def test_iter_sse_and_notable_helpers():
    text = (
        ": keep-alive\n"
        "\n"
        'data: {"type":"agent.session.created","id":"sess_h"}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
        'data: {"type":"agent.session.turn.item.added","item":{"type":"create_subagent_call"}}\n'
        "\n"
        'data: {"type":"noise"}\n'
        "\n"
        'data: {"type":"agent.session.turn.completed","turn":{"subagent_id":null}}\n'
        "\n"
    )
    events = list(iter_sse_events(text))
    assert session_id_from_payload(events[0]) == "sess_h"
    notable = collect_notable_events(events)
    assert [event["type"] for event in notable] == [
        "agent.session.created",
        "agent.session.turn.item.added",
        "agent.session.turn.completed",
    ]
    collected = consume_until_turn_end(events)
    assert is_coordinator_turn_end(collected[-1])
    assert collected[-1]["type"] == "agent.session.turn.completed"


def test_input_message_event_shape():
    event = input_message_event("hi")
    assert event["type"] == "agent.session.input.message"
    assert event["input"][0]["content"][0] == {"type": "input_text", "text": "hi"}


def test_live_gate_requires_flag_and_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(LIVE_FLAG_ENV, "1")
    assert agents_api_live_enabled() is False
    monkeypatch.setenv("OPENAI_API_KEY", TEST_KEY)
    monkeypatch.delenv(LIVE_FLAG_ENV, raising=False)
    assert agents_api_live_enabled() is False
    monkeypatch.setenv(LIVE_FLAG_ENV, "1")
    assert agents_api_live_enabled() is True


@pytest.mark.agents_api
@pytest.mark.skipif(
    not agents_api_live_enabled(),
    reason="set JARVIS_AGENTS_API_LIVE=1 and OPENAI_API_KEY to run the live spike",
)
def test_live_create_stream_delete():
    """Optional live proof. Never required for CI."""
    api = AgentsApiClient(timeout=90.0)
    session_id = None
    try:
        result = api.create_session(
            input="Reply with the single word ok. Do not use tools.",
            stream=True,
            instructions="Be brief. Do not spawn subagents.",
        )
        session_id = result.session_id
        assert session_id
        assert any(
            event.get("type") in (
                "agent.session.created",
                "agent.session.turn.completed",
                "agent.session.turn.failed",
                "agent.session.idle",
            )
            or session_id_from_payload(event)
            for event in result.events
        )
    finally:
        if session_id:
            api.delete_session(session_id)
