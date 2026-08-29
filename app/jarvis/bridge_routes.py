"""Authenticated agent-to-Jarvis bridge API (ORCH-287)."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.jarvis.bridge_store import TERMINAL, BridgeStore
from app.jarvis.gateway import get_gateway
from app.jarvis.tools import plain_confirm_text, plain_summary
from app.jarvis.permissions import (
    Tier,
    bridge_max_auto_tier,
    current_profile,
    list_tools_public,
    max_auto_tier,
)
from app.jarvis.workspace import default_workspace

log = logging.getLogger("jarvis.bridge")
router = APIRouter(prefix="/api/bridge/v1", tags=["jarvis-bridge"])

_START = time.time()
_store: BridgeStore | None = None
_rate: dict[str, list[float]] = {}


def _bridge_enabled() -> bool:
    if str(os.environ.get("BRIDGE_ENABLED", "true")).strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return bool((os.environ.get("BRIDGE_TOKEN") or os.environ.get("JARVIS_BRIDGE_TOKEN") or "").strip())


def _bridge_token() -> str:
    return (os.environ.get("BRIDGE_TOKEN") or os.environ.get("JARVIS_BRIDGE_TOKEN") or "").strip()


def _store_get() -> BridgeStore:
    global _store
    if _store is None:
        path = default_workspace() / "Memory" / "bridge_tasks.db"
        _store = BridgeStore(path)
    return _store


def _auth(token: str | None) -> None:
    if not _bridge_enabled():
        raise HTTPException(status_code=403, detail="Bridge disabled (set BRIDGE_TOKEN)")
    expected = _bridge_token()
    got = (token or "").strip()
    if not expected or not hmac.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bridge token")


def _rate_limit(source: str) -> None:
    now = time.time()
    window = _rate.setdefault(source, [])
    _rate[source] = [t for t in window if now - t < 3600]
    limit = int(os.environ.get("BRIDGE_RATE_PER_HOUR") or "60")
    if len(_rate[source]) >= limit:
        raise HTTPException(status_code=429, detail="Bridge rate limit exceeded")
    _rate[source].append(now)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="opencode", min_length=1, max_length=64)
    priority: str = Field(default="normal", max_length=32)
    tier_hint: str | None = Field(default=None, max_length=8)
    engine: str | None = Field(
        default=None,
        max_length=16,
        description="Optional: jarvis | prime (B2 dispatch)",
    )
    context: dict[str, Any] = Field(default_factory=dict)
    confirm_policy: str = Field(default="auto_if_allowed", max_length=32)
    timeout_sec: int = Field(default=300, ge=5, le=3600)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_id: str = Field(min_length=1, max_length=80)
    decision: str = Field(min_length=1, max_length=16)


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="opencode", min_length=1, max_length=64)


# Screen-control / browser jobs must run the agent — do not infer a single tool.
_SCREEN_CONTROL_MARKERS = (
    "see_screen",
    "focus_app",
    "screenshot",
    "click",
    "type",
    "keys",
    "scroll",
    "run_app",
    "chrome",
    "http://",
    "https://",
)

# Phrase stems only: "desktop job" and "see_screen shows" must not match.
_HOME_LIST_PHRASE_TEMPLATES = (
    "list {name}",
    "list my {name}",
    "list files on my {name}",
    "show {name}",
    "show my {name}",
    "what's on my {name}",
    "whats on my {name}",
    "{name} files",
    "files on my {name}",
    "files on the {name}",
)


def _looks_like_screen_control_job(g: str) -> bool:
    if _is_home_list_ask(g, "desktop") or _is_home_list_ask(g, "download") or _is_home_list_ask(g, "document"):
        return False
    if any(marker in g for marker in _SCREEN_CONTROL_MARKERS):
        return True
    from app.jarvis.virtual_pc import goal_is_virtual_pc_job
    return goal_is_virtual_pc_job(g)


def _is_home_list_ask(g: str, name: str) -> bool:
    """True for a real list-this-folder ask, not adjective uses like 'desktop job'."""
    return any(tpl.format(name=name) in g for tpl in _HOME_LIST_PHRASE_TEMPLATES)


def _infer_tool_from_goal(goal: str) -> tuple[str, dict[str, Any]] | None:
    g = goal.lower()
    if _looks_like_screen_control_job(g):
        return None
    if any(
        k in g
        for k in (
            "free space",
            "disk space",
            "disk free",
            "storage left",
            "how much space",
            "storage free",
        )
    ):
        return "get_disk_space", {}
    if any(
        k in g
        for k in (
            "github repositor",
            "github repo",
            "my repos",
            "my repositories",
            "list my repo",
            "get my repo",
        )
    ):
        return "list_github_repos", {}
    if "system info" in g or "how much ram" in g or "cpu" in g and "info" in g:
        return "system_info", {}
    if _is_home_list_ask(g, "desktop"):
        return "home_list", {"root": "Desktop", "path": "."}
    if _is_home_list_ask(g, "download"):
        return "home_list", {"root": "Downloads", "path": "."}
    if _is_home_list_ask(g, "document"):
        return "home_list", {"root": "Documents", "path": "."}
    return None


async def _execute_task(task_id: str, *, confirmed: bool = False) -> None:
    store = _store_get()
    task = store.get_task(task_id)
    if not task or task["status"] in TERMINAL:
        return
    store.set_status(task_id, "running")
    store.add_event(task_id, "progress", "Task started")
    goal = task["goal"]
    source = f"bridge:{task.get('source') or 'agent'}"
    gw = get_gateway()
    ctx = task.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}

    # B2: route heavy goals to Prime when enabled
    from app.jarvis.dispatch import classify_goal, run_prime_mission

    decision = classify_goal(goal, explicit=ctx.get("engine") or ctx.get("dispatch"))
    store.add_event(
        task_id,
        "progress",
        f"Dispatch engine={decision.engine} ({decision.reason})",
    )
    if decision.engine == "prime":
        result = await run_prime_mission(goal, memory=gw.memory, context=ctx)
        tools_used = ["prime-rpc"] if result.get("ok") else []
        if result.get("ok"):
            store.set_result(
                task_id,
                {
                    "summary": result.get("summary") or "Prime mission complete",
                    "data": result,
                    "tools_used": tools_used,
                    "artifacts": [],
                    "mission_id": result.get("mission_id"),
                    "prime_session_id": result.get("prime_session_id"),
                    "engine": "prime",
                },
                tools_used,
            )
            return
        # degrade to jarvis agent — do not fail voice/bridge hard
        store.add_event(
            task_id,
            "progress",
            f"Prime unavailable ({result.get('error')}); falling back to Jarvis",
        )

    inferred = _infer_tool_from_goal(goal)
    tools_used: list[str] = []

    if inferred:
        tool, args = inferred
        store.add_event(task_id, "progress", f"Calling {tool}")
        result = gw.run(
            tool,
            args,
            source=source,
            max_auto=bridge_max_auto_tier(),
            confirmed=confirmed,
        )
        tools_used.append(tool)
        if result.get("needs_confirm"):
            from app.jarvis.settings_store import get_approve_countdown_sec

            countdown = int(
                result.get("approve_countdown_sec") or get_approve_countdown_sec()
            )
            auto_at = result.get("auto_approve_at")
            if not isinstance(auto_at, (int, float)):
                auto_at = time.time() + countdown
            conf = {
                "id": result.get("confirm_id") or ("cnf_" + task_id[-12:]),
                "action_summary": result.get("action_summary")
                or result.get("user_prompt")
                or plain_confirm_text(tool, args),
                "tier": result.get("tier") or "L3",
                "tool": tool,
                "arguments": args,
                "user_prompt": result.get("user_prompt")
                or plain_confirm_text(tool, args),
                "approve_countdown_sec": countdown,
                "auto_approve_at": auto_at,
            }
            store.set_confirm(task_id, conf)
            asyncio.create_task(
                _auto_approve_bridge_task(task_id, str(conf["id"]), countdown)
            )
            return
        if not result.get("ok", True) and result.get("error"):
            store.set_status(task_id, "failed", error=str(result.get("error"))[:500])
            store.add_event(task_id, "error", str(result.get("error")))
            return
        summary = plain_summary(tool, result)
        store.set_result(
            task_id,
            {
                "summary": summary,
                "data": result,
                "tools_used": tools_used,
                "artifacts": [],
            },
            tools_used,
        )
        return

    # Generic: Jarvis agent turn with bridge permission ceiling + model override
    store.add_event(task_id, "progress", "Running Jarvis agent turn")
    try:
        from app.jarvis.agent import (
            LOOK_JOB_STOP_PROMPT,
            build_jarvis_agent,
            is_desktop_look_job,
            resolve_tool_rounds,
        )
        from app.jarvis.workspace import default_workspace

        ctx = task.get("context") if isinstance(task.get("context"), dict) else {}
        model_override = (ctx.get("model") or "").strip() or None
        pref = (ctx.get("model_preference") or ctx.get("preference") or "").strip() or None
        max_auto = int(bridge_max_auto_tier())
        agent = build_jarvis_agent(
            api_key=os.environ.get("OPENROUTER_API_KEY") or "",
            model=model_override,
            tool_source="bridge",
            max_auto=max_auto,
            timeout_seconds=float(ctx.get("timeout_seconds") or 180),
            max_tool_rounds=resolve_tool_rounds(goal, ctx.get("max_tool_rounds")),
            max_tokens=int(ctx.get("max_tokens") or 8192),
            goal=goal,
            model_preference=pref,
        )
        if agent is None:
            store.set_status(
                task_id,
                "failed",
                error="No tool mapping for goal and Jarvis agent unavailable",
            )
            return
        route_info = getattr(agent, "_model_route", None) or {}
        if route_info:
            store.add_event(
                task_id,
                "progress",
                "model_route model={m} reason={r}".format(
                    m=route_info.get("model"),
                    r=route_info.get("reason"),
                ),
            )
        # Nudge: always allow workspace Exports writes for build tasks
        bridged_goal = (
            goal
            + "\n\n[Bridge policy] Write deliverables with write_file under Exports/ "
            + "in the Jarvis workspace. Do not ask which folder. Finish the file."
        )
        if is_desktop_look_job(goal):
            bridged_goal += "\n[Look policy] " + LOOK_JOB_STOP_PROMPT
        sess = await agent.start_session(role_name="bridge")
        msg = await agent.send_message(sess.session_id, message=bridged_goal)
        await agent.stop_session(sess.session_id, reason="bridge_complete")
        tools_used.append("jarvis-local")
        for called in getattr(agent, "_tools_called", []) or []:
            if called and called not in tools_used:
                tools_used.append(called)
        # Collect new/changed artifacts under Exports/
        artifacts: list[dict[str, Any]] = []
        exports = default_workspace() / "Exports"
        if exports.is_dir():
            for p in sorted(exports.rglob("*")):
                if p.is_file() and p.stat().st_mtime >= (task.get("created_at") or 0) - 1:
                    artifacts.append(
                        {
                            "path": str(p),
                            "rel": str(p.relative_to(default_workspace())).replace("\\", "/"),
                            "bytes": p.stat().st_size,
                        }
                    )
        cost = None
        model_used = model_override or getattr(agent, "_model", None)
        try:
            gen = getattr(msg, "generation", None)
            if gen is not None:
                cost = float(getattr(gen, "actual_cost_usd", 0) or 0)
                model_used = getattr(gen, "selected_model", model_used)
        except Exception:
            pass
        store.set_result(
            task_id,
            {
                "summary": msg.text[:2000],
                "data": {
                    "text": msg.text,
                    "model": model_used,
                    "cost_usd": cost,
                    "model_route": getattr(agent, "_model_route", None) or {},
                    "model_reason": getattr(agent, "_model_reason", None),
                    "tools_called": list(getattr(agent, "_tools_called", []) or []),
                },
                "tools_used": tools_used,
                "artifacts": artifacts[:50],
            },
            tools_used,
        )
        store.add_event(
            task_id,
            "progress",
            f"Agent done model={model_used} artifacts={len(artifacts)} cost_usd={cost}",
        )
        try:
            from app.jarvis.model_router import record_outcome

            route = getattr(agent, "_model_route", None) or {}
            record_outcome(
                model=str(model_used or agent._model),
                reason=str(getattr(agent, "_model_reason", None) or ""),
                task_class=str(route.get("task_class") or "routine_build"),  # type: ignore[arg-type]
                ok=True,
                extra={"task_id": task_id, "cost_usd": cost},
            )
        except Exception:
            pass
    except Exception as exc:
        log.exception("bridge task failed")
        store.set_status(task_id, "failed", error=str(exc)[:500])
        store.add_event(task_id, "error", str(exc)[:300])
        try:
            from app.jarvis.model_router import classify_task, record_outcome

            route = {}
            model_fail = model_override
            reason_fail = "bridge failure"
            if "agent" in locals() and agent is not None:
                route = getattr(agent, "_model_route", None) or {}
                model_fail = model_fail or getattr(agent, "_model", None)
                reason_fail = str(getattr(agent, "_model_reason", None) or reason_fail)
            record_outcome(
                model=str(model_fail or ""),
                reason=reason_fail,
                task_class=str(route.get("task_class") or classify_task(goal)),  # type: ignore[arg-type]
                ok=False,
                extra={"task_id": task_id, "error": str(exc)[:200]},
            )
        except Exception:
            pass


@router.get("/status")
async def bridge_status(
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    store = _store_get()
    running = store.list_tasks(status="running", limit=50)
    queued = store.list_tasks(status="queued", limit=50)
    return {
        "ok": True,
        "version": "1",
        "workspace": str(default_workspace()),
        "adapters": {
            "realtime": str(os.environ.get("JARVIS_REALTIME", "true")).lower()
            not in {"0", "false", "off"},
            "jarvis_tools": True,
            "prime": str(os.environ.get("PRIME_AGENT_ENABLED", "false")).lower()
            in {"1", "true", "yes", "on"},
            "bridge": True,
        },
        "permissions": {
            "profile": current_profile(),
            "max_tier_auto": f"L{int(max_auto_tier())}",
            "bridge_max_tier_auto": f"L{int(bridge_max_auto_tier())}",
        },
        "active_tasks": len(running) + len(queued),
        "uptime_sec": int(time.time() - _START),
    }


@router.get("/capabilities")
async def bridge_capabilities(
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    return {
        "tools": list_tools_public(),
        "profiles": ["locked", "personal", "power"],
        "confirm_required_from_tier": f"L{int(bridge_max_auto_tier()) + 1}",
    }


@router.post("/tasks", status_code=201)
async def create_task(
    body: TaskCreate,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    _rate_limit(body.source)
    store = _store_get()
    ctx = dict(body.context or {})
    if body.engine:
        ctx["engine"] = body.engine.strip().lower()
    task = store.create_task(
        goal=body.goal.strip(),
        source=body.source.strip(),
        priority=body.priority,
        context=ctx,
    )
    # Each bridge task starts with a clean taint slate (ORCH-297)
    # and the trusted user goal (ORCH-376).
    get_gateway().clear_taint(
        f"bridge:{body.source.strip() or 'agent'}",
        goal=body.goal.strip(),
    )
    # fire and forget execution
    asyncio.create_task(_execute_task(task["task_id"]))
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "created_at": task["created_at"],
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    task = _store_get().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    limit: int = 20,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    return {"tasks": _store_get().list_tasks(status=status, limit=limit)}


def _apply_bridge_confirm(
    task_id: str,
    confirm_id: str,
    decision: str,
    *,
    require_match: bool = True,
) -> dict[str, Any] | None:
    """Approve or deny a bridge confirm. None if the task is no longer waiting."""
    store = _store_get()
    task = store.get_task(task_id)
    if not task:
        return None
    if task["status"] != "needs_confirm" or not task.get("confirm"):
        return None
    if require_match and confirm_id != task["confirm"].get("id"):
        return None
    gw = get_gateway()
    cid = str(task["confirm"].get("id") or confirm_id)
    gw.discard_pending(cid)
    if decision == "deny":
        store.set_status(task_id, "failed", error="denied by caller")
        return store.get_task(task_id)
    if decision != "approve":
        return None
    conf = task["confirm"]
    store.set_confirm(task_id, None)
    store.set_status(task_id, "running")
    tool = conf.get("tool") or "run_powershell"
    args = conf.get("arguments") or {}
    source = f"bridge:{task.get('source')}"
    result = gw.run(
        tool, args, source=source, max_auto=bridge_max_auto_tier(), confirmed=True
    )
    if not result.get("ok", True) and result.get("error"):
        store.set_status(task_id, "failed", error=str(result.get("error"))[:500])
    else:
        summary = plain_summary(tool, result)
        store.set_result(
            task_id,
            {
                "summary": summary,
                "data": result,
                "tools_used": [tool],
                "artifacts": [],
            },
            [tool],
        )
    return store.get_task(task_id)


async def _auto_approve_bridge_task(
    task_id: str, confirm_id: str, seconds: int
) -> None:
    """ORCH-411: if nobody confirms a bridge task, Accept after the wait."""
    try:
        await asyncio.sleep(max(0, int(seconds)))
        _apply_bridge_confirm(task_id, confirm_id, "approve", require_match=True)
    except Exception:
        log.exception("bridge auto-approve failed for %s", task_id)


@router.post("/tasks/{task_id}/confirm")
async def confirm_task(
    task_id: str,
    body: ConfirmBody,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    store = _store_get()
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] != "needs_confirm" or not task.get("confirm"):
        raise HTTPException(status_code=409, detail="task is not awaiting confirm")
    if body.confirm_id != task["confirm"].get("id"):
        raise HTTPException(status_code=400, detail="confirm_id mismatch")
    decision = body.decision.strip().lower()
    if decision not in {"approve", "deny"}:
        raise HTTPException(status_code=422, detail="decision must be approve or deny")
    updated = _apply_bridge_confirm(task_id, body.confirm_id, decision)
    if not updated:
        raise HTTPException(status_code=409, detail="task is not awaiting confirm")
    return updated


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    store = _store_get()
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] in TERMINAL:
        return task
    conf = task.get("confirm") if isinstance(task.get("confirm"), dict) else None
    if conf and conf.get("id"):
        get_gateway().discard_pending(str(conf["id"]))
    store.set_status(task_id, "cancelled", error="cancelled")
    return store.get_task(task_id)  # type: ignore[return-value]


@router.post("/messages")
async def bridge_message(
    body: MessageBody,
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> dict[str, Any]:
    _auth(x_jarvis_bridge_token)
    _rate_limit(body.source)
    store = _store_get()
    task = store.create_task(goal=body.text.strip(), source=body.source.strip())
    get_gateway().clear_taint(
        f"bridge:{body.source.strip() or 'agent'}",
        goal=body.text.strip(),
    )
    await _execute_task(task["task_id"])
    # poll briefly
    for _ in range(50):
        t = store.get_task(task["task_id"])
        if t and t["status"] in TERMINAL or (t and t["status"] == "needs_confirm"):
            return t  # type: ignore[return-value]
        await asyncio.sleep(0.1)
    return store.get_task(task["task_id"])  # type: ignore[return-value]


@router.get("/events")
async def bridge_events(
    task_id: str = Query(...),
    x_jarvis_bridge_token: str | None = Header(default=None, alias="X-Jarvis-Bridge-Token"),
) -> StreamingResponse:
    _auth(x_jarvis_bridge_token)
    store = _store_get()

    async def gen() -> AsyncIterator[str]:
        last_len = 0
        for _ in range(300):
            task = store.get_task(task_id)
            if not task:
                yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                return
            prog = task.get("progress") or []
            if len(prog) > last_len:
                for p in prog[last_len:]:
                    yield f"event: progress\ndata: {json.dumps({'task_id': task_id, **p})}\n\n"
                last_len = len(prog)
            yield f"event: status\ndata: {json.dumps({'task_id': task_id, 'status': task['status']})}\n\n"
            if task["status"] == "done":
                yield f"event: result\ndata: {json.dumps({'task_id': task_id, 'status': 'done', 'result': task.get('result')})}\n\n"
                return
            if task["status"] in {"failed", "cancelled"}:
                yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'status': task['status'], 'error': task.get('error')})}\n\n"
                return
            if task["status"] == "needs_confirm":
                yield f"event: status\ndata: {json.dumps({'task_id': task_id, 'status': 'needs_confirm', 'confirm': task.get('confirm')})}\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")
