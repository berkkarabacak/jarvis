"""Server-side Talk Terminal mode — no computer tools, no screen start.

Computer mode is unchanged. Terminal is chat/CLI only: simple Q&A, helpers,
and spawn_child research still run. Desktop drivers do not.
"""

from __future__ import annotations

from typing import Any

# Tools that drive the PC / screen. Gateway activate_desktop_backend uses
# DESKTOP_TOOLS (same set as realtime PUBLIC_LOOK_TOOLS). COMPUTER_TOOLS
# adds nearby desktop drivers the ask shortcuts also use.
DESKTOP_TOOLS = frozenset(
    {
        "see_screen",
        "screenshot",
        "keys",
        "click",
        "type",
        "scroll",
        "focus_app",
        "run_app",
    }
)
COMPUTER_TOOLS = DESKTOP_TOOLS | {
    "open_path",
    "close_windows",
    "confirm_screen_action",
    "install",
}

TERMINAL_SCREEN_REPLY = "Switch to Computer mode to use the screen."


def talk_mode_is_terminal() -> bool:
    from app.jarvis.settings_store import get_talk_mode

    return get_talk_mode() == "terminal"


def blocks_computer_tool(name: str) -> bool:
    return talk_mode_is_terminal() and (name or "").strip() in COMPUTER_TOOLS


def refuse_computer_decision(tier: str = "L1") -> Any:
    from app.jarvis.gateway import GatewayDecision

    return GatewayDecision(False, False, tier, TERMINAL_SCREEN_REPLY)


def refuse_computer_tool_result(tool: str) -> dict[str, Any] | None:
    """Gateway / Realtime / run_tool early result. None when allowed."""
    if not blocks_computer_tool(tool):
        return None
    return {
        "ok": False,
        "blocked": True,
        "error": TERMINAL_SCREEN_REPLY,
        "message": TERMINAL_SCREEN_REPLY,
        "tool": (tool or "").strip(),
        "tier": "L1",
    }


def refuse_computer_ask_payload() -> dict[str, Any] | None:
    """Mom-simple /ask body when Terminal must not touch the PC. None if Computer."""
    if not talk_mode_is_terminal():
        return None
    return {
        "ok": False,
        "reply": TERMINAL_SCREEN_REPLY,
        "tools_used": [],
        "result": {
            "ok": False,
            "blocked": True,
            "error": TERMINAL_SCREEN_REPLY,
        },
        "ui": {
            "ok": False,
            "blocked": True,
            "error": TERMINAL_SCREEN_REPLY,
        },
    }
