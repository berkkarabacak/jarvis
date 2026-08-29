"""Permission tiers L0-L5 for Jarvis tools ==GRoK== (ORCH-245)."""

from __future__ import annotations

import os
from enum import IntEnum
from typing import Iterable


class Tier(IntEnum):
    L0 = 0  # read facts (disk, system)
    L1 = 1  # workspace read/write
    L2 = 2  # user profile folders
    L3 = 3  # shell / apps
    L4 = 4  # UI automation (future)
    L5 = 5  # destructive


# Minimum tier required to run each tool
TOOL_TIERS: dict[str, Tier] = {
    "disk_space": Tier.L0,
    "get_disk_space": Tier.L0,
    "list_github_repos": Tier.L0,
    "get_github_repos": Tier.L0,
    "github_repos": Tier.L0,
    "system_info": Tier.L0,
    "recall_memories": Tier.L0,
    "list_dir": Tier.L1,
    "read_file": Tier.L1,
    "write_file": Tier.L1,
    "create_excel": Tier.L1,
    "organize_folder": Tier.L1,
    "screenshot": Tier.L1,
    "see_screen": Tier.L1,
    "click": Tier.L1,
    "type": Tier.L1,
    "keys": Tier.L1,
    "scroll": Tier.L1,
    "focus_app": Tier.L1,
    "confirm_screen_action": Tier.L0,
    "remember": Tier.L1,
    "forget_memory": Tier.L1,
    "save_mission_summary": Tier.L1,
    "dispatch_prime": Tier.L1,
    "spawn_child": Tier.L0,
    "message_child": Tier.L0,
    "wait_child": Tier.L0,
    "download_fetch": Tier.L2,
    "release_download": Tier.L2,
    "home_list": Tier.L2,
    "home_read": Tier.L2,
    "home_write": Tier.L2,
    "run_powershell": Tier.L3,
    "open_path": Tier.L3,
    "run_app": Tier.L3,
    "confirm_action": Tier.L0,
    "confirm_pending": Tier.L0,
}

# ORCH-368 / ORCH-372: click/type/scroll/focus_app are normal tools. No confirm/nonce.
# ORCH-373: looking is a normal tool, no confirm/nonce.
# ORCH-391: keys is the same — real shortcuts, no confirm/nonce.
NO_CONFIRM_TOOLS: frozenset[str] = frozenset(
    {"click", "type", "keys", "scroll", "focus_app", "screenshot", "see_screen"}
)


def skips_confirm(name: str) -> bool:
    return (name or "").strip() in NO_CONFIRM_TOOLS


PROFILE_MAX_AUTO: dict[str, Tier] = {
    "locked": Tier.L0,
    "personal": Tier.L2,
    "power": Tier.L3,
}


def current_profile() -> str:
    """Active permission profile: durable settings store, else env, else personal."""
    try:
        from app.jarvis.settings_store import get_permission_profile

        return get_permission_profile()
    except Exception:
        p = (os.environ.get("JARVIS_PERMISSION_PROFILE") or "personal").strip().lower()
        return p if p in PROFILE_MAX_AUTO else "personal"


def max_auto_tier(profile: str | None = None) -> Tier:
    return PROFILE_MAX_AUTO.get((profile or current_profile()).lower(), Tier.L2)


def bridge_max_auto_tier() -> Tier:
    raw = (os.environ.get("BRIDGE_MAX_TIER_AUTO") or "").strip()
    if raw.upper().startswith("L") and raw[1:].isdigit():
        return Tier(min(5, max(0, int(raw[1:]))))
    # default bridge allows workspace + home folder writes (L2); shell still needs confirm
    env = (os.environ.get("BRIDGE_MAX_TIER_AUTO") or "L2").strip().upper()
    try:
        return Tier[env] if env in Tier.__members__ else Tier.L1
    except Exception:
        return Tier.L1


def tool_tier(name: str) -> Tier:
    """Resolve tier for built-in or discovered MCP tools.

    Built-ins come from TOOL_TIERS. MCP tools (``mcp.<server>.<tool>``) must
    have an explicit tier in the MCP registry — never a silent default for
    unknown MCP names (those are rejected at the gateway). Unknown non-MCP
    names still fall back to L5 for denylist/authorize messaging.
    """
    raw = (name or "").strip()
    if raw.startswith("mcp."):
        try:
            from app.jarvis.mcp_registry import mcp_tool_tier

            tier = mcp_tool_tier(raw)
            if tier is not None:
                return tier
        except Exception:
            pass
        # Unknown MCP tool — treat as L5 for messaging; gateway denies dispatch.
        return Tier.L5
    return TOOL_TIERS.get(raw, Tier.L5)


def is_known_tool(name: str) -> bool:
    """True when the gateway may authorize the name (built-in or MCP registry)."""
    raw = (name or "").strip()
    if raw in TOOL_TIERS:
        return True
    if raw.startswith("mcp."):
        try:
            from app.jarvis.mcp_registry import mcp_tool_tier

            return mcp_tool_tier(raw) is not None
        except Exception:
            return False
    return False


def requires_confirm(name: str, *, max_auto: Tier) -> bool:
    if skips_confirm(name):
        return False
    return tool_tier(name) > max_auto


def list_tools_public() -> list[dict]:
    out = []
    for name, tier in sorted(TOOL_TIERS.items(), key=lambda x: (x[1], x[0])):
        if name == "disk_space":
            continue  # expose get_disk_space as canonical
        if name in {"get_github_repos", "github_repos"}:
            continue  # expose list_github_repos as canonical
        out.append({"name": name, "tier": f"L{int(tier)}"})
    try:
        from app.jarvis.mcp_registry import list_mcp_tools_public

        for t in list_mcp_tools_public():
            out.append(
                {
                    "name": t["name"],
                    "tier": t.get("tier") or "L5",
                    "mcp": True,
                    "server_id": t.get("server_id"),
                    "description": t.get("description") or "",
                }
            )
    except Exception:
        pass
    return out
