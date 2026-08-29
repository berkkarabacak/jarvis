"""Voice listen with only OPENROUTER_API_KEY — no OpenAI Realtime required."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
Usage = namedtuple("usage", "total used free")


@pytest.fixture
def voice_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mom-key-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("JARVIS_REALTIME", "true")
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


@pytest.fixture
async def client(voice_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def _win_exists(path: str) -> bool:
    raw = str(path).replace("/", "\\").upper()
    return raw.startswith("C:")


def _win_usage(_path: str) -> Usage:
    return Usage(total=256 * 1024**3, used=int(213.5 * 1024**3), free=int(42.5 * 1024**3))


@pytest.mark.asyncio
async def test_health_can_listen_without_openai(client):
    r = await client.get("/api/jarvis/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["realtime"] is False
    assert body["can_listen"] is True
    assert body["listen_mode"] == "browser_speech"
    assert body["can_speak"] is True
    assert body["speak_mode"] == "openrouter_tts"
    assert body["neural_tts"] is True
    assert body["openrouter"] is True


@pytest.mark.asyncio
async def test_health_cannot_listen_without_keys(voice_env, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    assert body["realtime"] is False
    assert body["can_listen"] is False
    assert body["listen_mode"] == "none"
    assert body["can_speak"] is False
    assert body["speak_mode"] == "none"
    assert body["neural_tts"] is False


@pytest.mark.asyncio
async def test_health_realtime_when_openai_present(voice_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
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
    assert body["realtime"] is True
    assert body["can_listen"] is True
    assert body["listen_mode"] == "openai_realtime"
    assert body["can_speak"] is True
    assert body["speak_mode"] == "openai_realtime"
    assert body["neural_tts"] is True


@pytest.mark.asyncio
async def test_ask_how_much_free_space_uses_get_disk_space(client, monkeypatch):
    from app.jarvis import host_disk

    monkeypatch.setattr(host_disk, "windows_shaped", lambda **_k: True)
    monkeypatch.setattr(host_disk.os.path, "exists", _win_exists)
    monkeypatch.setattr(host_disk.shutil, "disk_usage", _win_usage)

    r = await client.post("/api/jarvis/ask", json={"text": "how much free space"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["tools_used"] == ["get_disk_space"]
    assert "42.50 GB" in body["reply"] or "42.5" in body["reply"]
    assert "C:" in body["reply"]
    assert "free" in body["reply"].lower()
    assert body["ui"]["ok"] is True


def test_listen_helpers_split_can_listen_from_realtime(monkeypatch):
    from app.jarvis.realtime import can_listen, listen_mode, realtime_available
    from app.jarvis.tts import can_speak, neural_tts_available, speak_mode

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-only")
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    assert realtime_available() is False
    assert can_listen() is True
    assert listen_mode() == "browser_speech"
    assert can_speak() is True
    assert speak_mode() == "openrouter_tts"
    assert neural_tts_available() is True


def test_speak_mode_openai_tts_when_realtime_flag_off(monkeypatch):
    from app.jarvis.tts import speak_mode

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-tts-only")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-only")
    monkeypatch.setenv("JARVIS_REALTIME", "false")
    assert speak_mode() == "openai_tts"


def test_first_run_never_asks_for_a_key():
    html = (ROOT / "desktop" / "first-run.html").read_text(encoding="utf-8")
    low = html.lower()
    assert "api key" not in low
    assert "openrouter" not in low
    assert "openai" not in low
    assert "Welcome to Jarvis" in html


def test_avatar_error_is_listening_when_openrouter_can_listen():
    html = (ROOT / "desktop" / "avatar.html").read_text(encoding="utf-8")
    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    routes = (ROOT / "app" / "jarvis" / "realtime_routes.py").read_text(encoding="utf-8")
    assert 'status === "error") return canListen === false' in html
    assert "Can't hear right now" in html
    assert "Listening…" in html
    assert 'canListen ? "listening" : "unavailable"' in ceo
    assert "Can't hear right now" not in ceo
    assert "askViaOpenRouter" in ceo
    assert "speakNeural" in ceo
    assert "/api/jarvis/speak" in ceo
    assert "outputMuted" in ceo
    assert "if (outputMuted) return false" in ceo
    assert 'id="mute"' in html
    assert 'id="close"' in html
    # Replies must never use Windows SAPI / speechSynthesis.
    assert "speechSynthesis.speak" not in html
    assert "speechSynthesis.speak" not in ceo
    assert "SpeechSynthesisUtterance" not in html
    assert "SpeechSynthesisUtterance" not in ceo
    assert "function speakReply" not in html
    assert "function speakReply" not in ceo
    assert "new Audio(" in ceo
    # Talk/call follows health: browser_speech / openrouter_tts never mint.
    assert "function talkPathFromHealth" in ceo
    assert "function talkPathFromHealth" in html
    assert "function startOpenRouterTalk" in ceo
    assert "mintRealtime" in ceo
    assert 'token.fallback === "browser_speech"' in ceo
    assert "if (health.realtime) return" not in html
    assert "OPENAI_API_KEY is not set" not in ceo
    assert "OPENAI_API_KEY is not set" not in html
    assert "OPENAI_API_KEY is not set" not in routes
    assert "required for Realtime voice" not in routes
    assert "CANT_TALK" in routes
    assert "Add your OpenRouter key" not in routes
    from app.jarvis.talk_auth import CANT_TALK

    assert CANT_TALK == "Can't talk right now"


@pytest.mark.asyncio
async def test_speak_openrouter_uses_published_model_and_stored_voice(
    client, voice_env, monkeypatch
):
    from app.jarvis import settings_store, tts

    settings_store.save({"realtime_voice": "coral"})
    captured: dict = {}

    class _FakeRes:
        status_code = 200
        content = b"ID3fake-mp3-bytes-here"
        text = ""

    async def fake_post(url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return _FakeRes()

    monkeypatch.setattr(tts, "_post_speech", fake_post)
    r = await client.post("/api/jarvis/speak", json={"text": "You have 42 GB free."})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == b"ID3fake-mp3-bytes-here"
    assert captured["url"] == tts.OPENROUTER_TTS_URL
    assert captured["payload"]["model"] == "mistralai/voxtral-mini-tts-2603"
    assert captured["payload"]["model"] == tts.OPENROUTER_TTS_MODEL
    assert captured["payload"]["voice"] == "en_paul_neutral"
    assert captured["payload"]["input"] == "You have 42 GB free."
    assert captured["payload"]["response_format"] == "mp3"
    assert "sk-or-mom-key-not-real" in captured["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_speak_openai_preferred_when_key_present(voice_env, monkeypatch):
    from app.config import get_settings
    from app.jarvis import tts
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-tts")
    monkeypatch.setenv("JARVIS_REALTIME", "false")
    captured: dict = {}

    class _FakeRes:
        status_code = 200
        content = b"ID3openai-mp3"
        text = ""

    async def fake_post(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        captured["auth"] = headers.get("Authorization")
        return _FakeRes()

    monkeypatch.setattr(tts, "_post_speech", fake_post)
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/speak", json={"text": "Hello."})
    get_settings.cache_clear()
    assert r.status_code == 200
    assert captured["url"] == tts.OPENAI_TTS_URL
    assert captured["payload"]["model"] == "gpt-4o-mini-tts"
    assert captured["payload"]["voice"] == "marin"
    assert captured["auth"] == "Bearer sk-test-openai-tts"


@pytest.mark.asyncio
async def test_speak_silent_when_no_neural_tts(voice_env, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/speak", json={"text": "should stay silent"})
    get_settings.cache_clear()
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_speak_provider_error_stays_silent(client, monkeypatch):
    from app.jarvis import tts

    class _FakeRes:
        status_code = 402
        content = b""
        text = '{"error":"payment required"}'

    async def fake_post(url, headers, payload):
        return _FakeRes()

    monkeypatch.setattr(tts, "_post_speech", fake_post)
    r = await client.post("/api/jarvis/speak", json={"text": "stay quiet"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_speak_ignores_fake_scottish_voice_slug(client, monkeypatch):
    from app.jarvis import tts

    captured: dict = {}

    class _FakeRes:
        status_code = 200
        content = b"ID3ok"
        text = ""

    async def fake_post(url, headers, payload):
        captured["payload"] = payload
        return _FakeRes()

    monkeypatch.setattr(tts, "_post_speech", fake_post)
    r = await client.post(
        "/api/jarvis/speak",
        json={"text": "Hello.", "voice": "scottish"},
    )
    assert r.status_code == 200
    assert captured["payload"]["voice"] == "en_paul_neutral"


def test_tts_model_ids_are_published_not_invented():
    from app.jarvis.realtime import ALLOWED_REALTIME_VOICES
    from app.jarvis.tts import (
        OPENAI_TTS_MODEL,
        OPENROUTER_TTS_MODEL,
        OPENROUTER_TTS_VOICE,
        OPENROUTER_TTS_VOICES,
        _openrouter_voice,
    )

    assert OPENROUTER_TTS_MODEL == "mistralai/voxtral-mini-tts-2603"
    assert OPENROUTER_TTS_MODEL != "openai/gpt-4o-mini-tts-2025-12-15"
    assert OPENAI_TTS_MODEL == "gpt-4o-mini-tts"
    assert OPENROUTER_TTS_VOICE == "en_paul_neutral"
    assert OPENROUTER_TTS_VOICE in OPENROUTER_TTS_VOICES
    assert _openrouter_voice("marin") == "en_paul_neutral"
    assert _openrouter_voice("coral") == "en_paul_neutral"
    assert _openrouter_voice("en_paul_neutral") == "en_paul_neutral"
    assert "scottish" not in ALLOWED_REALTIME_VOICES
    assert "fable" not in ALLOWED_REALTIME_VOICES
    assert "marin" in ALLOWED_REALTIME_VOICES
    assert "cedar" in ALLOWED_REALTIME_VOICES


def test_null_stored_voice_defaults_to_marin_not_sapi(voice_env):
    from app.jarvis.realtime import resolve_realtime_voice
    from app.jarvis.settings_store import get_realtime_voice, load

    assert load().get("realtime_voice") is None
    assert get_realtime_voice() == "marin"
    assert resolve_realtime_voice(None) == "marin"
    assert resolve_realtime_voice("scottish") == "marin"


def test_plain_talk_voice_aliases_map_to_allow_list(voice_env):
    from app.jarvis.realtime import ALLOWED_REALTIME_VOICES, resolve_realtime_voice

    assert resolve_realtime_voice("warm") == "marin"
    assert resolve_realtime_voice("clear") == "alloy"
    assert resolve_realtime_voice("deep") == "echo"
    assert "warm" not in ALLOWED_REALTIME_VOICES
    assert "clear" not in ALLOWED_REALTIME_VOICES
    assert "deep" not in ALLOWED_REALTIME_VOICES


@pytest.mark.asyncio
async def test_settings_reject_invented_scottish_slug(client):
    r = await client.put("/api/jarvis/settings", json={"realtime_voice": "scottish"})
    assert r.status_code == 400
    warm = await client.put("/api/jarvis/settings", json={"realtime_voice": "warm"})
    assert warm.status_code == 400


def test_ceo_realtime_replies_do_not_call_http_tts():
    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert "if (listenMode !== \"openai_realtime\") void speakNeural(reply)" in ceo
    assert "if (outputMuted) return false" in ceo
    assert "SpeechRecognition" in ceo


@pytest.mark.asyncio
async def test_session_without_openai_does_not_block_openrouter_talk(client):
    r = await client.post("/api/jarvis/realtime/session", json={})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["realtime"] is False
    assert body["can_listen"] is True
    assert body["listen_mode"] == "browser_speech"
    assert body["can_speak"] is True
    assert body["speak_mode"] == "openrouter_tts"
    assert body["fallback"] == "browser_speech"
    assert "OPENAI_API_KEY" not in r.text
    assert "required for Realtime" not in r.text


@pytest.mark.asyncio
async def test_session_no_keys_asks_for_openrouter_not_openai(voice_env, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/realtime/session", json={})
    get_settings.cache_clear()
    assert r.status_code == 503
    body = r.json()
    assert body["can_listen"] is False
    assert body["fallback"] == "none"
    assert body["detail"] == "Can't talk right now"
    assert "OpenRouter" not in body["detail"]
    assert "API key" not in body["detail"]
    assert "OPENAI_API_KEY" not in r.text
    assert "required for Realtime" not in r.text


@pytest.mark.asyncio
async def test_session_with_openai_still_mints(voice_env, monkeypatch):
    import httpx
    from app.config import get_settings
    from app.jarvis import realtime_routes
    from app.main import create_app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
    captured: dict = {}

    class _FakeRes:
        status_code = 200
        text = ""

        def json(self):
            return {"value": "eph-test-token"}

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
            captured["session"] = json
            return _FakeRes()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(realtime_routes.httpx, "AsyncClient", _FakeClient)
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/jarvis/realtime/session", json={"voice": "coral"})
    get_settings.cache_clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value"] == "eph-test-token"
    assert body["voice"] == "coral"
    assert captured["url"] == "https://api.openai.com/v1/realtime/client_secrets"
    assert captured["auth"] == "Bearer sk-test-openai-optional-upgrade"
    assert (captured["session"] or {}).get("session", {}).get("audio", {}).get(
        "output", {}
    ).get("voice") == "coral"


@pytest.mark.asyncio
async def test_health_and_talk_ui_agree_not_to_mint_session(client):
    import json
    import subprocess

    r = await client.get("/api/jarvis/health")
    assert r.status_code == 200
    health = r.json()
    assert health["can_listen"] is True
    assert health["can_speak"] is True
    assert health["listen_mode"] == "browser_speech"
    assert health["speak_mode"] == "openrouter_tts"
    assert health["realtime"] is False

    script = (
        "const m = require("
        + json.dumps(str(ROOT / "desktop" / "mini-avatar.js"))
        + ");\n"
        "const h = "
        + json.dumps(health)
        + ";\n"
        "if (m.connectActionFromHealth(h) !== 'start_browser_listen') process.exit(2);\n"
        "if (m.talkPathFromHealth(h).mintRealtime) process.exit(3);\n"
        "if (m.afterRealtimeSessionFailure(h, {fallback:'browser_speech'})"
        " !== 'start_browser_listen') process.exit(4);\n"
        "process.stdout.write('ok');\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT / "desktop"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "ok"
