"""Each setting the Talk / CEO UI exposes must persist and apply.

Keys are read from the live HTML, not invented here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.model_router import apply_model_speed, route_model
from app.jarvis.realtime import resolve_realtime_voice
from app.jarvis.screen_loop import normalize_look_speed

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
SCREEN_PAGE = ROOT / "deploy" / "jarvis-public" / "screen.html"
CEO = ROOT / "app" / "static" / "ceo.html"

SECRET = "test-secret-at-least-32-chars-long!!"


def _public_js() -> str:
    page = PUBLIC_PAGE.read_text(encoding="utf-8")
    return page.split("<script>", 1)[1].rsplit("</script>", 1)[0]


def _ceo_overlay() -> str:
    html = CEO.read_text(encoding="utf-8")
    start = "<!-- iris-usage-overlay ORCH-313 start -->"
    end = "<!-- iris-usage-overlay ORCH-313 end -->"
    assert start in html and end in html
    return html[html.index(start) : html.index(end) + len(end)]


def _ui_save_keys(source: str, fn: str) -> set[str]:
    keys: set[str] = set()
    for match in re.finditer(rf"{fn}\(\s*\{{(.*?)\}}", source, re.S):
        blob = match.group(1)
        for key in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", blob):
            if key not in {"function", "var", "const", "let"}:
                keys.add(key)
    return keys


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "deepseek/deepseek-v4-flash-0731")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    monkeypatch.delenv("JARVIS_DISABLE_MODEL_ROUTER", raising=False)
    monkeypatch.delenv("JARVIS_MODEL_PREFERENCE", raising=False)

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store
    from app.jarvis.model_router import reset_state_for_tests
    from app.jarvis.openrouter_leaders import reset_leaders_cache_for_tests

    gw._gateway = None
    settings_store.reset_cache()
    reset_state_for_tests(ws)
    reset_leaders_cache_for_tests()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_leaders_cache_for_tests()


@pytest.fixture
async def client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


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


def test_public_talk_cards_wire_persist_for_every_control():
    page = PUBLIC_PAGE.read_text(encoding="utf-8")
    js = _public_js()
    assert "data-q=" in page
    assert "data-speed=" in page
    assert "data-voice=" in page
    assert "data-talk-speed=" in page
    assert "data-allow=" in page
    assert "data-picture=" in page
    assert "text-smaller" in page
    assert "helper-picks" in page

    server_keys = _ui_save_keys(js, "saveTalkSettings")
    assert "quality_vs_price" in server_keys
    assert "model_speed" in server_keys
    assert "model" in server_keys
    assert "model_lock" in server_keys
    assert "saveTalkSettings({ quality_vs_price: q, model_lock: false })" in js

    assert "rememberTalkSettings" in js
    assert "localStorage.setItem(PREFS_KEY" in js
    assert "prefs.voice" in js
    assert "prefs.talkSpeed" in js
    assert "prefs.allowed" in js
    assert "prefs.picture" in js
    assert "prefs.textScale" in js
    assert "applyTalkRateAll" in js
    assert "applyTextScale" in js
    assert "applyPicture" in js
    assert "voice: prefs.voice" in js
    assert "{ text: text, voice: prefs.voice }" in js


def test_public_screen_applies_picture_pref():
    page = SCREEN_PAGE.read_text(encoding="utf-8")
    assert "jarvis.talk.prefs" in page
    assert "picturePref" in page
    assert "quality=" in page
    assert "compression=" in page


def test_ceo_controls_persist_each_field_they_show():
    overlay = _ceo_overlay()
    keys = _ui_save_keys(overlay, "persistJarvis")
    assert "quality_vs_price" in keys
    assert "model_preference" in keys
    assert re.search(
        r"persistJarvis\(\{\s*quality_vs_price:\s*selectedQuality,"
        r".*?model_lock:\s*false",
        overlay,
        re.S,
    )
    assert "model_speed" in keys
    assert "look_speed" in keys
    assert "realtime_voice" in keys
    assert "permission_profile" in keys
    assert "provider" in keys
    assert "monthly_budget_usd" in keys
    assert "daily_budget_usd" in keys
    assert "approve_countdown_sec" in keys
    assert "model_lock" in keys
    assert "Could not save" in overlay
    assert "res.j.detail" not in overlay


def test_model_speed_shifts_router_pool():
    assert apply_model_speed("balanced", "balanced") == "balanced"
    assert apply_model_speed("balanced", "fast") == "cheap_capable"
    assert apply_model_speed("balanced", "careful") == "high_iq"
    assert apply_model_speed("cheap_free_ok", "fast") == "cheap_free_ok"
    assert apply_model_speed("high_iq", "careful") == "high_iq"


def test_saved_model_speed_applies_on_route(jarvis_env):
    from app.jarvis import settings_store

    goal = "Create a playable tetris as one HTML file with write_file"
    settings_store.save({"quality_vs_price": "balanced", "model_speed": "fast"})
    settings_store.reset_cache()
    fast = route_model(goal=goal, workspace_root=jarvis_env)
    settings_store.save({"model_speed": "careful"})
    settings_store.reset_cache()
    careful = route_model(goal=goal, workspace_root=jarvis_env)
    assert settings_store.get_model_speed() == "careful"
    assert "model_speed=fast" in fast.reason
    assert "model_speed=careful" in careful.reason
    assert fast.metadata["model_speed"] == "fast"
    assert careful.metadata["model_speed"] == "careful"
    assert fast.metadata["pool"] != careful.metadata["pool"]


@pytest.mark.asyncio
async def test_public_host_persists_every_talk_server_card(public_client, jarvis_env):
    from app.jarvis import settings_store

    js = _public_js()
    keys = _ui_save_keys(js, "saveTalkSettings")
    assert keys == {"quality_vs_price", "model_speed", "model", "model_lock", "computer_kind"}

    quality = await public_client.put(
        "/api/jarvis/settings",
        json={"quality_vs_price": "smart"},
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["quality_vs_price"] == "smart"

    speed = await public_client.put(
        "/api/jarvis/settings",
        json={"model_speed": "fast"},
    )
    assert speed.status_code == 200, speed.text
    assert speed.json()["model_speed"] == "fast"

    helper = "deepseek/deepseek-v4-flash-0731"
    model = await public_client.put(
        "/api/jarvis/settings",
        json={"model": helper, "model_lock": True},
    )
    assert model.status_code == 200, model.text
    assert model.json()["model"] == helper
    assert model.json()["model_lock"] is True

    prefixed = await public_client.put(
        "/jarvis/api/jarvis/settings",
        json={"quality_vs_price": "fast", "model_speed": "careful"},
    )
    assert prefixed.status_code == 200, prefixed.text
    assert prefixed.json()["quality_vs_price"] == "fast"
    assert prefixed.json()["model_speed"] == "careful"

    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "fast"
    assert settings_store.get_model_speed() == "careful"
    assert settings_store.get_model() == helper
    assert settings_store.get_model_lock() is True

    health = await public_client.get("/jarvis/api/jarvis/health")
    assert health.status_code == 200
    sheet = health.json()
    assert sheet["quality_vs_price"] == "fast"
    assert sheet["model_speed"] == "careful"
    assert sheet["model"] == helper

    denied = await public_client.put(
        "/api/jarvis/settings",
        json={"daily_budget_usd": 9, "realtime_voice": "echo"},
    )
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_quality_card_unlocks_after_helper_lock(public_client, jarvis_env):
    """Quick / Everyday / Deep must clear a prior helper lock so the router listens."""
    from app.jarvis import settings_store

    js = _public_js()
    overlay = _ceo_overlay()
    assert "saveTalkSettings({ quality_vs_price: q, model_lock: false })" in js
    assert re.search(
        r"persistJarvis\(\{\s*quality_vs_price:\s*selectedQuality,"
        r".*?model_lock:\s*false",
        overlay,
        re.S,
    )

    helper = "deepseek/deepseek-v4-flash-0731"
    locked = await public_client.put(
        "/api/jarvis/settings",
        json={"model": helper, "model_lock": True},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["model_lock"] is True

    leftover = await public_client.put(
        "/api/jarvis/settings",
        json={"quality_vs_price": "smart"},
    )
    assert leftover.status_code == 200, leftover.text
    settings_store.reset_cache()
    assert leftover.json()["quality_vs_price"] == "smart"
    assert settings_store.get_model_lock() is True
    still_pinned = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert still_pinned.pinned is True
    assert still_pinned.model == helper

    unlocked = await public_client.put(
        "/api/jarvis/settings",
        json={"quality_vs_price": "smart", "model_lock": False},
    )
    assert unlocked.status_code == 200, unlocked.text
    body = unlocked.json()
    assert body["quality_vs_price"] == "smart"
    assert body["model_lock"] is False

    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_model_lock() is False
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert choice.pinned is False
    assert choice.preference == "quality"
    assert choice.model != helper


@pytest.mark.asyncio
async def test_ceo_ui_fields_persist_and_apply(client, jarvis_env):
    from app.jarvis import settings_store
    from app.jarvis.permissions import current_profile
    from app.jarvis.settings_store import look_speed_interval_seconds

    overlay = _ceo_overlay()
    keys = _ui_save_keys(overlay, "persistJarvis")
    body_fn = overlay.split("function allSettingsBody()", 1)[1].split("return body;", 1)[0]
    keys |= set(re.findall(r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)\s*:", body_fn))
    samples = {
        "permission_profile": "power",
        "provider": "openai",
        "realtime_voice": "coral",
        "look_speed": "10s",
        "quality_vs_price": "smart",
        "model_speed": "careful",
        "model_preference": "quality",
        "monthly_budget_usd": 35,
        "daily_budget_usd": 4,
        "approve_countdown_sec": 25,
        "model_lock": False,
        "computer_kind": "linux",
    }
    missing = [k for k in samples if k not in keys]
    assert missing == [], missing

    for key, value in samples.items():
        r = await client.put("/api/jarvis/settings", json={key: value})
        assert r.status_code == 200, (key, r.text)
        body = r.json()
        assert body["ok"] is True
        if key == "model_preference":
            assert body["model_preference"] == "quality"
            assert body["quality_vs_price"] == "smart"
        elif key != "model_lock":
            assert body[key] == value

    settings_store.reset_cache()
    assert current_profile() == "power"
    assert settings_store.get_provider() == "openai"
    assert settings_store.get_realtime_voice() == "coral"
    assert resolve_realtime_voice(None) == "coral"
    assert settings_store.get_look_speed() == "10s"
    assert look_speed_interval_seconds() == 10.0
    assert normalize_look_speed("10s") == "10s"
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_model_preference() == "quality"
    assert settings_store.get_model_speed() == "careful"
    assert settings_store.get_monthly_budget_usd() == 35.0
    assert settings_store.get_daily_budget_usd() == 4.0
    assert settings_store.get_approve_countdown_sec() == 25

    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert choice.preference == "quality"
    assert choice.metadata["model_speed"] == "careful"

    again = await client.get("/api/jarvis/settings")
    assert again.status_code == 200
    view = again.json()
    assert view["permission_profile"] == "power"
    assert view["realtime_voice"] == "coral"
    assert view["look_speed"] == "10s"
    assert view["quality_vs_price"] == "smart"
    assert view["model_speed"] == "careful"
    assert view["approve_countdown_sec"] == 25


def test_jarvis_keys_do_not_go_through_config_apply_updates():
    from app.config import Settings

    s = Settings(api_secret="x" * 40)
    with pytest.raises(ValueError, match="unknown settings fields"):
        s.apply_updates({"model_speed": "fast", "quality_vs_price": "smart"})
