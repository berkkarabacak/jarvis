"""Jarvis Settings + Audit viewer HTTP API (ORCH-322)."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.jarvis.audit import AuditLog, redact
from app.jarvis.gateway import get_gateway
from app.jarvis.settings_store import (
    get_approve_countdown_sec,
    get_computer_kind,
    get_daily_budget_usd,
    get_look_speed,
    get_model,
    get_model_lock,
    get_model_preference,
    get_model_speed,
    get_monthly_budget_usd,
    get_permission_profile,
    get_provider,
    get_quality_vs_price,
    get_realtime_voice,
    public_view,
    save,
    validate_update,
)
from app.jarvis.workspace import default_workspace

log = logging.getLogger("jarvis.settings")

router = APIRouter(prefix="/api/jarvis", tags=["jarvis-settings"])

# Hosted public Talk may persist helper + how-he-thinks / how-fast-he-works
# picks without an API key. Nothing else — no keys, budget, permissions,
# voice, or connectors.
PUBLIC_SAFE_SETTINGS_FIELDS = frozenset(
    {
        "model",
        "model_lock",
        "quality_vs_price",
        "model_preference",
        "model_speed",
        "computer_kind",
    }
)


class SettingsUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_profile: str | None = Field(default=None, max_length=32)
    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=120)
    model_lock: bool | None = None
    model_lock_pin: str | None = Field(default=None, max_length=8)
    unlock_pin: str | None = Field(default=None, max_length=8)
    realtime_voice: str | None = Field(default=None, max_length=32)
    look_speed: str | None = Field(default=None, max_length=8)
    quality_vs_price: str | None = Field(default=None, max_length=16)
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    daily_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    model_preference: str | None = Field(default=None, max_length=32)
    model_speed: str | None = Field(default=None, max_length=32)
    approve_countdown_sec: int | None = Field(default=None, ge=1, le=120)
    computer_kind: str | None = Field(default=None, max_length=32)


def _require_jarvis_write_auth(
    request: Request,
    x_api_key: str | None,
    authorization: str | None,
) -> None:
    """Authenticate mutating Jarvis settings like other protected write APIs.

    Local CEO has no browser-held API secret; when ``API_SECRET`` is unset or
    the caller is loopback without a key, same-origin writes are allowed (the
    same trust model as ``/api/jarvis/tools/run``). When a non-loopback client
    calls in and ``API_SECRET`` is configured, the standard X-Api-Key /
    Bearer secret is required — matching ``/api/settings/*``.
    """
    settings = getattr(getattr(request, "app", None), "state", None)
    expected = ""
    if settings is not None:
        cfg = getattr(settings, "settings", None)
        if cfg is not None:
            expected = (getattr(cfg, "api_secret", None) or "").strip()
    if not expected:
        expected = (os.environ.get("API_SECRET") or "").strip()

    peer = ""
    try:
        peer = (request.client.host if request.client else "") or ""
    except Exception:
        peer = ""
    # Empty peer = in-process / ASGI test client; treat as local like /ceo.
    loopback = (not peer) or peer in {
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
        "test",
    }

    provided = (x_api_key or "").strip()
    if not provided and authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()
        else:
            provided = authorization.strip()

    if provided and expected and provided == expected:
        return
    if loopback:
        # Same trust boundary as other /api/jarvis write routes used by /ceo.
        return
    if not expected:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API secret")


def _is_public_safe_settings_update(raw: dict[str, Any]) -> bool:
    return bool(raw) and set(raw).issubset(PUBLIC_SAFE_SETTINGS_FIELDS)


def _reject_unknown_public_helper(updates: dict[str, Any]) -> None:
    mid = updates.get("model")
    if not isinstance(mid, str) or not mid.strip():
        return
    from app.jarvis.openrouter_leaders import is_allowed_helper_model

    if not is_allowed_helper_model(mid):
        raise HTTPException(status_code=400, detail="model is not a current helper")


def _audit_settings_change(
    *,
    source: str,
    before: dict[str, Any],
    after: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    try:
        gw = get_gateway()
        entry = {
            "source": source,
            "tool": "settings.update",
            "tier": "L0",
            "allowed": True,
            "needs_confirm": False,
            "ok": True,
            "arguments": {"updates": updates},
            "result": {"before": before, "after": after},
            "reason": "settings changed",
        }
        if before.get("permission_profile") != after.get("permission_profile"):
            entry["event"] = "permission_profile_changed"
            entry["permission_profile_from"] = before.get("permission_profile")
            entry["permission_profile_to"] = after.get("permission_profile")
        gw._audit_log.append(entry)
    except Exception:
        log.exception("settings audit append failed")


def _snapshot() -> dict[str, Any]:
    return {
        "permission_profile": get_permission_profile(),
        "provider": get_provider(),
        "model": get_model(),
        "model_lock": get_model_lock(),
        "realtime_voice": get_realtime_voice(),
        "look_speed": get_look_speed(),
        "quality_vs_price": get_quality_vs_price(),
        "monthly_budget_usd": get_monthly_budget_usd(),
        "daily_budget_usd": get_daily_budget_usd(),
        "model_preference": get_model_preference(),
        "model_speed": get_model_speed(),
        "approve_countdown_sec": get_approve_countdown_sec(),
        "computer_kind": get_computer_kind(),
    }


@router.get("/settings")
async def get_jarvis_settings() -> dict[str, Any]:
    """Public-ish same-origin read of Jarvis settings. Never returns secrets."""
    return public_view()


@router.put("/settings")
async def put_jarvis_settings(
    body: SettingsUpdateBody,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Persist settings overrides. Audits profile/model changes."""
    raw = body.model_dump(exclude_unset=True)
    if not raw:
        raise HTTPException(status_code=400, detail="no settings fields to update")
    authorized = True
    try:
        _require_jarvis_write_auth(request, x_api_key, authorization)
    except HTTPException:
        authorized = False
    public_safe = _is_public_safe_settings_update(raw)
    if not authorized and not public_safe:
        raise HTTPException(status_code=401, detail="Invalid or missing API secret")
    try:
        updates = validate_update(raw, require_unlock=authorized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updates:
        raise HTTPException(status_code=400, detail="no settings fields to update")
    if not authorized:
        _reject_unknown_public_helper(updates)

    before = _snapshot()
    save(updates)
    after = _snapshot()
    _audit_settings_change(
        source="settings-ui",
        before=before,
        after=after,
        updates=updates,
    )
    view = public_view()
    view["ok"] = True
    view["changed"] = sorted(updates.keys())
    return view


def _audit_log() -> AuditLog:
    return AuditLog(default_workspace() / "Memory" / "tool_audit.jsonl")


@router.get("/audit/recent")
async def audit_recent(n: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    """List the most recent AuditLog entries (already redacted at write time)."""
    entries = _audit_log().tail(n)
    # Re-redact for defense in depth before leaving the process.
    return {"ok": True, "n": len(entries), "entries": redact(entries)}


@router.post("/audit/verify")
async def audit_verify() -> dict[str, Any]:
    """Run tamper check across the current file and any rotation."""
    log_obj = _audit_log()
    ok, reason = log_obj.verify_across_rotation()
    # Also expose the single-file verify detail for the UI.
    file_ok, index, file_reason = log_obj.verify()
    return {
        "ok": ok,
        "verify_across_rotation": {"ok": ok, "reason": reason},
        "verify": {"ok": file_ok, "index": index, "reason": file_reason},
    }


# ---------------------------------------------------------------------------
# MCP connectors (ORCH-323)
# ---------------------------------------------------------------------------


class McpServerCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    transport: str = Field(default="stdio", max_length=16)
    command: str | None = Field(default=None, max_length=400)
    args: list[str] | None = None
    url: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    trusted: bool = False
    max_tier: str = Field(default="L5", max_length=8)
    token: str | None = Field(default=None, max_length=4000)
    refresh: bool = True
    # ORCH-325: optional granted scope labels (stored; never secrets)
    granted_scopes: list[str] | None = None
    preset: str | None = Field(default=None, max_length=32)


class McpServerPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    transport: str | None = Field(default=None, max_length=16)
    command: str | None = Field(default=None, max_length=400)
    args: list[str] | None = None
    url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    trusted: bool | None = None
    max_tier: str | None = Field(default=None, max_length=8)
    refresh: bool = False


class McpTokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=0, max_length=4000)


def _normalize_max_tier(raw: str | None) -> str:
    s = (raw or "L5").strip().upper()
    if s.startswith("L") and s[1:].isdigit() and 0 <= int(s[1:]) <= 5:
        return f"L{int(s[1:])}"
    raise ValueError("max_tier must be L0-L5")


def _normalize_transport(raw: str | None) -> str:
    t = (raw or "stdio").strip().lower()
    if t not in {"stdio", "http"}:
        raise ValueError("transport must be stdio or http")
    return t


@router.get("/mcp/servers")
async def list_mcp_servers() -> dict[str, Any]:
    from app.jarvis.mcp_registry import list_connectors_public

    servers = list_connectors_public()
    return {"ok": True, "servers": servers, "n": len(servers)}


@router.post("/mcp/servers")
async def create_mcp_server(
    body: McpServerCreateBody,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_client import refresh_server
    from app.jarvis.mcp_registry import new_server_id, public_server, upsert_server
    from app.jarvis.mcp_tokens import encrypt_token

    try:
        transport = _normalize_transport(body.transport)
        max_tier = _normalize_max_tier(body.max_tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if transport == "stdio" and not (body.command or "").strip():
        raise HTTPException(status_code=400, detail="stdio transport requires command")
    if transport == "http" and not (body.url or "").strip():
        raise HTTPException(status_code=400, detail="http transport requires url")

    scopes = [s.strip() for s in (body.granted_scopes or []) if isinstance(s, str) and s.strip()]
    preset = (body.preset or "").strip().lower() or None
    server = {
        "id": new_server_id(),
        "name": body.name.strip(),
        "transport": transport,
        "command": (body.command or "").strip(),
        "args": list(body.args or []),
        "url": (body.url or "").strip(),
        "enabled": bool(body.enabled),
        "trusted": bool(body.trusted),
        "max_tier": max_tier,
        "status": "unknown",
        "last_error": None,
        "token_enc": encrypt_token(body.token) if body.token else "",
        "discovered_tools": [],
        "granted_scopes": scopes,
        "preset": preset,
        "read_only": bool(preset in {"github", "slack"}),
    }
    server = upsert_server(server)
    if body.refresh and server.get("enabled", True):
        server = refresh_server(server)
    return {"ok": True, "server": public_server(server)}


@router.patch("/mcp/servers/{server_id}")
async def patch_mcp_server(
    server_id: str,
    body: McpServerPatchBody,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_client import refresh_server
    from app.jarvis.mcp_registry import get_server, public_server, upsert_server

    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    raw = body.model_dump(exclude_unset=True)
    refresh = bool(raw.pop("refresh", False))
    try:
        if "transport" in raw and raw["transport"] is not None:
            server["transport"] = _normalize_transport(raw["transport"])
        if "max_tier" in raw and raw["max_tier"] is not None:
            server["max_tier"] = _normalize_max_tier(raw["max_tier"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for key in ("name", "command", "url"):
        if key in raw and raw[key] is not None:
            server[key] = str(raw[key]).strip()
    if "args" in raw and raw["args"] is not None:
        server["args"] = list(raw["args"])
    if "enabled" in raw and raw["enabled"] is not None:
        server["enabled"] = bool(raw["enabled"])
    if "trusted" in raw and raw["trusted"] is not None:
        server["trusted"] = bool(raw["trusted"])
    server = upsert_server(server)
    # Re-tier discovered tools when trust/max_tier changes
    if any(k in raw for k in ("trusted", "max_tier")) and server.get("discovered_tools"):
        from app.jarvis.mcp_registry import compute_tool_tier, namespaced_tool

        retiered = []
        for t in server.get("discovered_tools") or []:
            if not isinstance(t, dict):
                continue
            ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
            tier = compute_tool_tier(
                trusted=bool(server.get("trusted")),
                max_tier=server.get("max_tier"),
                annotations=ann,
            )
            tt = dict(t)
            tt["tier"] = f"L{int(tier)}"
            tt["namespaced"] = namespaced_tool(str(server.get("id") or ""), str(t.get("name") or ""))
            retiered.append(tt)
        server["discovered_tools"] = retiered
        server = upsert_server(server)
    if refresh:
        server = refresh_server(server)
    return {"ok": True, "server": public_server(server)}


@router.delete("/mcp/servers/{server_id}")
async def delete_mcp_server(
    server_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_registry import delete_server

    if not delete_server(server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"ok": True, "deleted": server_id}


@router.post("/mcp/servers/{server_id}/refresh")
async def refresh_mcp_server(
    server_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_client import refresh_server
    from app.jarvis.mcp_registry import get_server, public_server

    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    server = refresh_server(server)
    return {"ok": True, "server": public_server(server)}


@router.post("/mcp/servers/{server_id}/token")
async def set_mcp_server_token(
    server_id: str,
    body: McpTokenBody,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Store an encrypted bearer token. Never echoes the token back."""
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_registry import get_server, public_server, upsert_server
    from app.jarvis.mcp_tokens import encrypt_token

    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    server["token_enc"] = encrypt_token(body.token)
    server = upsert_server(server)
    view = public_server(server)
    # belt-and-braces: ensure no token-like fields leak
    for k in list(view.keys()):
        if "token" in k.lower() and k != "has_token":
            view.pop(k, None)
    return {"ok": True, "server": view, "has_token": view.get("has_token")}


# ---------------------------------------------------------------------------
# Official GitHub / Slack MCP presets (ORCH-325)
# ---------------------------------------------------------------------------


class McpPresetRegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str | None = Field(default=None, max_length=4000)
    scopes: list[str] | None = None
    enabled: bool = True
    refresh: bool = False


@router.get("/mcp/presets")
async def list_mcp_presets() -> dict[str, Any]:
    """Catalog of first-class read-only GitHub + Slack MCP presets."""
    from app.jarvis.mcp_presets import list_presets_public

    presets = list_presets_public()
    return {"ok": True, "presets": presets, "n": len(presets)}


@router.post("/mcp/presets/{preset_id}")
async def register_mcp_preset(
    preset_id: str,
    body: McpPresetRegisterBody,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Register or update an official read-only MCP preset.

    Tokens are encrypted at rest and never echoed. ``granted_scopes`` are
    stored as labels for Settings (read-only display).
    """
    _require_jarvis_write_auth(request, x_api_key, authorization)
    from app.jarvis.mcp_presets import public_preset_server, register_preset

    try:
        server = register_preset(
            preset_id,
            token=body.token,
            scopes=body.scopes,
            enabled=bool(body.enabled),
            refresh=bool(body.refresh),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    view = public_preset_server(server)
    return {"ok": True, "server": view}
