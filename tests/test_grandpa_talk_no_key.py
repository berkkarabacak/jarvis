"""Family talk path: no user key, operator/hosted talk, honest Free/$3/$8."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"

USER_UX_FILES = (
    DESKTOP / "first-run.html",
    DESKTOP / "first-run-preload.js",
    DESKTOP / "electron-builder.installer.yml",
    ROOT / "docs" / "START-HERE-WINDOWS.txt",
    ROOT / "deploy" / "jarvis-public" / "index.html",
)

SECRETISH = re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}")


@pytest.fixture
def talk_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
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


async def _health(monkeypatch_app=True):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/jarvis/health")
    get_settings.cache_clear()
    return r


def test_user_first_run_and_installer_ux_has_no_key_prompt():
    for path in USER_UX_FILES:
        text = path.read_text(encoding="utf-8")
        low = text.lower()
        assert "api key" not in low, path
        assert "openrouter" not in low, path
        if "jarvis-public" not in str(path):
            assert "openai" not in low, path
        assert "OPENAI_API_KEY" not in text, path
        assert "sk-or-" not in text, path
        assert "sk-" not in text, path
        assert SECRETISH.search(text) is None, path


def test_first_run_html_is_welcome_and_plans_only():
    html = (DESKTOP / "first-run.html").read_text(encoding="utf-8")
    assert "Welcome to Jarvis" in html
    assert "Free" in html
    assert "$3" in html
    assert "$8" in html
    assert 'id="key"' not in html
    assert "saveKey" not in html
    assert "password" not in html.lower()


def test_packaged_start_skips_the_key_window():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    policy = (DESKTOP / "talk-policy.js").read_text(encoding="utf-8")
    assert "shouldShowFirstRunKeyWindow" in main
    assert "shouldShowFirstRunKeyWindow" in policy
    assert "return false" in policy
    result = subprocess.run(
        [sys.executable and "node", str(DESKTOP / "talk-policy.test.js")],
        cwd=str(DESKTOP),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "talk-policy helpers ok" in result.stdout


def test_no_secrets_in_desktop_or_installer_tree():
    paths = [
        *USER_UX_FILES,
        DESKTOP / "talk-policy.js",
        DESKTOP / "talk-policy.test.js",
        DESKTOP / "main.js",
        DESKTOP / "package.json",
        ROOT / "scripts" / "windows" / "build-installer.ps1",
        ROOT / "docs" / "windows-installer.md",
        ROOT / "desktop" / "README.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "sk-or-v1-" not in text, path
        assert SECRETISH.search(text) is None, path
        if path in USER_UX_FILES:
            assert "sk-or-" not in text, path
            assert re.search(r"(?i)\bsk-[a-z0-9]", text) is None, path


def test_ceo_settings_has_honest_plans_and_hides_keys_on_desktop():
    html = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert 'id = "iu-subscribe"' in html
    assert "Current plan: Free" in html
    assert "$3" in html
    assert "$8" in html
    assert "does not charge a card" in html
    assert "Can't talk right now" in html
    assert "Add your OpenRouter key" not in html
    assert "desktopMode" in html
    assert 'sec("API keys")' in html
    assert "if (!desktopMode)" in html


def test_operator_and_hosted_helpers(monkeypatch):
    from app.jarvis.talk_auth import (
        CANT_TALK,
        DEFAULT_HOSTED_TALK_URL,
        openrouter_api_key,
        should_use_hosted_talk,
        talk_ready,
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    assert CANT_TALK == "Can't talk right now"
    assert DEFAULT_HOSTED_TALK_URL == "https://berkkarabacak.com/jarvis"
    assert openrouter_api_key() == ""
    assert talk_ready() is False
    assert should_use_hosted_talk() is False


def test_operator_key_makes_talk_ready(monkeypatch):
    from app.jarvis.realtime import can_listen
    from app.jarvis.talk_auth import openrouter_api_key, talk_ready
    from app.jarvis.tts import can_speak, speak_mode

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setenv("JARVIS_OPERATOR_OPENROUTER_KEY", "operator-test-key-not-a-secret")
    assert openrouter_api_key() == "operator-test-key-not-a-secret"
    assert talk_ready() is True
    assert can_listen() is True
    assert can_speak() is True
    assert speak_mode() == "openrouter_tts"


def test_hosted_url_makes_talk_ready(monkeypatch):
    from app.jarvis.realtime import can_listen, listen_mode
    from app.jarvis.talk_auth import hosted_talk_endpoint, should_use_hosted_talk
    from app.jarvis.tts import can_speak, neural_tts_available, speak_mode

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    assert should_use_hosted_talk() is True
    assert can_listen() is True
    assert listen_mode() == "browser_speech"
    assert can_speak() is True
    assert speak_mode() == "hosted_tts"
    assert neural_tts_available() is True
    assert hosted_talk_endpoint("ask") == "https://berkkarabacak.com/jarvis/api/jarvis/ask"
    assert hosted_talk_endpoint("speak") == "https://berkkarabacak.com/jarvis/api/jarvis/speak"


def test_hosted_url_does_not_proxy_to_self(monkeypatch):
    from app.jarvis.talk_auth import should_use_hosted_talk

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://berkkarabacak.com/jarvis")
    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    assert should_use_hosted_talk() is False


@pytest.mark.asyncio
async def test_health_operator_key_without_user_env(talk_env, monkeypatch):
    monkeypatch.setenv("JARVIS_OPERATOR_OPENROUTER_KEY", "operator-test-key-not-a-secret")
    r = await _health()
    assert r.status_code == 200
    body = r.json()
    assert body["can_listen"] is True
    assert body["can_speak"] is True
    assert body["listen_mode"] == "browser_speech"
    assert body["speak_mode"] == "openrouter_tts"
    assert body["neural_tts"] is True
    assert body["openrouter"] is True
    assert body["hosted_talk"] is False
    assert "operator-test-key-not-a-secret" not in r.text


@pytest.mark.asyncio
async def test_health_hosted_talk_without_user_key(talk_env, monkeypatch):
    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    r = await _health()
    assert r.status_code == 200
    body = r.json()
    assert body["can_listen"] is True
    assert body["can_speak"] is True
    assert body["listen_mode"] == "browser_speech"
    assert body["speak_mode"] == "hosted_tts"
    assert body["neural_tts"] is True
    assert body["openrouter"] is False
    assert body["hosted_talk"] is True


@pytest.mark.asyncio
async def test_ask_and_speak_use_hosted_talk(talk_env, monkeypatch):
    from app.config import get_settings
    from app.jarvis import tts, voice_ask
    from app.main import create_app

    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    captured: dict = {}

    class _AskRes:
        status_code = 200

        def json(self):
            return {"ok": True, "reply": "Hello from hosted talk.", "tools_used": []}

    class _SpeakRes:
        status_code = 200
        content = b"ID3hosted-mp3"
        text = ""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["ask_url"] = url
            captured["ask_json"] = json
            return _AskRes()

    async def fake_post(url, headers, payload):
        captured["speak_url"] = url
        captured["speak_payload"] = payload
        return _SpeakRes()

    monkeypatch.setattr(voice_ask.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(tts, "_post_speech", fake_post)

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            ask = await ac.post("/api/jarvis/ask", json={"text": "hello there"})
            speak = await ac.post("/api/jarvis/speak", json={"text": "Hello from hosted talk."})
    get_settings.cache_clear()
    assert ask.status_code == 200, ask.text
    assert ask.json()["reply"] == "Hello from hosted talk."
    assert captured["ask_url"] == "https://berkkarabacak.com/jarvis/api/jarvis/ask"
    assert speak.status_code == 200
    assert speak.content == b"ID3hosted-mp3"
    assert captured["speak_url"] == "https://berkkarabacak.com/jarvis/api/jarvis/speak"


@pytest.mark.asyncio
async def test_health_and_talk_ui_agree_on_hosted_path(talk_env, monkeypatch):
    monkeypatch.setenv("JARVIS_HOSTED_TALK_URL", "https://berkkarabacak.com/jarvis")
    r = await _health()
    health = r.json()
    script = (
        "const m = require("
        + json.dumps(str(DESKTOP / "mini-avatar.js"))
        + ");\n"
        "const h = "
        + json.dumps(health)
        + ";\n"
        "if (m.connectActionFromHealth(h) !== 'start_browser_listen') process.exit(2);\n"
        "if (m.talkPathFromHealth(h).mintRealtime) process.exit(3);\n"
        "if (!m.talkPathFromHealth(h).canSpeak) process.exit(4);\n"
        "process.stdout.write('ok');\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=str(DESKTOP),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "ok"
