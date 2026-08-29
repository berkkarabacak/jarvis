"""ORCH-301 — Realtime confirm routes: nonce utterance + bare refuse."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_TOKEN", "test-bridge-token-secret")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-not-real")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    import app.jarvis.gateway as gw

    gw._gateway = None
    yield ws


@pytest.mark.asyncio
async def test_realtime_confirm_action_bare_refused(jarvis_env, monkeypatch):
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.main import app
    from app.jarvis.gateway import get_gateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = get_gateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output rt"},
        source="realtime",
        confirmed=False,
    )
    assert pending.get("needs_confirm") is True
    assert pending.get("nonce_prompt")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/run",
            json={"name": "confirm_action", "arguments": {"decision": "confirm"}},
        )
    assert r.status_code == 200
    body = r.json()["result"]
    assert body.get("ok") is False
    # ORCH-319 changed the wording: a bare "confirm" from a tool call is now
    # refused for the channel rather than for the missing code, so assert the
    # outcome instead of the sentence.
    assert body.get("outcome") == "needs_user"
    assert g.pending_confirms()


@pytest.mark.asyncio
async def test_a_tool_call_cannot_approve_even_with_the_right_code(
    jarvis_env, monkeypatch
):
    """ORCH-319. This test previously asserted the opposite — that posting the
    correct code to /tools/run approves. That endpoint carries MODEL tool
    calls, so an approval arriving on it is authored by the model, and the
    model is steerable by any file, screen, or page it has read. The code
    being right is not the point; the channel is."""
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.main import app
    from app.jarvis.gateway import get_gateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = get_gateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output rt2"},
        source="realtime",
        confirmed=False,
    )
    code = pending["nonce_code"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/run",
            json={
                "name": "confirm_action",
                "arguments": {"decision": "confirm", "utterance": f"confirm {code}"},
            },
        )
    assert r.status_code == 200
    body = r.json()["result"]
    assert body.get("ok") is False
    assert "cannot approve" in (body.get("error") or "").lower()
    assert g.pending_confirms(), "the action must still be waiting"


@pytest.mark.asyncio
async def test_the_spoken_channel_approves_with_the_right_code(
    jarvis_env, monkeypatch
):
    """The counterpart: the same code on /tools/confirm — where the browser
    puts the raw ASR transcript — does approve."""
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.main import app
    from app.jarvis.gateway import get_gateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = get_gateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output rt2"},
        source="realtime",
        confirmed=False,
    )
    code = pending["nonce_code"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/confirm",
            json={"decision": "confirm", "utterance": f"confirm {code}"},
        )
    assert r.status_code == 200
    body = r.json()["result"]
    assert not g.pending_confirms(), "the action should have been settled"
    err = (body.get("error") or "").lower()
    assert (
        "exit_code" in body
        or body.get("ok") is True
        or "powershell" in err
        or "no such file" in err
    )


@pytest.mark.asyncio
async def test_the_model_never_receives_the_code_in_any_spelling(jarvis_env):
    """The original bug: `nonce_code` was deleted from the model payload but
    `nonce_prompt` survived, spelling the same code out in words. Assert on
    the digits AND the words, since spoken_digits() reads them identically."""
    from app.main import app
    from app.jarvis.gateway import get_gateway
    from app.jarvis.nonce import say_code
    import app.jarvis.gateway as gw
    import json as _json

    gw._gateway = None
    g = get_gateway()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/run",
            json={
                "name": "run_powershell",
                "arguments": {"command": "Write-Output leak-check"},
            },
        )
    body = r.json()
    to_model = _json.dumps(body["result"])
    code = body["ui"]["nonce_code"]

    assert body["ui"]["needs_confirm"] is True, "precondition: a confirm is pending"
    assert code not in to_model, "raw digits reached model context"
    assert say_code(code) not in to_model, "the code in words reached model context"
    assert "nonce_prompt" not in to_model
    assert "confirm_id" not in to_model, "knowing confirm_id is enough to approve"
    # ...and the page still gets what it needs to run the UI.
    assert body["ui"]["confirm_id"] and body["ui"]["nonce_prompt"]


@pytest.mark.asyncio
async def test_a_tool_call_may_still_cancel(jarvis_env, monkeypatch):
    """Refusing is always safe, so the model is allowed to do it — otherwise
    'no, stop' would go nowhere while the user is talking to the model."""
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.main import app
    from app.jarvis.gateway import get_gateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = get_gateway()
    g.run("run_powershell", {"command": "Write-Output rt3"}, source="realtime")
    assert g.pending_confirms()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/run",
            json={"name": "confirm_action", "arguments": {"decision": "cancel"}},
        )
    assert r.status_code == 200
    assert r.json()["result"].get("ok") is True
    assert not g.pending_confirms()


@pytest.mark.asyncio
async def test_realtime_instructions_mention_nonce(jarvis_env):
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS, build_instructions

    text = build_instructions()
    # ORCH-319: the model is no longer told to read nonce_prompt or to pass an
    # utterance — it never sees the code, and cannot approve. The instructions
    # must say so, so the model does not narrate an approval it cannot perform.
    assert "cannot approve" in JARVIS_REALTIME_INSTRUCTIONS
    assert "action_summary" in JARVIS_REALTIME_INSTRUCTIONS
    assert "cancel" in JARVIS_REALTIME_INSTRUCTIONS
    assert "nonce_prompt" not in text, "the model is told about a field it must not see"
    assert "action_summary" in text


@pytest.mark.asyncio
async def test_input_transcription_is_enabled(jarvis_env):
    """Without it there is no human-authored channel to resolve a code from,
    and the spoken confirmation path silently never fires."""
    from app.jarvis.realtime import build_realtime_session_config

    from app.jarvis.realtime import TEST_FORCE_ENGLISH

    cfg = build_realtime_session_config()
    tx = cfg["audio"]["input"].get("transcription") or {}
    assert tx.get("model")
    lang = str(tx.get("language") or "").strip().lower()
    assert "es-es" not in str(tx).lower()
    if TEST_FORCE_ENGLISH:
        # TEST pin for public Talk. Flip TEST_FORCE_ENGLISH to restore auto-detect.
        assert lang == "en"
    else:
        # Auto-detect the speaker. Do not pin Spanish (or only English).
        assert lang in {"", "auto"}
        assert tx.get("language") not in {"es", "es-ES", "en", "en-US"}



def test_model_view_keeps_ordinary_results_and_strips_confirm_secrets():
    """model_view must not empty successful payloads — only confirm challenges
    are allowlisted. Regression for ORCH-319 rebase review."""
    from app.jarvis.gateway import model_view

    ordinary = {"ok": True, "result": {"cpu": "ok"}, "summary": "Ready."}
    assert model_view(ordinary) == ordinary

    challenge = {
        "ok": False,
        "needs_confirm": True,
        "tier": "L3",
        "action_summary": "Delete Downloads?",
        "confirm_id": "cnf_x",
        "nonce_code": "24",
        "nonce_prompt": "To confirm, say: confirm two four.",
        "extra_future_secret": "must-not-leak",
    }
    viewed = model_view(challenge)
    assert viewed == {
        "ok": False,
        "needs_confirm": True,
        "tier": "L3",
        "action_summary": "Delete Downloads?",
    }
    assert "confirm_id" not in viewed
    assert "nonce_code" not in viewed
    assert "nonce_prompt" not in viewed
    assert "extra_future_secret" not in viewed


@pytest.mark.asyncio
async def test_ordinary_tool_results_still_reach_the_model(jarvis_env):
    """HTTP path: a successful /tools/run keeps result/summary for the model."""
    from app.main import app
    from app.jarvis.gateway import get_gateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    get_gateway()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/jarvis/tools/run",
            json={"name": "system_info", "arguments": {}},
        )
    assert r.status_code == 200
    body = r.json()
    result = body["result"]
    assert result.get("ok") is True
    assert result.get("result") is not None or result.get("summary")
