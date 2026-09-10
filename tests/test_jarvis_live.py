"""GPT-Live-1 session config, event unwrap, and route mapping. No live OpenAI."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.live import (
    DEFAULT_BACKEND_MODEL,
    DEFAULT_LIVE_MODEL,
    LIVE_SESSIONS_URL,
    build_backend_instructions,
    build_live_create_payload,
    build_live_session_config,
    build_voice_instructions,
    continue_response_event,
    function_call_from_output_item,
    function_call_output_event,
    live_available,
    live_backend_model,
    live_model,
    parse_function_arguments,
    parse_live_create_response,
    unwrap_live_event,
    validate_sdp_offer,
    voice_path,
)
from app.jarvis.realtime import TEST_FORCE_ENGLISH, listen_mode
from app.jarvis.tts import speak_mode


SAMPLE_SDP = (
    "v=0\r\n"
    "o=- 0 0 IN IP4 127.0.0.1\r\n"
    "s=-\r\n"
    "t=0 0\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
)


@pytest.fixture
def openai_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mom-key-not-real")
    monkeypatch.delenv("JARVIS_VOICE", raising=False)
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


def test_voice_path_defaults_to_live(monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE", raising=False)
    assert voice_path() == "live"
    monkeypatch.setenv("JARVIS_VOICE", "")
    assert voice_path() == "live"
    monkeypatch.setenv("JARVIS_VOICE", "LIVE")
    assert voice_path() == "live"
    monkeypatch.setenv("JARVIS_VOICE", "realtime")
    assert voice_path() == "realtime"
    monkeypatch.setenv("JARVIS_VOICE", "openai_realtime")
    assert voice_path() == "realtime"


def test_live_available_needs_key_and_default_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    monkeypatch.delenv("JARVIS_VOICE", raising=False)
    assert live_available() is True
    assert listen_mode() == "openai_live"
    assert speak_mode() == "openai_live"
    monkeypatch.setenv("JARVIS_VOICE", "realtime")
    assert live_available() is False
    assert listen_mode() == "openai_realtime"
    assert speak_mode() == "openai_realtime"


def test_live_models_default_and_pin(monkeypatch):
    monkeypatch.delenv("OPENAI_LIVE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_LIVE_BACKEND_MODEL", raising=False)
    assert live_model() == DEFAULT_LIVE_MODEL == "gpt-live-1"
    assert live_backend_model() == DEFAULT_BACKEND_MODEL == "gpt-5.6-terra"
    monkeypatch.setenv("OPENAI_LIVE_MODEL", "gpt-live-1")
    monkeypatch.setenv("OPENAI_LIVE_BACKEND_MODEL", "gpt-5.6-luna")
    assert live_backend_model() == "gpt-5.6-luna"


def test_voice_prompt_is_short_and_delegates():
    voice = build_voice_instructions(locale="en", timezone=None)
    assert "Jarvis" in voice
    assert "Delegation policy" in voice
    assert "Interruption policy" in voice
    assert "cannot see images" in voice.lower() or "cannot see images" in voice
    assert "see_screen" not in voice or "Delegate" in voice
    assert "DuckDuckGo" not in voice
    assert "SERP is not done" not in voice
    assert "batch clicks" not in voice.lower()
    if TEST_FORCE_ENGLISH:
        assert "TEST_FORCE_ENGLISH" in voice
        assert "English only" in voice


def test_backend_prompt_keeps_look_click_confirm_and_text_vision():
    backend = build_backend_instructions(locale="en", timezone=None)
    assert "see_screen" in backend
    assert "needs_confirm" in backend
    assert "Live audio cannot accept images" in backend
    assert "short text facts" in backend
    assert "vision_description" in backend.lower() or "vision_description" in backend


def test_live_session_config_uses_responses_delegation():
    cfg = build_live_session_config(voice="coral", locale="en")
    assert cfg["model"] == "gpt-live-1"
    assert "Delegation policy" in cfg["instructions"]
    assert "DuckDuckGo" not in cfg["instructions"]
    assert cfg["audio"]["output"]["voice"] == "coral"
    deleg = cfg["delegation"]
    assert deleg["type"] == "responses"
    resp = deleg["responses"]
    assert resp["model"] == "gpt-5.6-terra"
    assert resp["parallel_tool_calls"] is False
    assert resp["tool_choice"] == "auto"
    names = {t["name"] for t in resp["tools"] if t.get("type") == "function"}
    assert "see_screen" in names
    assert "click" in names
    assert "Live audio cannot accept images" in resp["instructions"]


def test_live_create_payload_wraps_sdp():
    payload = build_live_create_payload(SAMPLE_SDP, voice="marin", locale="en")
    assert payload["transport"] == {"type": "webrtc", "sdp": SAMPLE_SDP}
    assert payload["session"]["model"] == "gpt-live-1"


def test_validate_sdp_offer_rejects_empty_and_huge():
    assert validate_sdp_offer(SAMPLE_SDP) == SAMPLE_SDP.strip()
    with pytest.raises(ValueError):
        validate_sdp_offer("")
    with pytest.raises(ValueError):
        validate_sdp_offer("not-sdp")
    with pytest.raises(ValueError):
        validate_sdp_offer("v=" + ("x" * (96 * 1024)))


def test_unwrap_response_event_preserves_delegation_id():
    envelope = {
        "type": "response.event",
        "event_id": "event_response_1",
        "delegation_id": "item_deleg_1",
        "event": {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": "call_123",
                "name": "see_screen",
                "arguments": '{"goal":"what do you see"}',
            },
        },
    }
    inner = unwrap_live_event(envelope)
    assert inner["type"] == "response.output_item.done"
    assert inner["_delegation_id"] == "item_deleg_1"
    call = function_call_from_output_item(inner)
    assert call == {
        "call_id": "call_123",
        "name": "see_screen",
        "arguments": {"goal": "what do you see"},
        "delegation_id": "item_deleg_1",
    }
    result = function_call_output_event("call_123", '{"ok":true,"summary":"desktop"}')
    assert result["type"] == "response.item.create"
    assert result["item"]["type"] == "function_call_output"
    assert result["item"]["call_id"] == "call_123"
    assert "desktop" in result["item"]["output"]
    assert continue_response_event() == {"type": "response.create"}


def test_unwrap_passes_through_session_events():
    started = {"type": "session.started", "session": {"id": "live_1"}}
    assert unwrap_live_event(started) is started
    assert function_call_from_output_item(started) is None
    assert parse_function_arguments("not-json") == {}


def test_parse_live_create_response_requires_sdp():
    parsed = parse_live_create_response(
        {
            "session": {"id": "live_abc"},
            "transport": {"type": "webrtc", "sdp": "v=0\r\n"},
        }
    )
    assert parsed["session_id"] == "live_abc"
    assert parsed["sdp"] == "v=0"
    with pytest.raises(ValueError):
        parse_live_create_response({"session": {"id": "live_abc"}})


@pytest.mark.asyncio
async def test_health_reports_openai_live_when_key_present(openai_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/jarvis/health")
    get_settings.cache_clear()
    body = r.json()
    assert body["ok"] is True
    assert body["live"] is True
    assert body["voice_path"] == "live"
    assert body["live_model"] == "gpt-live-1"
    assert body["listen_mode"] == "openai_live"
    assert body["speak_mode"] == "openai_live"
    assert body["realtime"] is True
    assert body["can_listen"] is True
    assert "sk-test" not in r.text
    assert "OPENAI_API_KEY" not in r.text


@pytest.mark.asyncio
async def test_live_session_route_posts_sdp_and_hides_key(openai_env, monkeypatch):
    import httpx
    from app.config import get_settings
    from app.jarvis import realtime_routes
    from app.main import create_app

    captured: dict = {}

    class _FakeRes:
        status_code = 201
        text = ""

        def json(self):
            return {
                "session": {"id": "live_test_1"},
                "transport": {"type": "webrtc", "sdp": "v=0\r\nanswer"},
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["auth"] = (headers or {}).get("Authorization")
            captured["json"] = json
            return _FakeRes()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(realtime_routes.httpx, "AsyncClient", _FakeClient)
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/jarvis/live/session",
                json={"sdp": SAMPLE_SDP, "voice": "coral", "locale": "it-IT"},
            )
    get_settings.cache_clear()
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["live"] is True
    assert body["session"]["id"] == "live_test_1"
    assert body["transport"]["sdp"] == "v=0\r\nanswer"
    assert body["voice"] == "coral"
    assert body["model"] == "gpt-live-1"
    assert captured["url"] == LIVE_SESSIONS_URL
    assert captured["auth"] == "Bearer sk-test-openai-optional-upgrade"
    session = (captured["json"] or {}).get("session") or {}
    assert session["model"] == "gpt-live-1"
    assert session["delegation"]["type"] == "responses"
    assert session["delegation"]["responses"]["parallel_tool_calls"] is False
    assert captured["json"]["transport"]["sdp"] == SAMPLE_SDP.strip()
    assert "sk-test" not in r.text
    assert "OPENAI_API_KEY" not in r.text
    # TEST_FORCE_ENGLISH ignores the Italian locale for the first hello.
    assert "TEST_FORCE_ENGLISH" in session["instructions"]


@pytest.mark.asyncio
async def test_live_session_without_openai_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mom-key-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/jarvis/live/session",
                json={"sdp": SAMPLE_SDP},
            )
    get_settings.cache_clear()
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert body["live"] is False
    assert body["fallback"] == "browser_speech"
    assert body["listen_mode"] == "browser_speech"
    assert "OPENAI_API_KEY" not in r.text


@pytest.mark.asyncio
async def test_live_session_rejects_missing_sdp(openai_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/live/session", json={"voice": "coral"})
    get_settings.cache_clear()
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_realtime_session_is_dead_when_live_is_default(openai_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/realtime/session", json={"voice": "coral"})
    get_settings.cache_clear()
    assert r.status_code == 409
    body = r.json()
    assert body["live"] is True
    assert body["fallback"] == "openai_live"
    assert body["listen_mode"] == "openai_live"
    assert "value" not in body
    assert "sk-test" not in r.text


def test_public_and_ceo_pages_use_live_connect():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    public = (root / "deploy" / "jarvis-public" / "index.html").read_text(
        encoding="utf-8"
    )
    ceo = (root / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    for page in (public, ceo):
        assert "/api/jarvis/live/session" in page
        assert 'createDataChannel("oai-events")' in page
        assert "session.started" in page
        assert "session.close" in page
        assert "response.item.create" in page
        assert "unwrapLiveEvent" in page
        assert "openai_live" in page
        assert "OPENAI_API_KEY" not in page
        assert "sk-" not in page
    assert "async function connectLive" in public
    assert "async function connectLive" in ceo
    assert "function liveGreetEvent" in public
    assert "TEST_FORCE_ENGLISH" in public
    assert "const TEST_FORCE_ENGLISH = true" in public
