"""Public Talk must never load the operator localhost noVNC URL in the iframe.

The /jarvis/api/jarvis/computer/screen contract still returns
session_url=http://127.0.0.1:6080/... for the host. That URL is for
docker on the machine, not for a visitor's browser.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "deploy" / "jarvis-public" / "screen.html"
PUBLIC = ROOT / "deploy" / "jarvis-public" / "index.html"
WATCH = ROOT / "deploy" / "jarvis-android" / "watch" / "server.py"


def _load_script(html: str) -> str:
    return html.split("<script>", 1)[1].rsplit("</script>", 1)[0]


def test_public_screen_does_not_assign_session_from_session_url():
    html = SCREEN.read_text(encoding="utf-8")
    script = _load_script(html)
    assert "if (data && data.session_url) SESSION = String(data.session_url);" not in script
    assert not re.search(r"SESSION\s*=\s*String\(\s*data\.session_url", script)
    assert not re.search(r"SESSION\s*=\s*data\.session_url", script)
    assert "function publicSession" in script
    assert "SESSION = publicSession(data)" in script
    assert "SESSION = publicSession(started || data)" in script


def test_public_talk_iframe_never_uses_loopback():
    html = SCREEN.read_text(encoding="utf-8")
    talk = PUBLIC.read_text(encoding="utf-8")
    script = _load_script(html)
    assert 'src="http://127.0.0.1' not in html
    assert 'src="http://localhost' not in html
    assert "http://127.0.0.1:6080" not in html
    assert "http://127.0.0.1:6081" not in html
    assert not re.search(r'setAttribute\(\s*"src"\s*,\s*["\']https?://(?:127\.0\.0\.1|localhost)', html)
    assert "var LINUX_SESSION = \"/jarvis/novnc/vnc.html" in script
    assert 'path=jarvis/novnc/websockify"' in script or "path=jarvis/novnc/websockify" in script
    assert "/jarvis/android/" in script
    assert "ANDROID_WATCH_URL" not in html
    iframe = talk.split('id="pc-frame"', 1)[1].split(">", 1)[0]
    assert "127.0.0.1" not in iframe
    assert "localhost" not in iframe.lower()
    assert 'frame.setAttribute("src", "/jarvis/screen?picture="' in talk
    assert "http://127.0.0.1:6080" not in talk
    assert "http://127.0.0.1:6081" not in talk


def test_public_session_rejects_operator_loopback_and_uses_watch_path():
    html = SCREEN.read_text(encoding="utf-8")
    script = _load_script(html)
    assert "function isPublicWatchSrc" in script
    assert 'low.indexOf("://")' in script
    assert 'low.indexOf("127.0.0.1")' in script
    assert 'low.indexOf("localhost")' in script
    assert 'isPublicWatchSrc(watch, "/jarvis/android/")' in script
    assert 'isPublicWatchSrc(publicUrl, "/jarvis/novnc/")' in script
    assert "data.session_url" not in script
    assert "data.url" not in script


def test_android_watch_stream_is_under_jarvis_prefix():
    watch = WATCH.read_text(encoding="utf-8")
    assert 'src="/stream.mjpeg"' not in watch
    assert 'src="stream.mjpeg"' in watch
    assert "/jarvis/android/stream.mjpeg" in watch


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    os.environ["API_SECRET"] = "test-secret-at-least-32-chars-long!!"
    os.environ["TOKEN_ENCRYPTION_KEY"] = ""
    os.environ["TOKEN_PROVIDER"] = "api_key"

    from app.config import get_settings
    from app.jarvis.screen_viewer import reset_screen_viewer_state, set_screen_probe

    reset_screen_viewer_state()
    set_screen_probe(lambda: {"running": True, "status_code": 200})
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    reset_screen_viewer_state()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_public_screen_page_and_api_keep_operator_session_url(client):
    page = await client.get("/jarvis/screen")
    assert page.status_code == 200
    assert "Jarvis's screen" in page.text
    assert "function publicSession" in page.text
    assert "SESSION = publicSession(data)" in page.text
    assert "http://127.0.0.1:6080" not in page.text
    assert "if (data && data.session_url) SESSION = String(data.session_url);" not in page.text

    status = await client.get("/jarvis/api/jarvis/computer/screen")
    assert status.status_code == 200
    body = status.json()
    assert body["running"] is True
    assert body["kind"] == "linux"
    assert body["public_bind"] is False
    assert body["watch_path"] == "/jarvis/novnc/"
    assert "127.0.0.1" in body["session_url"]
    assert "6080" in body["session_url"]
    assert body["session_url"].startswith("http://127.0.0.1:6080")
