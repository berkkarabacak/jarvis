"""Thin OpenAI Agents API client — PR0 spike for issue #26.

Proves we can create a multi-agent session, stream/consume events, and
delete the session. Not wired into Talk, gateway, or ChildSupervisor.

Spike constraints (locked — do not reopen in this module):

- ``environment`` is always ``{"type": "none"}``
- ``max_concurrent_subagents`` defaults to 4 and is capped at 4
- no public default; no Live Talk / realtime / deploy changes
- PR1 may reuse ``taint.CHILD_TAINT_SOURCE`` (``"child"``) when wiring results

The project does not depend on the official ``openai`` SDK, so this module
calls ``POST /v1/agents/sessions`` over HTTP with ``OpenAI-Beta: agents=v1``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

import httpx

from app.jarvis.hosted_openai import openai_api_key

AGENTS_BETA_HEADER = "agents=v1"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_MAX_CONCURRENT_SUBAGENTS = 4
SPIKE_ENVIRONMENT: dict[str, str] = {"type": "none"}
LIVE_FLAG_ENV = "JARVIS_AGENTS_API_LIVE"

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

NOTABLE_EVENT_TYPES = frozenset(
    {
        "agent.session.created",
        "agent.session.subagent.created",
        "agent.session.turn.completed",
        "agent.session.turn.failed",
        "agent.session.turn.cancelled",
        "error",
    }
)
NOTABLE_ITEM_TYPES = frozenset(
    {
        "create_subagent_call",
        "send_subagent_input_call",
        "wait_for_subagents_call",
        "interrupt_subagent_call",
    }
)
TURN_END_TYPES = frozenset(
    {
        "agent.session.turn.completed",
        "agent.session.turn.failed",
        "agent.session.turn.cancelled",
    }
)


class AgentsApiError(RuntimeError):
    """HTTP or protocol error from the Agents API. Never includes API keys."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class AgentsSessionResult:
    """Create-session outcome (JSON body and/or collected stream events)."""

    session_id: str | None
    payload: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    notable: list[dict[str, Any]] = field(default_factory=list)


def agents_api_live_enabled(
    environ: dict[str, str] | None = None,
) -> bool:
    """True only when the operator opts in *and* a key is present.

    CI stays green when ``OPENAI_API_KEY`` is absent.
    """
    env = os.environ if environ is None else environ
    flag = (env.get(LIVE_FLAG_ENV) or "").strip() == "1"
    key = bool((env.get("OPENAI_API_KEY") or "").strip())
    return flag and key


def cap_max_concurrent_subagents(value: int | None = None) -> int:
    if value is None:
        return DEFAULT_MAX_CONCURRENT_SUBAGENTS
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_concurrent_subagents must be an integer") from exc
    if n < 1:
        raise ValueError("max_concurrent_subagents must be >= 1")
    return min(n, DEFAULT_MAX_CONCURRENT_SUBAGENTS)


def build_create_session_body(
    *,
    input: Any = None,
    stream: bool | None = None,
    model: str = DEFAULT_MODEL,
    instructions: str | None = None,
    max_concurrent_subagents: int | None = None,
) -> dict[str, Any]:
    """Request body for ``POST /v1/agents/sessions`` (spike defaults)."""
    agent: dict[str, Any] = {
        "model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "multi_agent": {
            "enabled": True,
            "max_concurrent_subagents": cap_max_concurrent_subagents(
                max_concurrent_subagents
            ),
        },
    }
    if instructions:
        agent["instructions"] = instructions
    body: dict[str, Any] = {
        "agent": agent,
        "environment": dict(SPIKE_ENVIRONMENT),
    }
    if input is not None:
        body["input"] = input
    if stream is not None:
        body["stream"] = bool(stream)
    return body


def input_message_event(text: str) -> dict[str, Any]:
    return {
        "type": "agent.session.input.message",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
    }


def cancel_event() -> dict[str, str]:
    return {"type": "agent.session.input.cancel"}


def session_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("session_id", "id"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    session = payload.get("session")
    if isinstance(session, dict):
        for key in ("id", "session_id"):
            val = session.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def item_type(event: dict[str, Any]) -> str | None:
    item = event.get("item")
    if isinstance(item, dict):
        typ = item.get("type")
        if isinstance(typ, str) and typ:
            return typ
    typ = event.get("item_type")
    if isinstance(typ, str) and typ:
        return typ
    return None


def is_notable_event(event: dict[str, Any]) -> bool:
    typ = event.get("type")
    if typ in NOTABLE_EVENT_TYPES:
        return True
    return item_type(event) in NOTABLE_ITEM_TYPES


def collect_notable_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if isinstance(event, dict) and is_notable_event(event)]


def is_coordinator_turn_end(event: dict[str, Any]) -> bool:
    if event.get("type") not in TURN_END_TYPES:
        return False
    turn = event.get("turn")
    if not isinstance(turn, dict):
        return True
    return turn.get("subagent_id") in (None, "")


def iter_sse_events(text: str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from an SSE body (``data:`` frames)."""
    data_lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if line.startswith(":"):
            continue
        if not line:
            yield from _flush_sse_data(data_lines)
            data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    yield from _flush_sse_data(data_lines)


def consume_until_turn_end(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect events through the coordinator turn completed/failed/cancelled."""
    collected: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        collected.append(event)
        if is_coordinator_turn_end(event):
            break
    return collected


def _flush_sse_data(data_lines: list[str]) -> Iterator[dict[str, Any]]:
    if not data_lines:
        return
    payload = "\n".join(data_lines).strip()
    if not payload or payload == "[DONE]":
        return
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return
    if isinstance(obj, dict):
        yield obj


def _require_session_id(session_id: str) -> str:
    sid = (session_id or "").strip()
    if not SESSION_ID_RE.match(sid):
        raise AgentsApiError("invalid session id")
    return sid


def _safe_error_text(response: httpx.Response) -> str:
    text = (response.text or "").strip()
    if len(text) > 300:
        text = text[:300] + "…"
    # Never echo bearer tokens if a proxy reflected headers.
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", text)
    return text


class AgentsApiClient:
    """Minimal HTTP client for ``/v1/agents/sessions``.

    Inject ``client`` in tests (``httpx.MockTransport``). Production callers
    pass a key or rely on ``OPENAI_API_KEY`` / ``HOSTED_OPENAI_KEY``.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else openai_api_key()).strip()
        if not self._api_key:
            raise AgentsApiError("OpenAI API key is not set")
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._client = client

    def _headers(self, *, accept: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": AGENTS_BETA_HEADER,
        }
        if accept:
            headers["Accept"] = accept
        return headers

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout, base_url=self._base_url)

    def _close_if_owned(self, client: httpx.Client) -> None:
        if client is not self._client:
            client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        client = self._http()
        try:
            request = client.build_request(
                method,
                url,
                headers=self._headers(accept=accept),
                json=json_body,
                params=params,
            )
            response = client.send(request)
            response.read()
            if response.status_code >= 400:
                raise AgentsApiError(
                    f"Agents API {method} {path} failed ({response.status_code}): "
                    f"{_safe_error_text(response)}",
                    status_code=response.status_code,
                )
            return response
        finally:
            self._close_if_owned(client)

    def create_session(
        self,
        *,
        input: Any = None,
        stream: bool = False,
        model: str = DEFAULT_MODEL,
        instructions: str | None = None,
        max_concurrent_subagents: int | None = None,
    ) -> AgentsSessionResult:
        body = build_create_session_body(
            input=input,
            stream=stream,
            model=model,
            instructions=instructions,
            max_concurrent_subagents=max_concurrent_subagents,
        )
        if stream:
            response = self._request(
                "POST",
                "/agents/sessions",
                json_body=body,
                accept="text/event-stream",
            )
            try:
                events = list(iter_sse_events(response.text))
            finally:
                response.close()
            session_id = None
            for event in events:
                session_id = session_id_from_payload(event)
                if session_id:
                    break
            return AgentsSessionResult(
                session_id=session_id,
                events=events,
                notable=collect_notable_events(events),
            )
        response = self._request("POST", "/agents/sessions", json_body=body)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise AgentsApiError("create session returned non-JSON") from exc
        if not isinstance(payload, dict):
            raise AgentsApiError("create session returned a non-object")
        return AgentsSessionResult(
            session_id=session_id_from_payload(payload),
            payload=payload,
        )

    def post_events(
        self,
        session_id: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        sid = _require_session_id(session_id)
        response = self._request(
            "POST",
            f"/agents/sessions/{sid}/events",
            json_body={"events": events},
        )
        if not (response.text or "").strip():
            return None
        try:
            data = response.json()
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def send_message(self, session_id: str, text: str) -> dict[str, Any] | None:
        return self.post_events(session_id, [input_message_event(text)])

    def cancel_turn(self, session_id: str) -> dict[str, Any] | None:
        return self.post_events(session_id, [cancel_event()])

    def delete_session(self, session_id: str) -> dict[str, Any] | None:
        sid = _require_session_id(session_id)
        response = self._request("DELETE", f"/agents/sessions/{sid}")
        if not (response.text or "").strip():
            return {"id": sid, "deleted": True}
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"id": sid, "deleted": True}
        return data if isinstance(data, dict) else {"id": sid, "deleted": True}

    def stream_events(self, session_id: str) -> list[dict[str, Any]]:
        """GET ``/sessions/{id}/events?stream=true`` and collect SSE events."""
        sid = _require_session_id(session_id)
        response = self._request(
            "GET",
            f"/agents/sessions/{sid}/events",
            params={"stream": "true"},
            accept="text/event-stream",
        )
        try:
            return list(iter_sse_events(response.text))
        finally:
            response.close()


__all__ = [
    "AGENTS_BETA_HEADER",
    "DEFAULT_MAX_CONCURRENT_SUBAGENTS",
    "DEFAULT_MODEL",
    "LIVE_FLAG_ENV",
    "NOTABLE_EVENT_TYPES",
    "NOTABLE_ITEM_TYPES",
    "SPIKE_ENVIRONMENT",
    "AgentsApiClient",
    "AgentsApiError",
    "AgentsSessionResult",
    "agents_api_live_enabled",
    "build_create_session_body",
    "cancel_event",
    "cap_max_concurrent_subagents",
    "collect_notable_events",
    "consume_until_turn_end",
    "input_message_event",
    "is_coordinator_turn_end",
    "is_notable_event",
    "iter_sse_events",
    "session_id_from_payload",
]
