"""Next.js Windows desktop UI — issues #93 / #94 / #95 / #96."""

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
WEB = ROOT / "desktop-web"
DESKTOP = ROOT / "desktop"


def test_next_app_exists_with_elevenlabs_conversation():
    assert (WEB / "package.json").is_file()
    pkg = (WEB / "package.json").read_text(encoding="utf-8")
    assert '"name": "desktop-web"' in pkg
    conversation = (WEB / "components" / "ui" / "conversation.tsx").read_text(encoding="utf-8")
    assert "ConversationEmptyState" in conversation
    assert "use-stick-to-bottom" in conversation
    assert (WEB / "components" / "ui" / "message.tsx").is_file()
    assert (WEB / "components" / "ui" / "orb.tsx").is_file()
    assert (WEB / "components" / "ui" / "response.tsx").is_file()
    middle = (WEB / "components" / "desktop" / "MiddlePane.tsx").read_text(encoding="utf-8")
    assert "from \"@/components/ui/conversation\"" in middle
    assert "<Orb" in middle
    assert "/api/jarvis/ask" not in middle or "composer" in middle
    assert 'id="ask"' in middle
    assert 'id="mic"' in middle
    assert 'id="send"' in middle
    assert "Start a conversation" in middle or "emptyOrbTitle" in middle or "LABELS.empty" in middle


def test_react_shell_matches_mock_and_honest_helpers():
    left = (WEB / "components" / "desktop" / "LeftPane.tsx").read_text(encoding="utf-8")
    right = (WEB / "components" / "desktop" / "RightPane.tsx").read_text(encoding="utf-8")
    shell = (WEB / "components" / "desktop" / "Shell.tsx").read_text(encoding="utf-8")
    jarvis = (WEB / "lib" / "jarvis.ts").read_text(encoding="utf-8")
    combined = left + right + shell + jarvis
    assert 'id="left"' in left
    assert 'id="middle"' in (WEB / "components" / "desktop" / "MiddlePane.tsx").read_text(encoding="utf-8")
    assert 'id="right"' in right
    assert 'id="live-computer"' in right
    assert 'id="live-frame"' in right
    assert 'data-embed="iframe"' in right
    assert "#1A1D23" in left
    assert "#F8F9FB" in (WEB / "components" / "desktop" / "MiddlePane.tsx").read_text(encoding="utf-8")
    assert "Not connected yet" in jarvis
    assert "No routines yet." in jarvis
    assert "Chat only" in jarvis
    assert "stopComputer: false" in jarvis
    assert "killsComputerOnHide: false" in jarvis
    assert "Buyra" not in combined
    assert "Morning briefing" not in combined
    assert "/api/jarvis/computer/screen/stop" not in combined
    assert "api key" not in combined.lower()
    assert "openrouter" not in combined.lower()


def test_electron_prefers_next_or_dev_url():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    pkg = (DESKTOP / "package.json").read_text(encoding="utf-8")
    assert "resolveDesktopHref" in helpers
    assert "REACT_SHELL_PATH" in helpers
    assert "/desktop-ui" in helpers
    assert "JARVIS_DESKTOP_UI_URL" in helpers
    assert "function nextUiDir" in main
    assert "resolveDesktopHref" in main
    assert "prepare-desktop-ui.js" in pkg


def test_desktop_web_helpers():
    result = subprocess.run(
        ["npm", "test"],
        cwd=str(WEB),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
async def client():
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_desktop_ui_route_falls_back_or_serves_next(client):
    r = await client.get("/desktop-ui", follow_redirects=False)
    assert r.status_code in (200, 307)
    if r.status_code == 307:
        assert r.headers.get("location") == "/desktop"
        legacy = await client.get("/desktop-legacy")
        assert legacy.status_code == 200
        assert 'id="left"' in legacy.text
    else:
        assert "text/html" in r.headers.get("content-type", "")
        assert "Jarvis" in r.text
        assert "or-test-key" not in r.text
