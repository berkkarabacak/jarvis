"""Per-request Talk allow picks (yes / ask / no) for hosted Public Talk.

Public Settings cannot persist permission_profile (401 without a key, and a
shared host must not let one visitor change everyone else). The page sends
``allowed`` with /ask and /tools/run. Only keys the hosted computer can honor
are enforced. Unset keys leave the existing profile rules alone.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

# Hosted Talk can actually stop or confirm these. Docs (their folder) and buy
# (shop / send) are not wired on this page — the UI must not look clickable.
HOSTED_ALLOW_KEYS = frozenset({"apps", "files", "computer"})
ALLOW_VALUES = frozenset({"yes", "ask", "no"})

TOOL_ALLOW_GROUP: dict[str, str] = {
    "run_app": "apps",
    "open_path": "apps",
    "write_file": "files",
    "create_excel": "files",
    "organize_folder": "files",
    "home_write": "files",
    "run_powershell": "computer",
    "download_fetch": "computer",
    "release_download": "computer",
    "install": "computer",
}

REFUSE = "He is not allowed to do that."
ASK_FIRST = "He will ask first."

_request_allow: ContextVar[dict[str, str] | None] = ContextVar(
    "talk_allow", default=None
)


def normalize_allowed(raw: Any) -> dict[str, str]:
    """Keep only hosted keys with yes/ask/no. Ignore the rest."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        name = str(key or "").strip().lower()
        mode = str(val or "").strip().lower()
        if name in HOSTED_ALLOW_KEYS and mode in ALLOW_VALUES:
            out[name] = mode
    return out


def set_request_allow(raw: Any) -> Token:
    return _request_allow.set(normalize_allowed(raw) or None)


def reset_request_allow(token: Token) -> None:
    _request_allow.reset(token)


def get_request_allow() -> dict[str, str]:
    return dict(_request_allow.get() or {})


def group_for_tool(tool: str) -> str | None:
    return TOOL_ALLOW_GROUP.get((tool or "").strip())


def talk_allow_mode(tool: str, allowed: dict[str, str] | None = None) -> str | None:
    """yes/ask/no when this tool is gated by a sent pick; else None."""
    group = group_for_tool(tool)
    if not group:
        return None
    picks = allowed if allowed is not None else get_request_allow()
    mode = (picks or {}).get(group)
    if mode in ALLOW_VALUES:
        return mode
    return None


def overlay_decision(
    tool: str,
    decision: Any,
    *,
    confirmed: bool = False,
    allowed: dict[str, str] | None = None,
) -> Any:
    """Apply a sent Talk pick on top of the usual profile decision."""
    from app.jarvis.gateway import GatewayDecision

    mode = talk_allow_mode(tool, allowed)
    if mode is None:
        return decision
    if mode == "no":
        return GatewayDecision(False, False, decision.tier, REFUSE)
    if mode == "ask" and not confirmed:
        return GatewayDecision(False, True, decision.tier, ASK_FIRST)
    return decision


def refuse_ask_payload() -> dict[str, Any]:
    """Mom-simple /ask body when a shortcut is forbidden."""
    return {
        "ok": False,
        "reply": REFUSE,
        "tools_used": [],
        "result": {"ok": False, "error": REFUSE},
        "ui": {"ok": False, "error": REFUSE},
    }


def shortcut_gate(tool: str) -> dict[str, Any] | bool | None:
    """None = run shortcut. False = skip (ask). dict = refuse reply."""
    mode = talk_allow_mode(tool)
    if mode == "no":
        return refuse_ask_payload()
    if mode == "ask":
        return False
    return None
