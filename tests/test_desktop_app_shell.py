"""Windows 3-pane shell chrome — issues #74 / #67 (epic #66)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")
os.environ.setdefault("LLM_MODEL_MODE", "fixed")
os.environ.setdefault("DEFAULT_MODEL", "openai/gpt-4.1-mini")

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
SHELL_HTML = ROOT / "app" / "static" / "desktop.html"


def test_app_shell_helpers():
    script = DESKTOP / "app-shell.test.js"
    result = subprocess.run(
        ["node", str(script)],
        cwd=str(DESKTOP),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "app-shell helpers ok" in result.stdout


def test_electron_hosts_three_pane_as_primary_window():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    pkg = (DESKTOP / "package.json").read_text(encoding="utf-8")
    yml = (DESKTOP / "electron-builder.installer.yml").read_text(encoding="utf-8")

    assert 'require("./app-shell")' in main
    assert "function desktopUrl" in main
    assert "function ceoUrl" in main
    assert "loadURL(desktopUrl(port))" in main
    assert "createTalkEngineWindow" in main
    assert "function openSettingsInWindow" in main
    assert "jarvis:open-settings" in main
    assert "Quit Jarvis" in main
    assert "trayMenuItems" in main
    assert "shouldShowFirstRunKeyWindow" in main
    assert "/desktop" in shell
    assert 'defaultLaunch: "main"' in helpers
    assert "function shouldShowMainOnLaunch" in helpers
    assert "openSettings" in preload
    assert "app-shell.js" in pkg
    assert "app-shell.js" in yml
    assert (DESKTOP / "app-shell.js").is_file()


def test_three_pane_html_is_light_grok_like_chrome():
    html = SHELL_HTML.read_text(encoding="utf-8")
    low = html.lower()
    assert 'id="left"' in html
    assert 'id="middle"' in html
    assert 'id="right"' in html
    assert 'id="live-computer"' in html
    assert 'id="composer"' in html
    assert 'id="ask"' in html
    assert 'id="mic"' in html
    assert 'id="send"' in html
    assert "Helpers" in html
    assert "Chats" in html
    assert "Group chats" in html
    assert "Jarvis's screen" in html
    assert "Routines" in html
    assert "Type a message" in html
    assert "Hide chats" in html
    assert "Show chats" in html
    assert "Hide computer" in html
    assert "Show computer" in html
    assert "Chat only" in html
    assert "talk_mode" in html
    assert "/api/jarvis/settings" in html
    assert "127.0.0.1:6080" in html
    assert "left-collapsed" in html
    assert "right-collapsed" in html
    assert "#efece8" in html
    assert "border-radius: 20px" in html or "border-radius: var(--radius)" in html
    assert "api key" not in low
    assert "openrouter" not in low
    assert 'id="voiceDock"' not in html
    assert "Coming soon" in html


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

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_desktop_route_serves_three_pane_shell(client):
    r = await client.get("/desktop")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert 'id="left"' in r.text
    assert 'id="middle"' in r.text
    assert 'id="right"' in r.text
    assert "API secret" not in r.text
    assert "or-test-key" not in r.text


@pytest.mark.asyncio
async def test_ceo_talk_page_still_exists(client):
    r = await client.get("/ceo")
    assert r.status_code == 200
    assert 'id="voiceDock"' in r.text
