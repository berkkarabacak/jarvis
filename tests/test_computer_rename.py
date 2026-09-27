"""Rename a registered computer without changing its machine id."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-secret-at-least-32-chars-long!!"


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("JARVIS_COMPUTER_KIND", raising=False)
    from app.jarvis import settings_store

    settings_store.reset_cache()
    yield ws
    settings_store.reset_cache()


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


def test_default_label_stays_when_unset(jarvis_env):
    from app.jarvis.settings_store import computer_display_name, public_view

    assert computer_display_name("linux") == "Linux"
    assert computer_display_name("android") == "Android"
    view = public_view()
    rows = {row["id"]: row for row in view["computers"]}
    assert rows["linux"]["hostname"] == "jarvis-computer"
    assert rows["linux"]["label"] == "Linux"
    assert rows["linux"]["renamed"] is False
    assert rows["android"]["hostname"] == "jarvis-android"
    assert view["computer_names"] == {}
    kinds = {row["id"]: row for row in view["computer_kinds"]}
    assert kinds["linux"]["display_name"] == "Linux"
    assert kinds["android"]["hostname"] == "jarvis-android"


def test_rename_persists_and_does_not_touch_the_other_computer(jarvis_env):
    from app.jarvis.computer import public_computer_status
    from app.jarvis.settings_store import (
        computer_display_name,
        get_computer_names,
        list_computers,
        reset_cache,
        save,
    )

    save({"computer_names": {"linux": "  Office PC  "}})
    assert get_computer_names() == {"linux": "Office PC"}
    assert computer_display_name("linux") == "Office PC"
    assert computer_display_name("android") == "Android"
    save({"computer_names": {"jarvis-android": "Phone box"}})
    names = get_computer_names()
    assert names["linux"] == "Office PC"
    assert names["android"] == "Phone box"
    rows = {row["id"]: row for row in list_computers()}
    assert rows["linux"]["hostname"] == "jarvis-computer"
    assert rows["android"]["hostname"] == "jarvis-android"
    assert rows["linux"]["id"] == "linux"

    reset_cache()
    assert get_computer_names()["linux"] == "Office PC"
    assert computer_display_name("android") == "Phone box"
    status = public_computer_status()
    assert status["id"] == "linux"
    assert status["hostname"] == "jarvis-computer"
    assert status["label"] == "Office PC"
    assert status["display_name"] == "Office PC"


def test_display_name_validation(jarvis_env):
    from app.jarvis.settings_store import normalize_computer_display_name, validate_update

    assert normalize_computer_display_name("Berk's PC") == "Berk's PC"
    assert normalize_computer_display_name("Office-PC_2") == "Office-PC_2"
    assert normalize_computer_display_name("Mom's laptop (upstairs)") == "Mom's laptop (upstairs)"
    assert normalize_computer_display_name("Büro #2") == "Büro #2"
    for bad in ("", "   ", "\n\t", "a" * 65, "ok\x00pc"):
        with pytest.raises(ValueError):
            normalize_computer_display_name(bad)
    with pytest.raises(ValueError):
        validate_update({"computer_names": {"windows": "Laptop"}})
    with pytest.raises(ValueError):
        validate_update({"computer_names": {"linux": "   "}})
    parsed = validate_update({"computer_names": {"jarvis-computer": " Desk "}})
    assert parsed["computer_names"]["linux"] == "Desk"


@pytest.mark.asyncio
async def test_settings_api_rename_round_trip(client, jarvis_env):
    from app.jarvis.settings_store import get_computer_kind, get_computer_names, reset_cache

    headers = {"X-Api-Key": SECRET}
    saved = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"computer_names": {"linux": "Office PC"}},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["computer_names"]["linux"] == "Office PC"
    linux = next(row for row in body["computers"] if row["id"] == "linux")
    android = next(row for row in body["computers"] if row["id"] == "android")
    assert linux["display_name"] == "Office PC"
    assert linux["hostname"] == "jarvis-computer"
    assert android["display_name"] == "Android"
    assert android["hostname"] == "jarvis-android"

    other = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"computer_names": {"android": "Kitchen tablet"}},
    )
    assert other.status_code == 200, other.text
    names = other.json()["computer_names"]
    assert names["linux"] == "Office PC"
    assert names["android"] == "Kitchen tablet"

    blank = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"computer_names": {"linux": "   "}},
    )
    assert blank.status_code == 400
    assert "empty" in str(blank.json().get("detail") or "").lower()

    unknown = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"computer_names": {"windows": "Mine"}},
    )
    assert unknown.status_code == 400

    reset_cache()
    again = await client.get("/api/jarvis/settings", headers=headers)
    assert again.json()["computer_names"]["linux"] == "Office PC"
    assert get_computer_names()["android"] == "Kitchen tablet"
    assert get_computer_kind() == "linux"

    health = await client.get("/api/jarvis/health")
    assert health.json()["computer"]["display_name"] == "Office PC"
    assert health.json()["computer"]["hostname"] == "jarvis-computer"

    switched = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"computer_kind": "android"},
    )
    assert switched.status_code == 200
    assert switched.json()["computer_names"]["linux"] == "Office PC"
    health = await client.get("/api/jarvis/health")
    assert health.json()["computer"]["label"] == "Kitchen tablet"
    assert health.json()["computer"]["hostname"] == "jarvis-android"
    assert health.json()["computer"]["id"] == "android"


def test_rename_controls_are_on_the_computer_surfaces():
    desktop = (ROOT / "app" / "static" / "desktop.html").read_text(encoding="utf-8")
    assert 'id="computers"' in desktop
    assert 'id="pc-name"' in desktop
    assert "computer_names" in desktop
    assert "Live Computer" in desktop

    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert "computer_names" in ceo
    assert "Rename" in ceo
    assert "persistJarvis({ computer_kind: selectedComputer })" in ceo

    public = (ROOT / "deploy" / "jarvis-public" / "index.html").read_text(encoding="utf-8")
    assert 'data-rename-computer="linux"' in public
    assert 'data-rename-computer="android"' in public
    assert "saveTalkSettings({ computer_names: names })" in public
    assert 'data-computer="linux"' in public

    right = (ROOT / "desktop-web" / "components" / "desktop" / "RightPane.tsx").read_text(
        encoding="utf-8"
    )
    shell = (ROOT / "desktop-web" / "components" / "desktop" / "Shell.tsx").read_text(
        encoding="utf-8"
    )
    assert 'id="computers"' in right
    assert 'id="pc-name"' in right
    assert "Rename" in right
    assert "renameComputer" in shell
    assert "computersFromSettings" in shell
