"""Spend helpers for Settings (ORCH-380 / ORCH-383 / ORCH-386).

Caps and the ledger live in the one shared settings file
``Memory/jarvis_settings.json``. This module is a thin reader so the
Windows app and older imports do not invent a second store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def spend_path(root: Path | None = None) -> Path:
    from app.jarvis.settings_store import settings_path

    return settings_path(root)


def load_spend(root: Path | None = None) -> dict[str, Any]:
    from app.jarvis.settings_store import budget_status

    status = budget_status(root)
    return {
        "day": "",
        "month": "",
        "daily_spent_usd": status["daily_spent_usd"],
        "monthly_spent_usd": status["monthly_spent_usd"],
    }


def record_spend(usd: float, root: Path | None = None) -> dict[str, Any]:
    from app.jarvis.settings_store import record_spend as _record

    _record(usd, root=root)
    return load_spend(root)


def remaining_budget_usd(root: Path | None = None) -> float:
    from app.jarvis.settings_store import budget_status

    rem = budget_status(root).get("remaining_usd")
    return 0.0 if rem is None else float(rem)


def public_spend(root: Path | None = None) -> dict[str, Any]:
    from app.jarvis.settings_store import budget_status

    status = budget_status(root)
    return {
        "spent_today_usd": status["daily_spent_usd"],
        "spent_month_usd": status["monthly_spent_usd"],
        "remaining_budget_usd": remaining_budget_usd(root),
    }
