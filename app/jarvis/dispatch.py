"""Heavy-task dispatch: Jarvis tools vs Prime RPC ==GRoK== (ORCH-252 B2).

Light laptop facts stay on ToolGateway. Long coding jobs route to Prime when
enabled. Prime failure never takes down Realtime voice.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

log = logging.getLogger("jarvis.dispatch")

Engine = Literal["jarvis", "prime"]

_HEAVY_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(refactor|multi-?file|codebase|repository|repo)\b",
        r"\b(implement|build|scaffold|migrate)\b.+\b(feature|module|service|api)\b",
        r"\b(write|create)\b.+\b(test suite|unit tests|integration tests)\b",
        r"\bprime\b",
        r"\blong[- ]?running\b",
        r"\bautonomous\b",
        r"\b(large|big)\b.+\b(refactor|migration|upgrade)\b",
        r"\bdispatch\s+to\s+prime\b",
        r"\buse\s+prime\b",
    )
)

_LIGHT_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(disk|free space|storage|ram|cpu|system info)\b",
        r"\b(open|launch|start)\b.+\b(notepad|calc|excel|chrome|browser)\b",
        r"\b(list|show)\b.+\b(desktop|downloads|documents|files)\b",
        r"\b(screenshot|what('s| is) on (my )?screen)\b",
        r"\bremember\b",
        r"\bhow much\b",
    )
)


@dataclass
class DispatchDecision:
    engine: Engine
    reason: str
    force: bool = False


def prime_enabled() -> bool:
    if str(os.environ.get("PRIME_AGENT_ENABLED", "")).lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    # never on public guest
    if str(os.environ.get("PUBLIC_GUEST_PROFILE", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    if str(os.environ.get("HERDR_ENABLED", "")).lower() in {"1", "true"} and str(
        os.environ.get("JARVIS_ENABLED", "true")
    ).lower() in {"0", "false", "off"}:
        return False
    return True


def classify_goal(goal: str, *, explicit: str | None = None) -> DispatchDecision:
    g = (goal or "").strip()
    exp = (explicit or "").strip().lower()
    if exp in {"prime", "rpc", "heavy"}:
        return DispatchDecision("prime", "explicit engine=prime", force=True)
    if exp in {"jarvis", "local", "tools", "light"}:
        return DispatchDecision("jarvis", "explicit engine=jarvis", force=True)
    if not g:
        return DispatchDecision("jarvis", "empty goal")
    for pat in _LIGHT_PATTERNS:
        if pat.search(g):
            return DispatchDecision("jarvis", f"light pattern {pat.pattern[:40]}")
    for pat in _HEAVY_PATTERNS:
        if pat.search(g):
            return DispatchDecision("prime", f"heavy pattern {pat.pattern[:40]}")
    # default local tools — voice-first laptop colleague
    return DispatchDecision("jarvis", "default jarvis")


async def run_prime_mission(
    goal: str,
    *,
    memory: Any | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a Prime RPC session for a heavy goal; degrade gracefully."""
    mission_id = "msn_" + uuid.uuid4().hex[:12]
    if not prime_enabled():
        return {
            "ok": False,
            "engine": "prime",
            "mission_id": mission_id,
            "error": "Prime is not enabled on this host",
            "degraded": True,
        }
    try:
        from app.executive.adapters.prime_rpc import build_prime_agent_from_environment

        agent = build_prime_agent_from_environment()
        if getattr(agent, "name", "") in {"null", ""}:
            return {
                "ok": False,
                "engine": "prime",
                "mission_id": mission_id,
                "error": "Prime RPC adapter unavailable",
                "degraded": True,
            }

        # inject memory
        inject = ""
        if memory is not None and hasattr(memory, "context_blob"):
            try:
                inject = memory.context_blob(max_chars=1200)
            except Exception:
                inject = ""
        prompt = goal
        if inject:
            prompt = f"{inject}\n\n---\nMission:\n{goal}"

        from app.jarvis.prime_progress import get_progress_bus

        bus = get_progress_bus()
        bus.emit(mission_id, "Prime mission started.")

        sess = await agent.start_session(role_name="jarvis-prime")
        prime_sid = getattr(sess, "session_id", None) or getattr(sess, "id", None)
        bus.emit(mission_id, "Prime session connected; working on your task.")
        msg = await agent.send_message(str(prime_sid), message=prompt)
        text = getattr(msg, "text", None) or str(msg)
        try:
            await agent.stop_session(str(prime_sid), reason="mission_complete")
        except Exception:
            pass
        bus.emit(mission_id, "Prime mission finished.")

        if memory is not None and hasattr(memory, "add_mission_summary"):
            try:
                memory.add_mission_summary(
                    text[:4000],
                    title=(goal[:80] or "Prime mission"),
                    mission_id=mission_id,
                    tools_used=["prime-rpc"],
                    prime_session_id=str(prime_sid) if prime_sid else None,
                )
            except Exception:
                log.exception("failed to persist mission summary")

        return {
            "ok": True,
            "engine": "prime",
            "mission_id": mission_id,
            "prime_session_id": str(prime_sid) if prime_sid else None,
            "summary": text[:2000],
            "context": context or {},
            "progress": bus.recent(limit=5),
        }
    except Exception as exc:
        log.warning("prime mission failed (voice continues): %s", exc)
        return {
            "ok": False,
            "engine": "prime",
            "mission_id": mission_id,
            "error": str(exc)[:400],
            "degraded": True,
        }
