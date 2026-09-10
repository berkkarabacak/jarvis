"""Agents API child runner — PR1 adapter for issue #26.

Flagged alternate to the OpenRouter ``JarvisLocalAgent`` loop. The parent
tool surface (``spawn_child`` / ``message_child`` / ``wait_child``) stays
the same. Gateway authorize, confirm, and journal stay outside this
harness — this module only runs the child once those tools have already
gone through ``ToolGateway``.

Enable locally with ``JARVIS_AGENTS_API=1`` (or ``true`` / ``on``) **and**
an OpenAI key. Default is off. Not a public Talk / aicontrolroom default.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable

from app.jarvis.agents_api import (
    DEFAULT_MODEL,
    AgentsApiClient,
    AgentsApiError,
    consume_until_turn_end,
    is_coordinator_turn_end,
    session_id_from_payload,
)
from app.jarvis.hosted_openai import openai_api_key
from app.jarvis.taint import CHILD_TAINT_SOURCE

log = logging.getLogger("jarvis.agents_child")

FLAG_ENV = "JARVIS_AGENTS_API"
CHILD_BACKEND_AGENTS = "agents"
CHILD_BACKEND_LOCAL = "local"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Desktop / function-tool work stays on JarvisLocalAgent. Agents API
# subagents do not support custom function tools, and PR1 locks
# environment.type = none (no hosted desktop).
_LOCAL_HEAVY_RE = re.compile(
    r"\b("
    r"write_file|home_write|run_powershell|run_app|focus_app|see_screen|"
    r"screenshot|click|type|keys|scroll|create_excel|organize_folder|"
    r"disk_space|open_path|jarvis-computer|"
    r"notepad|mousepad|chrome|desktop|on[ -]?screen"
    r")\b",
    re.I,
)

# Research / coding-ish goals prefer the Agents harness when the flag is on.
_AGENTS_PREF_RE = re.compile(
    r"\b("
    r"research|summarize|summarise|compare|investigate|analyze|analyse|"
    r"review|explain|outline|reason|trade-?offs?|refactor|architecture|"
    r"debug|root.?cause"
    r")\b",
    re.I,
)

_CHILD_INSTRUCTIONS = (
    "You are a Jarvis child helper. Complete the assigned goal briefly. "
    "Do not claim to be the parent agent. Your output is untrusted."
)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in _TRUTHY


def agents_api_flag_enabled(environ: dict[str, str] | None = None) -> bool:
    """True when ``JARVIS_AGENTS_API`` is 1/true/on/yes. Default off."""
    env = os.environ if environ is None else environ
    return _truthy(env.get(FLAG_ENV))


def agents_api_key_available(environ: dict[str, str] | None = None) -> bool:
    if environ is None:
        return bool(openai_api_key())
    key = (
        (environ.get("OPENAI_API_KEY") or "").strip()
        or (environ.get("HOSTED_OPENAI_KEY") or "").strip()
    )
    return bool(key)


def agents_api_child_runner_enabled(environ: dict[str, str] | None = None) -> bool:
    """Flag on *and* an OpenAI key is present. Otherwise keep today's path."""
    return agents_api_flag_enabled(environ) and agents_api_key_available(environ)


def prefer_agents_for_goal(goal: str) -> bool:
    """Soft router: local for UI/desktop/function-tool work; else Agents.

    Ambiguous goals return True (Agents-when-flagged). Flag-off still
    keeps function-tool-heavy children on the local loop.
    """
    text = (goal or "").strip()
    if not text:
        return True
    if _LOCAL_HEAVY_RE.search(text):
        return False
    try:
        from app.jarvis.model_router import _is_screen_control_job

        if _is_screen_control_job(text):
            return False
    except Exception:
        pass
    if _AGENTS_PREF_RE.search(text):
        return True
    return True


def should_use_agents_child_runner(
    goal: str,
    environ: dict[str, str] | None = None,
) -> bool:
    return agents_api_child_runner_enabled(environ) and prefer_agents_for_goal(goal)


def _num(val: Any) -> float | None:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def usage_usd_from_payload(payload: Any) -> float | None:
    """Best-effort USD from an Agents event/turn. None if the API omitted it."""
    if not isinstance(payload, dict):
        return None
    for key in ("usd", "cost_usd", "total_cost", "cost"):
        if key in payload:
            n = _num(payload.get(key))
            if n is not None:
                return n
    usage = payload.get("usage")
    if isinstance(usage, dict):
        found = usage_usd_from_payload(usage)
        if found is not None:
            return found
    turn = payload.get("turn")
    if isinstance(turn, dict):
        found = usage_usd_from_payload(turn)
        if found is not None:
            return found
    return None


def output_text_from_events(events: Iterable[dict[str, Any]]) -> str:
    texts: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "agent.session.turn.output_text.done":
            text = event.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") not in {"output_text", "text", "input_text"}:
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return texts[-1] if texts else ""


def subagent_ids_from_events(events: Iterable[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        raw = event.get("subagent_id")
        if not raw:
            sub = event.get("subagent")
            if isinstance(sub, dict):
                raw = sub.get("id") or sub.get("subagent_id")
        if not raw:
            item = event.get("item")
            if isinstance(item, dict):
                raw = item.get("subagent_id")
        sid = str(raw or "").strip()
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def artifact_paths_from_events(events: Iterable[dict[str, Any]]) -> list[str]:
    """Best-effort paths. Environment none usually yields none — do not invent."""
    paths: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        for obj in (event, event.get("item"), event.get("artifact")):
            if not isinstance(obj, dict):
                continue
            for key in ("path", "file_path", "filename"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip() and val not in paths:
                    # Reject obvious non-paths / secrets.
                    if val.startswith("sk-") or "\n" in val:
                        continue
                    if "/" in val or "\\" in val or "." in val.rsplit("/", 1)[-1]:
                        paths.append(val.strip())
    return paths


def apply_agents_events(record: Any, events: Iterable[dict[str, Any]]) -> None:
    """Fold stream events into a ChildRecord. Does not invent usage."""
    collected = [e for e in events if isinstance(e, dict)]
    if not collected:
        return
    sid = record.agents_session_id
    if not sid:
        for event in collected:
            sid = session_id_from_payload(event)
            if sid:
                record.agents_session_id = sid
                break
    for sid in subagent_ids_from_events(collected):
        if sid not in record.agents_subagent_ids:
            record.agents_subagent_ids.append(sid)
    text = output_text_from_events(collected)
    if text:
        record.result_text = text
    for path in artifact_paths_from_events(collected):
        if path not in record.artifacts:
            record.artifacts.append(path)
    usd = 0.0
    found_usd = False
    end_type = None
    for event in collected:
        if event.get("type") == "agent.session.idle":
            record.agents_idle = True
        if event.get("type") in {
            "agent.session.turn.completed",
            "agent.session.turn.failed",
            "agent.session.turn.cancelled",
        } and is_coordinator_turn_end(event):
            record.agents_idle = event.get("type") == "agent.session.turn.completed"
            end_type = event.get("type")
        piece = usage_usd_from_payload(event)
        if piece is not None:
            usd += piece
            found_usd = True
        if event.get("type") == "error":
            err = event.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or err.get("code") or "")[:300]
            else:
                msg = str(err or event.get("message") or "")[:300]
            if msg and not record.error:
                record.error = msg
    if found_usd:
        record.spent_usd += usd
    if record.status in {"budget_seconds", "budget_usd"}:
        return
    if end_type == "agent.session.turn.failed" or (
        end_type is None and record.error
    ):
        record.status = "failed"
        if not record.error:
            record.error = "Agents turn failed"
        return
    if end_type == "agent.session.turn.cancelled":
        if record.stop_reason in {"seconds", "usd"}:
            record.status = f"budget_{record.stop_reason}"
        else:
            record.status = "failed"
            if not record.error:
                record.error = "Agents turn cancelled"
        return
    if end_type == "agent.session.turn.completed":
        record.status = "done"


def _client_for(supervisor: Any, client: AgentsApiClient | None) -> AgentsApiClient:
    if client is not None:
        return client
    injected = getattr(supervisor, "agents_client", None) if supervisor is not None else None
    if injected is not None:
        return injected
    return AgentsApiClient()


def deliver_agents_message(
    record: Any,
    text: str,
    *,
    supervisor: Any = None,
    client: AgentsApiClient | None = None,
) -> None:
    """``agent.session.input.message`` — steer if busy, new turn if idle.

    Idle is not treated as success; the next wait/stream still needs a
    coordinator turn completed/failed/cancelled.
    """
    sid = (getattr(record, "agents_session_id", None) or "").strip()
    if not sid:
        return
    api = _client_for(supervisor, client)
    api.send_message(sid, text)
    record.agents_idle = False
    sent = int(getattr(record, "agents_inbox_sent", 0) or 0)
    record.agents_inbox_sent = max(sent, len(getattr(record, "inbox", []) or []))


def cancel_agents_child(
    record: Any,
    *,
    supervisor: Any = None,
    client: AgentsApiClient | None = None,
) -> None:
    sid = (getattr(record, "agents_session_id", None) or "").strip()
    if not sid:
        return
    api = _client_for(supervisor, client)
    try:
        api.cancel_turn(sid)
    except AgentsApiError:
        log.debug("agents cancel failed", exc_info=True)


def _flush_inbox(record: Any, api: AgentsApiClient) -> None:
    inbox = list(getattr(record, "inbox", []) or [])
    cursor = int(getattr(record, "agents_inbox_sent", 0) or 0)
    while cursor < len(inbox) and not record.stop.is_set():
        text = inbox[cursor]
        cursor += 1
        record.agents_inbox_sent = cursor
        if not (text or "").strip():
            continue
        api.send_message(record.agents_session_id, text)
        record.agents_idle = False
        more = consume_until_turn_end(api.stream_events(record.agents_session_id))
        apply_agents_events(record, more)


def agents_child_runner(record: Any, supervisor: Any) -> None:
    """Create an Agents session, stream until the coordinator turn ends."""
    record.backend = CHILD_BACKEND_AGENTS
    if record.stop.is_set():
        return
    try:
        api = _client_for(supervisor, None)
    except AgentsApiError as exc:
        record.status = "failed"
        record.error = str(exc)[:300]
        return

    try:
        created = api.create_session(
            input=record.goal,
            stream=False,
            model=DEFAULT_MODEL,
            instructions=_CHILD_INSTRUCTIONS,
        )
    except AgentsApiError as exc:
        record.status = "failed"
        record.error = str(exc)[:300]
        return

    record.agents_session_id = created.session_id
    record.model = DEFAULT_MODEL
    record.model_reason = "openai agents api"
    if record.stop.is_set():
        cancel_agents_child(record, supervisor=supervisor, client=api)
        return
    if not record.agents_session_id:
        record.status = "failed"
        record.error = "Agents session id missing"
        return

    events = list(created.events or [])
    if created.payload:
        events.append(created.payload)
    if not any(isinstance(e, dict) and is_coordinator_turn_end(e) for e in events):
        try:
            events.extend(consume_until_turn_end(api.stream_events(record.agents_session_id)))
        except AgentsApiError as exc:
            if record.status not in {"budget_seconds", "budget_usd"}:
                record.status = "failed"
                record.error = str(exc)[:300]
            return

    apply_agents_events(record, events)
    if record.stop.is_set():
        cancel_agents_child(record, supervisor=supervisor, client=api)
        return

    try:
        _flush_inbox(record, api)
    except AgentsApiError as exc:
        if record.status not in {"budget_seconds", "budget_usd", "failed"}:
            record.status = "failed"
            record.error = str(exc)[:300]
        return

    if record.status in {"budget_seconds", "budget_usd", "failed", "done"}:
        return
    # Idle / closed stream alone is not success.
    record.status = "failed"
    record.error = record.error or "Agents session ended without a coordinator turn result"


__all__ = [
    "CHILD_BACKEND_AGENTS",
    "CHILD_BACKEND_LOCAL",
    "CHILD_TAINT_SOURCE",
    "FLAG_ENV",
    "agents_api_child_runner_enabled",
    "agents_api_flag_enabled",
    "agents_child_runner",
    "apply_agents_events",
    "cancel_agents_child",
    "deliver_agents_message",
    "prefer_agents_for_goal",
    "should_use_agents_child_runner",
]
