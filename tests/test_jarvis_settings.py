"""ORCH-322 — Jarvis Settings surface + audit viewer."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

CEO = Path(__file__).resolve().parents[1] / "app" / "static" / "ceo.html"
HTML = CEO.read_text(encoding="utf-8")
START = "<!-- iris-usage-overlay ORCH-313 start -->"
END = "<!-- iris-usage-overlay ORCH-313 end -->"


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret-value-YYYY")
    monkeypatch.setenv("BRIDGE_TOKEN", "bridge-secret-value-ZZZZ")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


@pytest.fixture
async def client(jarvis_env, monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


# ---------------------------------------------------------------- HTML contract


@pytest.fixture(scope="module")
def overlay_block() -> str:
    assert START in HTML and END in HTML
    return HTML[HTML.index(START) : HTML.index(END) + len(END)]


def test_settings_panel_reachable_from_gear(overlay_block: str):
    assert "iu-settings-fab" in overlay_block
    assert "Settings" in overlay_block
    assert "iu-settings-sheet" in overlay_block
    assert "iu-settings-open" in overlay_block
    assert "Close" in overlay_block
    assert "Escape" in overlay_block


def test_single_settings_button_is_top_right(overlay_block: str):
    assert overlay_block.count('id = "iu-settings-fab"') == 1
    assert overlay_block.count("iu-settings-fab") >= 1
    assert 'item("Settings"' not in overlay_block
    assert "left/sidebar Settings" in overlay_block or "top-right" in overlay_block
    assert 'gear.id = "iu-gear"' not in overlay_block
    assert "#iu-gear {" not in overlay_block
    fab = overlay_block[overlay_block.index("#iu-settings-fab {") : overlay_block.index("#iu-settings-fab:focus-visible")]
    assert "right: 16px" in fab
    assert "left: 16px" not in fab
    assert "left:" not in fab
    assert 'settingsFab.textContent = "Settings"' not in overlay_block
    assert 'settingsFab.textContent = "⚙"' in overlay_block
    assert 'setAttribute("aria-label", "Settings")' in overlay_block
    assert 'setAttribute("title", "Settings")' in overlay_block
    assert "border-radius: 50%" in fab
    assert overlay_block.count("var settingsFab") == 1


def test_settings_sheet_is_translucent(overlay_block: str):
    bgs = re.findall(r"background:\s*([^;]+);", overlay_block)
    assert bgs
    for decl in bgs:
        d = decl.strip().lower()
        assert d.startswith("rgba("), decl
        alpha = float(d.rsplit(",", 1)[1].rstrip(") "))
        assert alpha < 0.4, (alpha, decl)


def test_settings_keeps_orch313_panels(overlay_block: str):
    assert "iu-voice" in overlay_block
    assert "iu-wall" in overlay_block
    assert "iu-about" in overlay_block
    assert "iu-usage" in overlay_block
    assert "IrisSettings" in overlay_block


def test_settings_connectors_empty_state(overlay_block: str):
    assert "None yet" in overlay_block


def test_settings_look_speed_control(overlay_block: str):
    assert "look_speed" in overlay_block
    assert "How often I look at the screen" in overlay_block
    assert "Every 30 seconds" in overlay_block
    assert "Every second" in overlay_block
    assert "separate from Fast / Balanced / Smart" in overlay_block


def test_settings_budget_and_quality_controls(overlay_block: str):
    assert "Spending limit" in overlay_block
    assert "Monthly limit in dollars" in overlay_block
    assert "Daily limit in dollars" in overlay_block
    assert "How Jarvis thinks" in overlay_block
    assert "Fast" in overlay_block
    assert "Balanced" in overlay_block
    assert "Smart" in overlay_block
    assert "Always use the same model" in overlay_block
    assert "Connectors" in overlay_block
    assert "None yet" in overlay_block


def test_settings_budget_speed_quality_controls(overlay_block: str):
    assert "Budget" in overlay_block
    assert "Daily cap" in overlay_block
    assert "Monthly cap" in overlay_block
    assert "daily_budget_usd" in overlay_block
    assert "monthly_budget_usd" in overlay_block
    assert "Speed" in overlay_block
    assert "Quality vs price" in overlay_block
    assert "model_preference" in overlay_block
    assert "model_speed" in overlay_block
    assert "Approve wait (seconds)" in overlay_block
    assert "approve_countdown_sec" in overlay_block
    assert "iu-settings-fab" in overlay_block
    assert "shouldOpenSettings" in overlay_block
    assert "persistJarvis" in overlay_block
    assert "persistJarvis({ model_speed:" in overlay_block
    assert "persistJarvis({ look_speed:" in overlay_block
    assert "persistJarvis({ computer_kind:" in overlay_block
    assert "persistJarvis({ realtime_voice:" in overlay_block
    assert "persistJarvis({ permission_profile:" in overlay_block
    assert "quality_vs_price: selectedQuality" in overlay_block
    assert "model_lock: false" in overlay_block
    assert "model_lock:" in overlay_block


def test_settings_calls_expected_apis(overlay_block: str):
    assert "/api/jarvis/settings" in overlay_block
    assert "/api/jarvis/audit/recent" in overlay_block
    assert "/api/jarvis/audit/verify" in overlay_block
    assert "/api/jarvis/mcp/servers" in overlay_block
    assert "innerHTML" not in overlay_block


def test_settings_html_never_embeds_secret_literals():
    # Page must not hardcode env secret values.
    assert "sk-test-openai-secret-value-XXXX" not in HTML
    assert "bridge-secret" not in HTML
    assert "API_SECRET" not in HTML or "API secret" not in HTML.lower()


# ---------------------------------------------------------------- store + profile


def test_settings_store_persists_across_reload(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save(
        {
            "permission_profile": "power",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "realtime_voice": "alloy",
            "daily_budget_usd": 5,
            "monthly_budget_usd": 40,
            "model_preference": "quality",
            "model_speed": "careful",
        }
    )
    settings_store.reset_cache()
    assert settings_store.get_permission_profile() == "power"
    assert settings_store.get_provider() == "openai"
    assert settings_store.get_model() == "gpt-4o-mini"
    assert settings_store.get_realtime_voice() == "alloy"
    assert settings_store.get_daily_budget_usd() == 5.0
    assert settings_store.get_monthly_budget_usd() == 40.0
    assert settings_store.get_model_preference() == "quality"
    assert settings_store.get_model_speed() == "careful"
    path = settings_store.settings_path()
    assert path.is_file()
    assert "jarvis_settings.json" in str(path)


def test_current_profile_consults_store(jarvis_env, monkeypatch):
    from app.jarvis import settings_store
    from app.jarvis.permissions import current_profile, max_auto_tier
    from app.jarvis.permissions import Tier

    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    assert current_profile() == "personal"
    settings_store.save({"permission_profile": "locked"})
    settings_store.reset_cache()
    assert current_profile() == "locked"
    assert max_auto_tier() == Tier.L0


def test_resolve_voice_consults_store(jarvis_env):
    from app.jarvis import settings_store
    from app.jarvis.realtime import resolve_realtime_voice

    settings_store.save({"realtime_voice": "coral"})
    settings_store.reset_cache()
    assert resolve_realtime_voice(None) == "coral"
    assert resolve_realtime_voice("sage") == "sage"  # explicit wins


# ---------------------------------------------------------------- HTTP API


@pytest.mark.asyncio
async def test_get_settings_never_returns_secret_values(client, jarvis_env):
    r = await client.get("/api/jarvis/settings")
    assert r.status_code == 200
    data = r.json()
    blob = json.dumps(data)
    assert "sk-test-openai-secret-value-XXXX" not in blob
    assert "sk-or-test-secret-value-YYYY" not in blob
    assert "bridge-secret-value-ZZZZ" not in blob
    by_name = {s["name"]: s["configured"] for s in data["secrets"]}
    assert by_name["OPENAI_API_KEY"] is True
    assert by_name["OPENROUTER_API_KEY"] is True
    assert by_name["BRIDGE_TOKEN"] is True
    assert data["permission_profile"] == "personal"
    assert data["connectors_empty"] == "None yet"
    assert data["model_preference"] in {"cheap_fast", "balanced", "quality"}
    assert data["model_speed"] in {"fast", "balanced", "careful"}
    assert isinstance(data["daily_budget_usd"], (int, float))
    assert isinstance(data["monthly_budget_usd"], (int, float))
    assert data["connectors"] == []
    # Plain-language blurbs present
    ids = {p["id"] for p in data["permission_profiles"]}
    assert ids == {"locked", "personal", "power"}
    assert all(p.get("allows") for p in data["permission_profiles"])


@pytest.mark.asyncio
async def test_put_settings_persists_and_audits_profile_change(client, jarvis_env):
    from app.jarvis.permissions import current_profile
    from app.jarvis import settings_store

    r = await client.put(
        "/api/jarvis/settings",
        json={
            "permission_profile": "power",
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4",
            "realtime_voice": "echo",
            "daily_budget_usd": 3.5,
            "monthly_budget_usd": 25,
            "model_preference": "balanced",
            "model_speed": "fast",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["permission_profile"] == "power"
    assert data["model"] == "anthropic/claude-sonnet-4"
    assert data["realtime_voice"] == "echo"
    assert data["daily_budget_usd"] == 3.5
    assert data["monthly_budget_usd"] == 25.0
    assert data["model_preference"] == "balanced"
    assert data["model_speed"] == "fast"
    assert "sk-test" not in json.dumps(data)

    settings_store.reset_cache()
    assert current_profile() == "power"

    recent = await client.get("/api/jarvis/audit/recent?n=20")
    assert recent.status_code == 200
    entries = recent.json()["entries"]
    assert entries, "expected an audit entry for the settings change"
    joined = json.dumps(entries)
    assert "permission_profile" in joined or "settings.update" in joined
    assert "sk-test-openai-secret-value-XXXX" not in joined
    assert "bridge-secret-value-ZZZZ" not in joined


@pytest.mark.asyncio
async def test_put_settings_rejects_bad_profile(client, jarvis_env):
    r = await client.put(
        "/api/jarvis/settings",
        json={"permission_profile": "godmode"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_audit_verify_endpoint(client, jarvis_env):
    # Seed a clean chain via a settings write.
    await client.put(
        "/api/jarvis/settings",
        json={"permission_profile": "personal"},
    )
    r = await client.post("/api/jarvis/audit/verify")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["verify_across_rotation"]["ok"] is True
    assert data["verify"]["ok"] is True


@pytest.mark.asyncio
async def test_put_accepts_api_secret_header(client, jarvis_env):
    r = await client.put(
        "/api/jarvis/settings",
        json={"realtime_voice": "verse"},
        headers={"X-Api-Key": "test-secret-at-least-32-chars-long!!"},
    )
    assert r.status_code == 200
    assert r.json()["realtime_voice"] == "verse"


@pytest.mark.asyncio
async def test_public_view_redacts_even_if_store_poisoned(jarvis_env, monkeypatch):
    """If a secret somehow lands in the JSON file, GET must not echo it."""
    from app.jarvis import settings_store

    path = settings_store.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "permission_profile": "personal",
                "model": "sk-proj-should-not-leak-abcdefghijklmnop",
                "provider": "openrouter",
                "realtime_voice": "marin",
            }
        ),
        encoding="utf-8",
    )
    settings_store.reset_cache()
    view = settings_store.public_view()
    blob = json.dumps(view)
    assert "sk-proj-should-not-leak-abcdefghijklmnop" not in blob


def test_model_suggestions_are_current_catalog_ids(jarvis_env):
    from app.jarvis import settings_store

    view = settings_store.public_view()
    suggestions = view["model_suggestions"]
    assert "deepseek/deepseek-v4-pro-0813" in suggestions
    assert "z-ai/glm-5.2" in suggestions
    assert "z-ai/glm-5.3" not in suggestions
    assert all("gpt-4.1" not in mid for mid in suggestions)
