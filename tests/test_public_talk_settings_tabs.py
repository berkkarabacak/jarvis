"""Public Talk Settings: exactly 5 working tabs, every click PUTs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
SECRET = "test-secret-at-least-32-chars-long!!"

REQUIRED_TABS = (
    ("cost", "Cost"),
    ("talk", "Talk"),
    ("brain", "Brain"),
    ("computer", "Computer"),
    ("about", "About"),
)
OLD_RAIL_NAMES = ("Model", "Speed", "Voice", "Allowed", "Memory", "Screen")


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _js() -> str:
    return _page().split("<script>")[-1].rsplit("</script>", 1)[0]


def _settings_tabs(page: str) -> list[tuple[str, str]]:
    blob = page.split("const SETTINGS_TABS = [", 1)[1].split("];", 1)[0]
    return [
        (m.group(1), m.group(2))
        for m in re.finditer(r'\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)"\s*\}', blob)
    ]


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


def test_exactly_five_settings_tabs_and_panels():
    page = _page()
    tabs = _settings_tabs(page)
    assert tabs == list(REQUIRED_TABS)
    assert len(tabs) == 5
    rail = page.split("const SETTINGS_TABS = [", 1)[1].split("];", 1)[0]
    for old in OLD_RAIL_NAMES:
        assert f'label: "{old}"' not in rail
        assert f'id: "{old.lower()}"' not in rail
    for tab_id, _label in REQUIRED_TABS:
        assert f'id="tab-{tab_id}"' in page
        assert f'data-settings-panel="{tab_id}"' in page
    for leftover in ("tab-model", "tab-speed", "tab-voice", "tab-allowed", "tab-memory", "tab-screen"):
        assert f'id="{leftover}"' not in page
        assert f'data-settings-panel="{leftover.removeprefix("tab-")}"' not in page


def test_talk_brain_computer_clicks_put_mapped_fields():
    js = _js()
    talk = js.split("voicePicksEl.querySelectorAll(\"[data-voice]\")", 1)[1]
    talk = talk.split("lookPicksEl", 1)[0]
    assert "saveTalkSettings({ realtime_voice: realtimeVoice() })" in talk
    assert "saveTalkSettings({ talk_speed: speed })" in talk
    assert "TALK_VOICES" in js
    assert 'warm: "marin"' in js
    assert 'clear: "alloy"' in js
    assert 'deep: "echo"' in js

    brain_q = js.split("modelPicksEl.querySelectorAll(\"[data-q]\")", 1)[1]
    brain_q = brain_q.split("qualityEl", 1)[0]
    assert "saveTalkSettings({ quality_vs_price: q, model_lock: false })" in brain_q
    brain_speed = js.split("qualityEl.querySelectorAll(\"[data-speed]\")", 1)[1]
    brain_speed = brain_speed.split("computerPicksEl", 1)[0]
    assert "saveTalkSettings({ model_speed: speed })" in brain_speed
    assert "saveTalkSettings({ model: id, model_lock: true })" in js

    computer = js.split("computerPicksEl.querySelectorAll(\"[data-computer]\")", 1)[1]
    assert "saveTalkSettings({ computer_kind: kind })" in computer
    assert "saveTalkSettings({ look_speed: look })" in js
    assert "saveTalkSettings({ permission_profile: prefs.permissionProfile })" in js

    save_fn = js.split("async function saveTalkSettings", 1)[1].split("function pinLog", 1)[0]
    assert 'method: "PUT"' in save_fn
    assert "/api/jarvis/settings" in save_fn
    assert "loadTalkSettings()" in save_fn
    load_fn = js.split("async function loadTalkSettings", 1)[1].split("async function saveTalkSettings", 1)[0]
    assert "/api/jarvis/settings" in load_fn
    assert "paintSheet(data)" in load_fn


def test_voice_alias_maps_to_openai_ids():
    js = _js()
    assert 'const TALK_VOICES = { warm: "marin", clear: "alloy", deep: "echo" }' in js
    visible = _page().split("<script>", 1)[0].lower()
    assert "marin" not in visible
    assert "alloy" not in visible
    assert "echo" not in visible


@pytest.mark.asyncio
async def test_public_talk_settings_put_get_roundtrip(public_client, jarvis_env):
    from app.jarvis import settings_store

    samples = {
        "realtime_voice": "echo",
        "talk_speed": "quick",
        "quality_vs_price": "smart",
        "model_speed": "careful",
        "computer_kind": "android",
        "look_speed": "10s",
        "permission_profile": "locked",
    }
    for key, value in samples.items():
        saved = await public_client.put("/api/jarvis/settings", json={key: value})
        assert saved.status_code == 200, (key, saved.text)
        assert saved.json()[key] == value
        got = await public_client.get("/api/jarvis/settings")
        assert got.status_code == 200
        assert got.json()[key] == value
        health = await public_client.get("/api/jarvis/health")
        assert health.status_code == 200
        assert health.json()[key] == value

    settings_store.reset_cache()
    assert settings_store.get_realtime_voice() == "echo"
    assert settings_store.get_talk_speed() == "quick"
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_model_speed() == "careful"
    assert settings_store.get_computer_kind() == "android"
    assert settings_store.get_look_speed() == "10s"
    assert settings_store.get_permission_profile() == "locked"

    again = await public_client.get("/jarvis/api/jarvis/settings")
    assert again.status_code == 200
    body = again.json()
    for key, value in samples.items():
        assert body[key] == value
    assert "spent_month_usd" in body
    assert "remaining_budget_usd" in body
    assert SECRET not in again.text

    denied = await public_client.put(
        "/api/jarvis/settings",
        json={"monthly_budget_usd": 99},
    )
    assert denied.status_code == 401
