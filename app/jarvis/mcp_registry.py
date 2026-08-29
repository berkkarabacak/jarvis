"""Persist MCP server registrations (ORCH-323).

Path: ``{JARVIS_WORKSPACE}/Memory/mcp_servers.json``
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.jarvis.permissions import Tier
from app.jarvis.workspace import default_workspace

REGISTRY_FILENAME = "mcp_servers.json"
_TOOL_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")

_lock = threading.RLock()
_cache: list[dict[str, Any]] | None = None
_cache_path: Path | None = None


def registry_path(root: Path | None = None) -> Path:
    base = (root or default_workspace()).resolve()
    return base / "Memory" / REGISTRY_FILENAME


def reset_cache() -> None:
    global _cache, _cache_path
    with _lock:
        _cache = None
        _cache_path = None


def _parse_tier(raw: Any, default: Tier = Tier.L5) -> Tier:
    if raw is None:
        return default
    if isinstance(raw, Tier):
        return raw
    if isinstance(raw, int):
        return Tier(min(5, max(0, raw)))
    s = str(raw).strip().upper()
    if s.startswith("L") and s[1:].isdigit():
        return Tier(min(5, max(0, int(s[1:]))))
    if s in Tier.__members__:
        return Tier[s]
    return default


def compute_tool_tier(
    *,
    trusted: bool,
    max_tier: Any,
    annotations: dict[str, Any] | None = None,
) -> Tier:
    """Default L5; trusted server max_tier is the start; annotations only raise."""
    if trusted:
        base = _parse_tier(max_tier, Tier.L5)
    else:
        base = Tier.L5
    ann = annotations or {}
    tier = int(base)
    if ann.get("destructiveHint") is True:
        tier = max(tier, int(Tier.L5))
    # Explicitly non-readonly → at least L3 (writes / side effects)
    if ann.get("readOnlyHint") is False:
        tier = max(tier, int(Tier.L3))
    # Never lower below the starting base
    tier = max(tier, int(base))
    return Tier(min(5, tier))


def namespaced_tool(server_id: str, tool_name: str) -> str:
    safe = _TOOL_SAFE.sub("_", (tool_name or "").strip()) or "tool"
    return f"mcp.{server_id}.{safe}"


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Return (server_id, tool_name) for ``mcp.<server_id>.<tool>`` or None."""
    raw = (name or "").strip()
    if not raw.startswith("mcp."):
        return None
    parts = raw.split(".", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def _read_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict) and isinstance(raw.get("servers"), list):
        return [s for s in raw["servers"] if isinstance(s, dict)]
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    return []


def _write_file(path: Path, servers: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"servers": servers, "updated_at": time.time()}
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_servers(root: Path | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    global _cache, _cache_path
    path = registry_path(root)
    with _lock:
        if not force and _cache is not None and _cache_path == path:
            return [dict(s) for s in _cache]
        data = _read_file(path)
        _cache = [dict(s) for s in data]
        _cache_path = path
        return [dict(s) for s in _cache]


def save_servers(servers: list[dict[str, Any]], root: Path | None = None) -> list[dict[str, Any]]:
    global _cache, _cache_path
    path = registry_path(root)
    with _lock:
        clean = [dict(s) for s in servers]
        _write_file(path, clean)
        _cache = [dict(s) for s in clean]
        _cache_path = path
        return [dict(s) for s in _cache]


def get_server(server_id: str, root: Path | None = None) -> dict[str, Any] | None:
    sid = (server_id or "").strip()
    for s in load_servers(root):
        if s.get("id") == sid:
            return dict(s)
    return None


def upsert_server(server: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    servers = load_servers(root, force=True)
    sid = server.get("id")
    found = False
    for i, s in enumerate(servers):
        if s.get("id") == sid:
            servers[i] = dict(server)
            found = True
            break
    if not found:
        servers.append(dict(server))
    save_servers(servers, root)
    return dict(server)


def delete_server(server_id: str, root: Path | None = None) -> bool:
    servers = load_servers(root, force=True)
    sid = (server_id or "").strip()
    new = [s for s in servers if s.get("id") != sid]
    if len(new) == len(servers):
        return False
    save_servers(new, root)
    return True


def new_server_id() -> str:
    return "mcp_" + uuid.uuid4().hex[:10]


def public_server(server: dict[str, Any]) -> dict[str, Any]:
    """Safe connector snapshot — never includes token ciphertext or plaintext."""
    tools = []
    for t in server.get("discovered_tools") or []:
        if not isinstance(t, dict):
            continue
        tools.append(
            {
                "name": t.get("name"),
                "namespaced": t.get("namespaced")
                or namespaced_tool(str(server.get("id") or ""), str(t.get("name") or "")),
                "description": t.get("description") or "",
                "tier": t.get("tier") or "L5",
                "annotations": dict(t.get("annotations") or {}),
            }
        )
    from app.jarvis.mcp_tokens import has_token

    scopes = []
    for s in server.get("granted_scopes") or []:
        if isinstance(s, str) and s.strip():
            scopes.append(s.strip())
    preset = server.get("preset")
    if not preset and server.get("id") in {"github", "slack"}:
        preset = server.get("id")
    return {
        "id": server.get("id"),
        "name": server.get("name") or server.get("id"),
        "transport": server.get("transport") or "stdio",
        "command": server.get("command") or "",
        "args": list(server.get("args") or []),
        "url": server.get("url") or "",
        "enabled": bool(server.get("enabled", True)),
        "trusted": bool(server.get("trusted", False)),
        "max_tier": server.get("max_tier") or "L5",
        "status": server.get("status") or "unknown",
        "last_error": server.get("last_error"),
        "has_token": has_token(server.get("token_enc")),
        "discovered_tools": tools,
        "updated_at": server.get("updated_at"),
        # ORCH-325: scopes are labels for Settings (read-only display).
        "granted_scopes": scopes,
        "preset": preset,
        "read_only": bool(server.get("read_only") or preset),
    }


def list_connectors_public(root: Path | None = None) -> list[dict[str, Any]]:
    return [public_server(s) for s in load_servers(root)]


def find_discovered_tool(tool_name: str, root: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Resolve a namespaced MCP tool to (server, tool_record)."""
    parsed = parse_mcp_tool_name(tool_name)
    if not parsed:
        return None
    server_id, short = parsed
    server = get_server(server_id, root)
    if not server:
        return None
    for t in server.get("discovered_tools") or []:
        if not isinstance(t, dict):
            continue
        ns = t.get("namespaced") or namespaced_tool(server_id, str(t.get("name") or ""))
        if ns == tool_name or str(t.get("name") or "") == short:
            return dict(server), dict(t)
    return None


def mcp_tool_tier(tool_name: str, root: Path | None = None) -> Tier | None:
    """Explicit tier from registry, or None if not a known discovered MCP tool."""
    hit = find_discovered_tool(tool_name, root)
    if not hit:
        return None
    _server, tool = hit
    return _parse_tier(tool.get("tier"), Tier.L5)


def list_mcp_tools_public(root: Path | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in load_servers(root):
        if not s.get("enabled", True):
            continue
        if (s.get("status") or "") == "failed":
            # Still list tools so operators see them; dispatch returns friendly error.
            pass
        for t in s.get("discovered_tools") or []:
            if not isinstance(t, dict):
                continue
            ns = t.get("namespaced") or namespaced_tool(str(s.get("id") or ""), str(t.get("name") or ""))
            out.append(
                {
                    "name": ns,
                    "tier": t.get("tier") or "L5",
                    "mcp": True,
                    "server_id": s.get("id"),
                    "description": t.get("description") or "",
                }
            )
    out.sort(key=lambda x: (x.get("tier") or "L5", x.get("name") or ""))
    return out


# ORCH-324 hook: registry of currently discovered MCP tool names for taint.
def mcp_tool_names(root: Path | None = None) -> frozenset[str]:
    return frozenset(t["name"] for t in list_mcp_tools_public(root) if t.get("name"))
