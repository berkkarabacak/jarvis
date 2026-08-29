"""Bridge discovered MCP tools into ToolGateway (ORCH-323 / ORCH-324).

ORCH-324: MCP tool *results* are untrusted external content. The gateway
``observe()`` / ``returns_untrusted()`` path treats every ``mcp.*`` name as
tainting — see ``app.jarvis.taint``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.jarvis.mcp_client import call_mcp_tool
from app.jarvis.mcp_registry import find_discovered_tool, parse_mcp_tool_name
from app.jarvis.permissions import Tier

log = logging.getLogger("jarvis.mcp.gateway")


def is_mcp_tool(name: str) -> bool:
    return parse_mcp_tool_name(name) is not None


def mcp_known_and_tier(name: str) -> Tier | None:
    """Return explicit registry tier, or None if not a registered MCP tool."""
    from app.jarvis.mcp_registry import mcp_tool_tier

    return mcp_tool_tier(name)


def run_mcp_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a namespaced MCP tool; always returns a gateway-shaped dict."""
    hit = find_discovered_tool(name)
    if not hit:
        return {"ok": False, "error": f"unknown MCP tool: {name}", "tier": "L5"}
    server, tool = hit
    short = str(tool.get("name") or "")
    tier = str(tool.get("tier") or "L5")
    if not server.get("enabled", True):
        return {
            "ok": False,
            "error": f"MCP server {server.get('name') or server.get('id')} is disabled",
            "tier": tier,
            "tool": name,
        }
    if (server.get("status") or "") == "failed":
        return {
            "ok": False,
            "error": (
                f"MCP server unavailable: "
                f"{(server.get('last_error') or 'failed state')}"
            )[:300],
            "tier": tier,
            "tool": name,
            "mcp_status": "failed",
        }

    result = call_mcp_tool(server, short, args or {})
    if not result.ok:
        return {
            "ok": False,
            "error": result.error or "MCP call failed",
            "tier": tier,
            "tool": name,
        }

    payload = result.result
    # MCP tools/call typically returns {content: [...], isError?: bool}
    if isinstance(payload, dict) and payload.get("isError"):
        return {
            "ok": False,
            "error": _content_text(payload) or "MCP tool reported an error",
            "tier": tier,
            "tool": name,
            "mcp_result": payload,
        }
    out: dict[str, Any] = {
        "ok": True,
        "tier": tier,
        "tool": name,
        "mcp_result": payload,
        # ORCH-324: connector results are outside the trust boundary.
        # Gateway observe()/returns_untrusted() also keys off the mcp. prefix.
        "mcp": True,
        "untrusted_candidate": True,
    }
    text = _content_text(payload) if isinstance(payload, dict) else None
    if text:
        out["content"] = text[:8000]
        out["summary"] = text[:240]
    return out


def _content_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
    elif isinstance(content, str):
        parts.append(content)
    if not parts and "result" in payload:
        try:
            parts.append(json.dumps(payload.get("result"), default=str)[:2000])
        except Exception:
            parts.append(str(payload.get("result"))[:2000])
    return "\n".join(p for p in parts if p).strip()
