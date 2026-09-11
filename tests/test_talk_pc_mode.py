"""Talk closable PC view (#60) + Terminal vs Computer mode (#61)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
SECRET = "test-secret-at-least-32-chars-long!!"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _js() -> str:
    return _page().split("<script>")[-1].rsplit("</script>", 1)[0]


def _html() -> str:
    return _page().split("<script src=", 1)[0]


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TALK_MODE", raising=False)
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


@pytest.fixture
async def public_client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=("203.0.113.10", 443))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def test_talk_mode_defaults_to_computer(jarvis_env):
    from app.jarvis.settings_store import (
        DEFAULT_TALK_MODE,
        get_talk_mode,
        public_view,
        validate_update,
    )

    assert DEFAULT_TALK_MODE == "computer"
    assert get_talk_mode() == "computer"
    view = public_view()
    assert view["talk_mode"] == "computer"
    ids = [row["id"] for row in view["talk_modes"]]
    assert ids == ["computer", "terminal"]
    with pytest.raises(ValueError):
        validate_update({"talk_mode": "voice"})
    with pytest.raises(ValueError):
        validate_update({"talk_mode": "cli-only"})


def test_talk_mode_aliases_and_persist(jarvis_env):
    from app.jarvis.settings_store import get_talk_mode, public_view, save, validate_update

    assert validate_update({"talk_mode": "CLI"}) == {"talk_mode": "terminal"}
    assert validate_update({"talk_mode": "pc"}) == {"talk_mode": "computer"}
    save({"talk_mode": "terminal"})
    assert get_talk_mode() == "terminal"
    assert public_view()["talk_mode"] == "terminal"
    save({"talk_mode": "computer"})
    assert get_talk_mode() == "computer"


def test_talk_html_has_closable_pc_and_mode_picks():
    html = _html()
    js = _js()
    assert 'id="pc"' in html
    assert 'id="pc-hide"' in html
    assert 'id="pc-show"' in html
    assert 'aria-label="Hide screen"' in html
    assert 'aria-label="Show screen"' in html
    assert 'data-talk-mode="computer"' in html
    assert 'data-talk-mode="terminal"' in html
    assert "Uses the screen when he needs it." in html
    assert "Chat only. No PC." in html
    assert 'id="talk-mode-picks"' in html
    assert "function setPcVisible" in js
    assert "function applyTalkMode" in js
    assert "function applyPcView" in js
    assert "function clearPcFrame" in js
    assert 'sessionStorage.setItem(PC_SESSION_KEY' in js
    assert 'prefs.pcVisible' in js
    assert "if (next === \"terminal\") prefs.pcVisible = false" in js
    assert "if (next === \"computer\") prefs.pcVisible = true" not in js
    assert 'setAttribute("src", "about:blank")' in js
    assert "if (!pcShouldShow()) return" in js
    assert "saveTalkSettings({ talk_mode: next })" in js
    assert "setPcVisible(false)" in js
    assert "setPcVisible(true)" in js
    assert "pcEl.hidden = !show" in js


@pytest.mark.asyncio
async def test_public_talk_mode_put_get_health(public_client, jarvis_env):
    from app.jarvis import settings_store

    first = await public_client.get("/api/jarvis/settings")
    assert first.status_code == 200
    assert first.json()["talk_mode"] == "computer"

    saved = await public_client.put("/api/jarvis/settings", json={"talk_mode": "terminal"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["talk_mode"] == "terminal"

    got = await public_client.get("/api/jarvis/settings")
    assert got.json()["talk_mode"] == "terminal"

    health = await public_client.get("/api/jarvis/health")
    assert health.status_code == 200
    assert health.json()["talk_mode"] == "terminal"

    lite = await public_client.get("/api/jarvis/health?lite=1")
    assert lite.status_code == 200
    assert lite.json()["talk_mode"] == "terminal"

    settings_store.reset_cache()
    assert settings_store.get_talk_mode() == "terminal"

    back = await public_client.put("/api/jarvis/settings", json={"talk_mode": "computer"})
    assert back.status_code == 200
    assert back.json()["talk_mode"] == "computer"
