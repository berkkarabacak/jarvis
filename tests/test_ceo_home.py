import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["API_SECRET"] = "test-secret"
os.environ["TOKEN_ENCRYPTION_KEY"] = ""
os.environ["TOKEN_PROVIDER"] = "api_key"
os.environ["XAI_API_KEY"] = "xai-test-key"
os.environ["LLM_PROVIDER"] = "openrouter"
os.environ["OPENROUTER_API_KEY"] = "or-test-key"
os.environ["LLM_MODEL_MODE"] = "fixed"
os.environ["DEFAULT_MODEL"] = "openai/gpt-4.1-mini"

AUTH = {"X-Api-Key": "test-secret"}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")

    from app.ceo.mission_mock import reset_mock_mission_store
    from app.config import get_settings

    reset_mock_mission_store()
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()
    reset_mock_mission_store()


@pytest.mark.asyncio
async def test_ceo_page_public_shell(client):
    """v2 Jarvis UI: landscape wall + empty white circle only ==GRoK==."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Jarvis" in r.text
    assert "API secret" not in r.text
    assert "Enter control room" not in r.text
    assert 'id="voiceDock"' in r.text
    assert 'id="wall"' in r.text
    assert 'id="ring"' in r.text
    assert 'id="stopBtn"' in r.text
    assert 'aria-label="Stop"' in r.text
    assert ">Stop</button>" not in r.text
    assert 'id="confirmPanel"' in r.text
    assert 'id="confirmAllow"' in r.text
    assert 'id="confirmCancel"' in r.text
    assert "missionInput" not in r.text
    assert "accountChip" not in r.text
    assert "Progress drawer" not in r.text
    assert "test-secret" not in r.text
    assert "or-test-key" not in r.text


@pytest.mark.asyncio
async def test_ceo_page_uses_cookie_session_without_client_credentials(client):
    """Realtime mint uses same-origin cookies; no client API keys ==GRoK==."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    html = r.text

    assert 'credentials: "same-origin"' in html
    assert "/api/jarvis/realtime/session" in html
    assert "/api/jarvis/tools/run" in html
    assert "/api/jarvis/tools/confirm" in html
    assert "authKey" not in html
    assert "getKey" not in html
    assert "setKey" not in html
    assert "clearKey" not in html
    assert "X-Api-Key" not in html
    assert "OPENAI_API_KEY" not in html
    assert "sk-" not in html
    assert 'id="gateMain"' not in html
    assert 'id="apiKey"' not in html


@pytest.mark.asyncio
async def test_ceo_page_live_chat_contract_and_safe_rendering(client):
    """v2 uses OpenAI Realtime + local tools, not public executive missions."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    html = r.text

    assert "async function connect()" in html
    assert "async function runTool(name, args)" in html
    assert "function sendToolResult(callId, output)" in html
    assert "needs_confirm" in html
    assert "showConfirmPanel" in html
    assert 'decision: "approve"' in html or '"approve"' in html
    assert "RTCPeerConnection" in html
    assert "function_call" in html
    assert "innerHTML" not in html
    assert 'api("/api/ceo/missions"' not in html
    assert "X-Api-Key" not in html


@pytest.mark.asyncio
async def test_ceo_page_voice_surface_contract(client):
    """OpenAI Realtime when available; Web Speech + /ask otherwise."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    html = r.text

    assert "getUserMedia" in html
    assert "AudioContext" in html
    assert "RTCPeerConnection" in html
    assert "/api/jarvis/realtime/session" in html
    assert "/api/jarvis/ask" in html
    assert "SpeechRecognition" in html
    assert "askViaOpenRouter" in html
    assert "startBrowserListen" in html
    assert "can_listen" in html
    assert "function talkPathFromHealth" in html
    assert "function startOpenRouterTalk" in html
    assert "mintRealtime" in html
    assert 'token.fallback === "browser_speech"' in html
    assert "async function connect()" in html
    assert "function teardown()" in html
    assert "function retry(reason)" in html
    assert "Can't hear right now" not in html
    assert "OPENAI_API_KEY is not set" not in html


@pytest.mark.asyncio
async def test_ceo_live_stop_contract(client):
    """Teardown closes peer connection / data channel on stop/retry."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    html = r.text

    assert 'id="stopBtn"' in html
    assert 'aria-label="Stop"' in html
    assert ">Stop</button>" not in html
    assert "function stopSession()" in html
    assert "function teardown()" in html
    assert "stopTracks" in html
    assert "pc && pc.close()" in html
    assert "dc && dc.close()" in html
    assert "micStream" in html
    assert "MAX_ATTEMPTS" in html
    assert 'body[data-rt="connecting"] #stopBtn' in html or 'data-rt="connecting"' in html
    assert 'body[data-rt="live"] #stopBtn' in html or 'data-rt="live"' in html


@pytest.mark.asyncio
async def test_ceo_confirm_overlay_contract(client):
    """Older-user confirm UI: high-contrast Allow/Cancel for needs_confirm tools."""
    r = await client.get("/ceo")
    assert r.status_code == 200
    html = r.text

    assert 'id="confirmPanel"' in html
    assert 'id="confirmAllow"' in html
    assert 'id="confirmCancel"' in html
    assert 'id="confirmText"' in html
    assert 'id="confirmCountdown"' in html
    assert "Accepting in " in html
    assert "approve_countdown_sec" in html
    assert "/api/jarvis/tools/confirm" in html
    assert "needs_confirm" in html
    assert "action_summary" in html
    assert "user_prompt" in html
    assert "showConfirmPanel" in html
    assert "finishUiConfirm" in html
    assert "startConfirmCountdown" in html
    assert "nonce_prompt" in html or "nonce_code" in html
    assert "handledCalls" in html
    assert "executeFunctionCall" in html
    assert "confirmQueue" in html
    assert "Allow" in html
    assert "Cancel" in html


@pytest.mark.asyncio
async def test_ceo_presence_requires_secret(client):
    r = await client.get("/api/ceo/presence")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ceo_presence_mock_shape(client):
    r = await client.get("/api/ceo/presence", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] >= 1
    assert body["source"] == "mock"
    assert body["safe_copy"] is True
    assert body["avatar_state"] == "listening"
    assert "listening" in body["avatar_states"]
    assert body["status_line"]
    assert "objective" in body["progress"]
    assert "progress_drawer" in body
    assert "controls" in body
    assert body["controls"]["can_start"] is True
    assert "subtitle_prefs" in body
    assert "access_token" not in str(body)
    assert "refresh_token" not in str(body)


@pytest.mark.asyncio
async def test_ceo_presence_avatar_and_mode(client):
    r = await client.get(
        "/api/ceo/presence",
        headers=AUTH,
        params={"avatar_state": "blocked", "display_mode": "cards", "subtitles": "0"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["avatar_state"] == "blocked"
    assert body["display_mode"] == "cards"
    assert body["subtitles_enabled"] is False
    assert body["subtitle"] == ""
    assert "Blocked" in body["status_line"]


@pytest.mark.asyncio
async def test_ceo_mock_mission_lifecycle_and_drawer(client):
    r = await client.post(
        "/api/ceo/missions",
        headers=AUTH,
        json={"brief": "Build a calm landing page"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    mid = body["mission_id"]
    assert body["status"] == "active"
    assert body["presence"]["mission_id"] == mid
    assert body["presence"]["controls"]["can_pause"] is True
    assert body["presence"]["progress_drawer"]["confidence"] is not None

    r = await client.get("/api/ceo/progress", headers=AUTH)
    assert r.status_code == 200
    drawer = r.json()
    assert drawer["mission_id"] == mid
    assert drawer["status"] == "active"
    assert len(drawer["events"]) >= 1

    r = await client.get("/api/ceo/preview", headers=AUTH)
    assert r.status_code == 200
    preview = r.json()
    assert preview["kind"] == "placeholder"
    assert "Preview" in preview["title"] or preview["ready"] is False

    r = await client.post(
        "/api/ceo/missions/pause",
        headers=AUTH,
        json={"mission_id": mid},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "paused"
    assert r.json()["presence"]["controls"]["can_resume"] is True

    r = await client.post(
        "/api/ceo/missions/resume",
        headers=AUTH,
        json={"mission_id": mid},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    r = await client.post(
        "/api/ceo/missions/stop",
        headers=AUTH,
        json={"mission_id": mid, "reason": "ceo_stopped"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_ceo_subtitle_prefs_allowlist(client):
    r = await client.get("/api/ceo/subtitles", headers=AUTH)
    assert r.status_code == 200
    assert "en" in r.json()["languages"]

    r = await client.post(
        "/api/ceo/subtitles",
        headers=AUTH,
        json={
            "enabled": True,
            "language": "zz",
            "size": "huge",
            "only_while_speaking": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "en"  # invalid -> default
    assert body["size"] == "md"
    assert body["only_while_speaking"] is True

    r = await client.get(
        "/api/ceo/presence",
        headers=AUTH,
        params={
            "subtitles": "1",
            "subtitle_language": "nl",
            "subtitle_size": "lg",
            "only_while_speaking": "1",
            "avatar_state": "working",
        },
    )
    assert r.status_code == 200
    prefs = r.json()["subtitle_prefs"]
    assert prefs["language"] == "nl"
    assert prefs["size"] == "lg"
    # only_while_speaking hides subtitle when not speaking
    assert r.json()["subtitle"] == ""


@pytest.mark.asyncio
async def test_ceo_start_requires_brief(client):
    r = await client.post("/api/ceo/missions", headers=AUTH, json={"brief": "  "})
    assert r.status_code == 400

