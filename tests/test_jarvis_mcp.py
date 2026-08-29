"""ORCH-323 — MCP client, registry, gateway dispatch, settings connectors."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

CEO = Path(__file__).resolve().parents[1] / "app" / "static" / "ceo.html"
HTML = CEO.read_text(encoding="utf-8")

# Minimal stdio MCP server script (Content-Length framed JSON-RPC).
_FAKE_STDIO_SCRIPT = r'''
import json, sys

def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("ascii", errors="replace").rstrip("\r\n")
        if ":" in text:
            k, v = text.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", "0"))
    body = sys.stdin.buffer.read(n)
    return json.loads(body.decode("utf-8"))

def send(msg):
    raw = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()

TOOLS = [{
    "name": "echo",
    "description": "Echo text",
    "annotations": {"readOnlyHint": True},
}]

while True:
    msg = read_msg()
    if msg is None:
        break
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{
            "protocolVersion":"2024-11-05",
            "capabilities":{"tools":{}},
            "serverInfo":{"name":"fake","version":"0.0.1"},
        }})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        text = str((params.get("arguments") or {}).get("text") or "")
        send({"jsonrpc":"2.0","id":mid,"result":{
            "content":[{"type":"text","text": "echo:"+text}],
            "isError": False,
        }})
    elif mid is not None:
        send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"unknown"}})
'''


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_ENABLED", "false")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    import app.jarvis.gateway as gw
    from app.jarvis import mcp_registry, mcp_tokens, settings_store

    gw._gateway = None
    settings_store.reset_cache()
    mcp_registry.reset_cache()
    mcp_tokens.reset_cipher_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    mcp_registry.reset_cache()
    mcp_tokens.reset_cipher_cache()


@pytest.fixture
async def client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def _stdio_server_body() -> dict:
    return {
        "name": "Fake Stdio",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-c", _FAKE_STDIO_SCRIPT],
        "enabled": True,
        "trusted": False,
        "max_tier": "L2",
        "refresh": True,
    }


# ---------------------------------------------------------------- HTML


def test_connectors_ui_present():
    assert "Connectors" in HTML
    assert "None yet" in HTML
    assert "/api/jarvis/mcp/servers" in HTML
    assert "Add connector" in HTML
    assert "Bearer token" in HTML or "never shown" in HTML.lower()


# ---------------------------------------------------------------- tokens


def test_token_never_in_settings_or_connectors(jarvis_env):
    from app.jarvis.mcp_registry import (
        list_connectors_public,
        new_server_id,
        public_server,
        upsert_server,
    )
    from app.jarvis.mcp_tokens import encrypt_token
    from app.jarvis.settings_store import public_view

    secret = "super-secret-mcp-token-VALUE-999"
    upsert_server(
        {
            "id": new_server_id(),
            "name": "Tok",
            "transport": "http",
            "url": "http://127.0.0.1:9/mcp",
            "enabled": False,
            "trusted": False,
            "max_tier": "L5",
            "status": "disabled",
            "last_error": None,
            "token_enc": encrypt_token(secret),
            "discovered_tools": [],
        }
    )
    view = public_view()
    blob = json.dumps(view)
    assert secret not in blob
    assert "token_enc" not in blob
    for c in list_connectors_public():
        assert secret not in json.dumps(c)
        assert "token_enc" not in c
        assert c.get("has_token") is True
        pub = public_server(c) if "token_enc" in c else c
        assert "token_enc" not in pub


@pytest.mark.asyncio
async def test_token_endpoint_async(client, jarvis_env):
    r = await client.post(
        "/api/jarvis/mcp/servers",
        json={
            "name": "T",
            "transport": "http",
            "url": "http://127.0.0.1:9/x",
            "enabled": False,
            "refresh": False,
        },
    )
    assert r.status_code == 200
    sid = r.json()["server"]["id"]
    secret = "echo-me-never-please-TOKEN"
    r2 = await client.post(
        f"/api/jarvis/mcp/servers/{sid}/token",
        json={"token": secret},
    )
    assert r2.status_code == 200
    assert secret not in r2.text
    assert r2.json()["server"]["has_token"] is True
    r3 = await client.get("/api/jarvis/settings")
    assert secret not in r3.text


# ---------------------------------------------------------------- stdio discover + dispatch


@pytest.mark.asyncio
async def test_register_stdio_discovers_and_dispatches(client, jarvis_env):
    r = await client.post("/api/jarvis/mcp/servers", json=_stdio_server_body())
    assert r.status_code == 200, r.text
    server = r.json()["server"]
    assert server["status"] == "ok"
    assert server["discovered_tools"]
    tool = server["discovered_tools"][0]
    assert tool["tier"] == "L5"  # untrusted default
    assert tool["namespaced"].startswith("mcp.")

    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    # L5 > personal max L2 → needs confirm
    pending = g.run(tool["namespaced"], {"text": "hi"}, source="test")
    assert pending.get("needs_confirm") is True
    assert pending.get("confirm_id")
    # Confirm and execute
    done = g.confirm(pending["confirm_id"], "approve", source="test")
    assert done.get("ok") is True
    assert "echo:hi" in (done.get("content") or "")


def test_tier_defaults_and_annotations(jarvis_env):
    from app.jarvis.mcp_registry import compute_tool_tier
    from app.jarvis.permissions import Tier

    assert compute_tool_tier(trusted=False, max_tier="L1", annotations={}) == Tier.L5
    assert compute_tool_tier(trusted=True, max_tier="L2", annotations={}) == Tier.L2
    # annotations raise only
    assert compute_tool_tier(
        trusted=True, max_tier="L2", annotations={"destructiveHint": True}
    ) == Tier.L5
    assert compute_tool_tier(
        trusted=True, max_tier="L2", annotations={"readOnlyHint": False}
    ) == Tier.L3
    # readOnlyHint true must NOT lower below trusted max start
    assert compute_tool_tier(
        trusted=True, max_tier="L2", annotations={"readOnlyHint": True}
    ) == Tier.L2


@pytest.mark.asyncio
async def test_trusted_server_caps_starting_tier(client, jarvis_env):
    body = _stdio_server_body()
    body["trusted"] = True
    body["max_tier"] = "L1"
    r = await client.post("/api/jarvis/mcp/servers", json=body)
    assert r.status_code == 200
    tool = r.json()["server"]["discovered_tools"][0]
    # readOnlyHint true → stays at trusted max L1
    assert tool["tier"] == "L1"


# ---------------------------------------------------------------- HTTP mock


class _McpHandler(BaseHTTPRequestHandler):
    token_required = None

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        if self.token_required:
            auth = self.headers.get("Authorization") or ""
            if auth != f"Bearer {self.token_required}":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"unauthorized"}')
                return
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "http-fake", "version": "0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "ping",
                        "description": "ping",
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [{"type": "text", "text": "pong"}],
                "isError": False,
            }
        else:
            result = {}
        body = json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def http_mcp_server():
    server = HTTPServer(("127.0.0.1", 0), _McpHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/mcp"
    server.shutdown()


@pytest.mark.asyncio
async def test_register_http_discovers(client, jarvis_env, http_mcp_server):
    r = await client.post(
        "/api/jarvis/mcp/servers",
        json={
            "name": "HTTP Fake",
            "transport": "http",
            "url": http_mcp_server,
            "enabled": True,
            "trusted": True,
            "max_tier": "L2",
            "refresh": True,
        },
    )
    assert r.status_code == 200, r.text
    server = r.json()["server"]
    assert server["status"] == "ok"
    assert server["discovered_tools"][0]["name"] == "ping"
    assert server["discovered_tools"][0]["tier"] == "L2"


# ---------------------------------------------------------------- failure + gateway


@pytest.mark.asyncio
async def test_failed_server_visible_and_gateway_safe(client, jarvis_env):
    r = await client.post(
        "/api/jarvis/mcp/servers",
        json={
            "name": "Broken",
            "transport": "http",
            "url": "http://127.0.0.1:1/nope",
            "enabled": True,
            "refresh": True,
        },
    )
    assert r.status_code == 200
    server = r.json()["server"]
    assert server["status"] == "failed"
    assert server.get("last_error")

    settings = await client.get("/api/jarvis/settings")
    assert settings.status_code == 200
    conns = settings.json().get("connectors") or []
    assert any(c.get("status") == "failed" for c in conns)

    # Manually inject a discovered tool on a failed server and ensure run is safe
    from app.jarvis.mcp_registry import get_server, namespaced_tool, upsert_server
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    s = get_server(server["id"])
    assert s
    s["discovered_tools"] = [
        {
            "name": "x",
            "namespaced": namespaced_tool(s["id"], "x"),
            "description": "x",
            "tier": "L5",
            "annotations": {},
        }
    ]
    upsert_server(s)
    gw._gateway = None
    g = ToolGateway()
    # needs confirm first
    pending = g.run(s["discovered_tools"][0]["namespaced"], {}, source="test")
    assert pending.get("needs_confirm") or pending.get("ok") is False
    if pending.get("needs_confirm"):
        out = g.confirm(pending["confirm_id"], "approve", source="test")
    else:
        out = pending
    assert out.get("ok") is False
    assert "unavailable" in (out.get("error") or "").lower() or "fail" in (
        out.get("error") or ""
    ).lower()


def test_unknown_mcp_tool_not_dispatchable(jarvis_env):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.permissions import is_known_tool

    assert is_known_tool("mcp.nope.tool") is False
    g = ToolGateway()
    r = g.run("mcp.nope.tool", {}, source="test")
    assert r.get("ok") is False
    assert "unknown" in (r.get("error") or "").lower()


def test_every_discovered_tool_has_tier(jarvis_env):
    from app.jarvis.mcp_client import refresh_server
    from app.jarvis.mcp_registry import new_server_id, upsert_server
    from app.jarvis.permissions import tool_tier

    server = upsert_server(
        {
            "id": new_server_id(),
            "name": "S",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", _FAKE_STDIO_SCRIPT],
            "enabled": True,
            "trusted": False,
            "max_tier": "L5",
            "status": "unknown",
            "discovered_tools": [],
            "token_enc": "",
        }
    )
    server = refresh_server(server)
    assert server["status"] == "ok"
    for t in server["discovered_tools"]:
        assert t.get("tier", "").startswith("L")
        assert tool_tier(t["namespaced"]).name.startswith("L")


@pytest.mark.asyncio
async def test_crud_delete(client, jarvis_env):
    r = await client.post(
        "/api/jarvis/mcp/servers",
        json={
            "name": "Temp",
            "transport": "http",
            "url": "http://127.0.0.1:9/x",
            "enabled": False,
            "refresh": False,
        },
    )
    sid = r.json()["server"]["id"]
    d = await client.delete(f"/api/jarvis/mcp/servers/{sid}")
    assert d.status_code == 200
    listed = await client.get("/api/jarvis/mcp/servers")
    ids = [s["id"] for s in listed.json()["servers"]]
    assert sid not in ids


def test_orch324_taint_hooks_exist():
    from app.jarvis import taint

    assert hasattr(taint, "mcp_untrusted_tool_names")
    assert hasattr(taint, "MCP_UNTRUSTED_PREFIX")
    assert taint.MCP_UNTRUSTED_PREFIX == "mcp."
    # Wired: every mcp.* name taints without opt-in.
    assert taint.returns_untrusted("mcp.demo.echo") is True
    assert taint.returns_untrusted("read_file") is True
    assert taint.returns_untrusted("get_disk_space") is False
