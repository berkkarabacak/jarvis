"""D3: public cloud / guest guardrails — never full laptop tools or Prime ==GRoK== (ORCH-259)."""

from __future__ import annotations

import os
from typing import Any


def is_public_cloud_host() -> bool:
    """True when this process must not expose desktop colleague capabilities."""
    if str(os.environ.get("PUBLIC_GUEST_PROFILE", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    if str(os.environ.get("JARVIS_PUBLIC_CLOUD", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    base = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("PUBLIC_HOST")
        or ""
    ).lower()
    if "aicontrolroom.nl" in base:
        return True
    host = (os.environ.get("HOST") or "").strip().lower()
    # binding non-loopback with guest profile markers
    if host and host not in {"127.0.0.1", "localhost", "::1"} and str(
        os.environ.get("HERDR_ENABLED", "")
    ).lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def enforce_public_guardrails() -> dict[str, Any]:
    """Force-disable dangerous local features on public hosts. Call at startup."""
    applied: list[str] = []
    if not is_public_cloud_host():
        return {"public_cloud": False, "applied": applied}

    forced = {
        "JARVIS_ENABLED": "false",
        "JARVIS_REALTIME": "false",
        "PRIME_AGENT_ENABLED": "false",
        "BRIDGE_ENABLED": "false",
        "EXECUTIVE_PRIME_ADAPTER": "openrouter",
    }
    for k, v in forced.items():
        prev = os.environ.get(k)
        if str(prev).lower() not in {v, ""} or k not in os.environ:
            os.environ[k] = v
            applied.append(f"{k}={v} (was {prev!r})")
        else:
            os.environ[k] = v
    # strip bridge token so bridge_routes stay 403
    if os.environ.get("BRIDGE_TOKEN"):
        os.environ["BRIDGE_TOKEN"] = ""
        applied.append("BRIDGE_TOKEN cleared")
    return {"public_cloud": True, "applied": applied}


def jarvis_tools_allowed() -> bool:
    if is_public_cloud_host():
        return False
    return str(os.environ.get("JARVIS_ENABLED", "false")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def assert_local_tool_allowed(tool: str) -> str | None:
    """Return error string if tool must not run on this host."""
    if not is_public_cloud_host():
        return None
    blocked = {
        "run_powershell",
        "run_app",
        "open_path",
        "home_write",
        "home_read",
        "home_list",
        "screenshot",
        "see_screen",
        "dispatch_prime",
        "download_fetch",
        "release_download",
        "write_file",
        "create_excel",
    }
    if tool in blocked or tool.startswith("home_") or tool.startswith("mcp."):
        return f"blocked on public cloud: {tool}"
    return None
