"""ORCH-325 — read-only GitHub + Slack MCP presets, scopes, voice helpers, taint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

CEO = Path(__file__).resolve().parents[1] / "app" / "static" / "ceo.html"
HTML = CEO.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------- UI / docs surface


def test_ceo_shows_presets_and_scopes_copy():
    assert "Add GitHub (read-only)" in HTML
    assert "Add Slack (read-only)" in HTML
    assert "Scopes (granted, read-only)" in HTML
    assert "/api/jarvis/mcp/presets/" in HTML


def test_docs_mention_official_endpoints():
    doc = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "jarvis-mcp-github-slack.md"
    ).read_text(encoding="utf-8")
    assert "api.githubcopilot.com/mcp/readonly" in doc
    assert "mcp.slack.com/mcp" in doc
    assert "ORCH-324" in doc


# ---------------------------------------------------------------- scope assertions


def test_github_readonly_scopes_accepted_and_write_rejected(jarvis_env):
    from app.jarvis.mcp_presets import assert_readonly_scopes

    ok = assert_readonly_scopes("github", ["repo", "read:org"])
    assert ok == ["repo", "read:org"]
    with pytest.raises(ValueError, match="write scopes|read-only"):
        assert_readonly_scopes("github", ["repo", "workflow"])
    with pytest.raises(ValueError, match="allow-list|read-only"):
        assert_readonly_scopes("github", ["admin:org"])


def test_slack_readonly_scopes_reject_chat_write(jarvis_env):
    from app.jarvis.mcp_presets import SLACK_READONLY_SCOPES, assert_readonly_scopes

    ok = assert_readonly_scopes("slack", list(SLACK_READONLY_SCOPES[:4]))
    assert "search:read.public" in ok
    with pytest.raises(ValueError, match="chat:write|read-only"):
        assert_readonly_scopes("slack", ["search:read.public", "chat:write"])
    with pytest.raises(ValueError, match="read-only"):
        assert_readonly_scopes("slack", ["canvases:write"])


# ---------------------------------------------------------------- register + token non-leak


def test_register_preset_stores_scopes_hides_token(jarvis_env):
    from app.jarvis.mcp_presets import register_preset
    from app.jarvis.mcp_registry import list_connectors_public, public_server
    from app.jarvis.settings_store import public_view

    secret = "ghp_ORCH325_NEVER_LEAK_token_value_XYZ"
    server = register_preset(
        "github",
        token=secret,
        scopes=["repo", "read:org", "read:user"],
        refresh=False,
    )
    assert server["id"] == "github"
    assert server["read_only"] is True
    assert server["url"].endswith("/readonly")
    assert "workflow" not in server["granted_scopes"]

    pub = public_server(server)
    blob = json.dumps(pub)
    assert secret not in blob
    assert "token_enc" not in pub
    assert pub["has_token"] is True
    assert pub["granted_scopes"] == ["repo", "read:org", "read:user"]
    assert pub.get("preset") == "github"

    view = public_view()
    assert secret not in json.dumps(view)
    assert any(c.get("id") == "github" for c in view.get("connectors") or [])
    assert any(p.get("id") == "github" for p in view.get("mcp_presets") or [])
    for c in list_connectors_public():
        assert secret not in json.dumps(c)
        assert "token_enc" not in c


@pytest.mark.asyncio
async def test_preset_api_token_never_echoed(client, jarvis_env):
    secret = "xoxp-orch325-slack-secret-TOKEN"
    r = await client.post(
        "/api/jarvis/mcp/presets/slack",
        json={
            "token": secret,
            "scopes": ["search:read.public", "channels:history", "users:read"],
            "refresh": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert secret not in r.text
    assert body["server"]["has_token"] is True
    assert "token_enc" not in body["server"]
    assert "search:read.public" in body["server"]["granted_scopes"]
    assert body["server"]["read_only"] is True

    listed = await client.get("/api/jarvis/mcp/presets")
    assert listed.status_code == 200
    assert secret not in listed.text
    presets = listed.json()["presets"]
    assert {p["id"] for p in presets} >= {"github", "slack"}

    settings = await client.get("/api/jarvis/settings")
    assert secret not in settings.text
    conn = next(c for c in settings.json()["connectors"] if c["id"] == "slack")
    assert conn["granted_scopes"]
    assert "token_enc" not in conn
    assert secret not in json.dumps(conn)
    # has_token may be structurally redacted by settings_store.public_view;
    # the preset endpoint above already asserted the real boolean.


@pytest.mark.asyncio
async def test_preset_api_rejects_write_scopes(client, jarvis_env):
    r = await client.post(
        "/api/jarvis/mcp/presets/github",
        json={"scopes": ["repo", "delete_repo"], "refresh": False},
    )
    assert r.status_code == 400
    assert "read-only" in r.text.lower() or "refuse" in r.text.lower()


# ---------------------------------------------------------------- voice helpers / instructions


def test_voice_summary_helpers():
    from app.jarvis.mcp_presets import (
        preset_voice_instructions,
        summarize_prs_for_voice,
        summarize_slack_missed_for_voice,
    )

    prs = summarize_prs_for_voice(
        [
            {
                "title": "Fix taint gate",
                "repo": "agent-orchestrator",
                "state": "open",
                "author": "berk",
                "review": "awaiting",
            }
        ]
    )
    assert "pull request" in prs.lower()
    assert "Fix taint gate" in prs
    assert "agent-orchestrator" in prs

    empty = summarize_prs_for_voice([])
    assert "no open pull" in empty.lower()

    slack = summarize_slack_missed_for_voice(
        [
            {
                "channel": "#eng",
                "user": "Ada",
                "text": "Can you review the MCP PR?",
            }
        ]
    )
    assert "Slack" in slack
    assert "#eng" in slack
    assert "Ada" in slack

    instr = preset_voice_instructions()
    assert "mcp.github" in instr
    assert "mcp.slack" in instr
    assert "untrusted" in instr.lower()


def test_realtime_instructions_include_mcp_block(jarvis_env):
    from app.jarvis.mcp_presets import register_preset
    from app.jarvis.realtime import build_instructions

    register_preset("github", refresh=False)
    text = build_instructions()
    assert "MCP connectors" in text or "mcp.github" in text
    assert "PRs" in text or "pull" in text.lower()


# ---------------------------------------------------------------- taint expectation (compatible with ORCH-324)


def test_mcp_taint_expectation_compatible_with_324_hooks(jarvis_env):
    """ORCH-324 may land first: if returns_untrusted covers mcp.*, assert full
    taint behaviour. Otherwise assert the hooks ORCH-323 left in place.
    """
    from app.jarvis import taint
    from app.jarvis.mcp_gateway import run_mcp_tool
    from app.jarvis.mcp_presets import register_preset
    from app.jarvis.mcp_registry import namespaced_tool, upsert_server

    assert taint.MCP_UNTRUSTED_PREFIX == "mcp."
    assert callable(taint.mcp_untrusted_tool_names)

    register_preset("github", refresh=False)
    # Inject a discovered tool without contacting GitHub.
    from app.jarvis.mcp_registry import get_server

    server = get_server("github")
    assert server
    tool_name = "list_pull_requests"
    ns = namespaced_tool("github", tool_name)
    server["discovered_tools"] = [
        {
            "name": tool_name,
            "namespaced": ns,
            "description": "list PRs",
            "tier": "L2",
            "annotations": {"readOnlyHint": True},
        }
    ]
    server["status"] = "ok"
    upsert_server(server)

    names = taint.mcp_untrusted_tool_names()
    assert ns in names

    if taint.returns_untrusted(ns):
        tracker = taint.TaintTracker()
        tracker.observe(ns)
        assert tracker.tainted is True
        assert tracker.source == ns
        # While tainted, L3+ blocked (same policy as file reads).
        decision, _ = taint.gate("run_powershell", tracker.tainted)
        assert decision == taint.BLOCK
    else:
        # Pre-324: contract is documented via prefix + registry hook.
        assert ns.startswith(taint.MCP_UNTRUSTED_PREFIX)

    # Gateway marks MCP results as untrusted candidates either way.
    # Failed/disabled path still returns the flag when tool resolves — force
    # a call against disabled to avoid network.
    server["enabled"] = False
    upsert_server(server)
    out = run_mcp_tool(ns, {})
    assert out.get("ok") is False
