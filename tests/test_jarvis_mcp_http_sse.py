"""ORCH-325 follow-up: HTTP MCP accepts SSE (GitHub remote) and plain JSON."""

from __future__ import annotations

import json

import httpx
import pytest

from app.jarvis.mcp_client import (
    HTTP_PROTOCOL_VERSION,
    _parse_sse_jsonrpc,
    http_jsonrpc,
    http_list_tools,
)


def test_parse_sse_jsonrpc_github_style():
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":"abc","result":{"tools":[{"name":"list_prs"}]}}\n'
        "\n"
    )
    data = _parse_sse_jsonrpc(body)
    assert data["result"]["tools"][0]["name"] == "list_prs"


def test_parse_sse_jsonrpc_missing_data_raises():
    with pytest.raises(RuntimeError, match="no data payload"):
        _parse_sse_jsonrpc("event: message\n\n")


def test_http_jsonrpc_accepts_sse(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["accept"] = request.headers.get("accept")
        payload = json.loads(request.content.decode())
        assert payload["method"] == "tools/list"
        body = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":"%s","result":{"tools":[{"name":"x"}]}}\n\n'
            % payload["id"]
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
        )

    transport = httpx.MockTransport(handler)

    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    result = http_jsonrpc("https://example.test/mcp", "tools/list", {})
    assert "text/event-stream" in (captured.get("accept") or "")
    assert result["tools"][0]["name"] == "x"


def test_http_jsonrpc_accepts_plain_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    result = http_jsonrpc("https://example.test/mcp", "tools/list", {})
    assert result == {"tools": []}


def test_http_list_tools_uses_http_protocol_and_initialized(monkeypatch):
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        methods.append(payload["method"])
        if payload["method"] == "initialize":
            assert payload["params"]["protocolVersion"] == HTTP_PROTOCOL_VERSION
            assert "id" in payload
            body = (
                "event: message\n"
                'data: {"jsonrpc":"2.0","id":"%s","result":{"capabilities":{}}}\n\n'
                % payload["id"]
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        if payload["method"] == "notifications/initialized":
            assert "id" not in payload
            return httpx.Response(202)
        if payload["method"] == "tools/list":
            body = (
                "event: message\n"
                'data: {"jsonrpc":"2.0","id":"%s","result":{"tools":[{"name":"get_me"}]}}\n\n'
                % payload["id"]
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    tools = http_list_tools("https://api.githubcopilot.com/mcp/readonly", token="t")
    assert [t["name"] for t in tools] == ["get_me"]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
