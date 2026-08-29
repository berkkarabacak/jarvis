"""ORCH-380 / ORCH-386 — budget caps persist and remaining spend is enforced."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("JARVIS_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("JARVIS_MONTHLY_BUDGET_USD", raising=False)
    from app.jarvis import settings_store

    settings_store.reset_cache()
    (tmp_path / "Memory").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_default_budget_caps(ws: Path):
    from app.jarvis.settings_store import get_daily_budget_usd, get_monthly_budget_usd

    assert get_daily_budget_usd() == 2.0
    assert get_monthly_budget_usd() == 20.0


def test_spend_respects_daily_cap(ws: Path):
    from app.jarvis import settings_store
    from app.jarvis.spend import public_spend, record_spend, remaining_budget_usd

    settings_store.save({"daily_budget_usd": 1.0, "monthly_budget_usd": 10.0}, root=ws)
    settings_store.reset_cache()
    record_spend(0.4, root=ws)
    assert remaining_budget_usd(ws) == pytest.approx(0.6)
    record_spend(0.7, root=ws)
    assert remaining_budget_usd(ws) == 0.0
    view = public_spend(ws)
    assert view["spent_today_usd"] == pytest.approx(1.1)
    assert view["remaining_budget_usd"] == 0.0


def test_settings_preference_drives_router(ws: Path, monkeypatch: pytest.MonkeyPatch):
    from app.jarvis import settings_store
    from app.jarvis.model_router import route_model

    monkeypatch.delenv("JARVIS_MODEL_PREFERENCE", raising=False)
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    settings_store.save({"model_preference": "quality"}, root=ws)
    settings_store.reset_cache()
    choice = route_model(goal="How much free disk space do I have?", workspace_root=ws)
    assert choice.preference == "quality"
    assert choice.metadata.get("pool") == "high_iq"
