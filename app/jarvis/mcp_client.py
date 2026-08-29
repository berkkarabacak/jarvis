"""Minimal MCP JSON-RPC client for tools/list + tools/call (ORCH-323).

Supports stdio (Content-Length framing, NDJSON fallback) and HTTP POST.
Prefers stdlib + httpx; does not require the ``mcp`` package.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.jarvis.mcp_registry import (
    compute_tool_tier,
    namespaced_tool,
    upsert_server,
)
from app.jarvis.mcp_tokens import decrypt_token

log = logging.getLogger("jarvis.mcp.client")

DEFAULT_TIMEOUT_S = 20.0
PROTOCOL_VERSION = "2024-11-05"
# GitHub remote MCP (and other HTTP servers) prefer the 2025 streamable-HTTP era.
HTTP_PROTOCOL_VERSION = "2025-03-26"


@dataclass
class McpCallResult:
    ok: bool
    result: Any = None
    error: str | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _frame_message(msg: dict[str, Any]) -> bytes:
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_framed(stdout) -> dict[str, Any] | None:
    """Read one Content-Length framed JSON message from a binary stream."""
    headers: dict[str, str] = {}
    while True:
        line = stdout.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        try:
            text = line.decode("ascii", errors="replace").rstrip("\r\n")
        except Exception:
            continue
        if ":" in text:
            k, v = text.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length_s = headers.get("content-length")
    if not length_s:
        return None
    try:
        length = int(length_s)
    except ValueError:
        return None
    body = stdout.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


class StdioMcpSession:
    """Short-lived stdio MCP session: initialize → tools/list or tools/call."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        import queue

        self.command = command
        self.args = list(args or [])
        self.env = env
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._out_q: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    def __enter__(self) -> "StdioMcpSession":
        self.open()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def open(self) -> None:
        if self._proc is not None:
            return
        cmd = [self.command, *self.args]
        child_env = os.environ.copy()
        if self.env:
            child_env.update(self.env)
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
        )

        def _reader() -> None:
            try:
                while self._proc is not None and self._proc.stdout is not None:
                    resp = _read_framed(self._proc.stdout)
                    if resp is None:
                        self._out_q.put(("eof", None))
                        return
                    self._out_q.put(("msg", resp))
            except Exception as exc:  # pragma: no cover
                self._out_q.put(("err", exc))

        self._reader_thread = threading.Thread(
            target=_reader, name="mcp-stdio-reader", daemon=True
        )
        self._reader_thread.start()
        self._initialize()

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import queue

        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP stdio session not open")
        req_id = _new_id()
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        with self._lock:
            self._proc.stdin.write(_frame_message(msg))
            self._proc.stdin.flush()
            deadline = time.time() + self.timeout_s
            while time.time() < deadline:
                remaining = max(0.05, deadline - time.time())
                try:
                    kind, payload = self._out_q.get(timeout=min(0.5, remaining))
                except queue.Empty:
                    if self._proc.poll() is not None:
                        err = b""
                        try:
                            err = self._proc.stderr.read() if self._proc.stderr else b""
                        except Exception:
                            pass
                        raise RuntimeError(
                            f"MCP process exited early: {(err or b'').decode('utf-8', errors='replace')[:400]}"
                        )
                    continue
                if kind == "eof":
                    raise RuntimeError("MCP process closed stdout")
                if kind == "err":
                    raise RuntimeError(str(payload)[:400])
                resp = payload
                if not isinstance(resp, dict) or "id" not in resp:
                    continue
                if resp.get("id") != req_id:
                    continue
                if "error" in resp and resp["error"]:
                    err = resp["error"]
                    if isinstance(err, dict):
                        raise RuntimeError(str(err.get("message") or err)[:400])
                    raise RuntimeError(str(err)[:400])
                return resp.get("result") if "result" in resp else {}
            raise TimeoutError(f"MCP stdio timeout on {method}")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP stdio session not open")
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        with self._lock:
            self._proc.stdin.write(_frame_message(msg))
            self._proc.stdin.flush()

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jarvis-mcp", "version": "0.1"},
            },
        )
        try:
            self._notify("notifications/initialized", {})
        except Exception:
            pass

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            return []
        return [t for t in tools if isinstance(t, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )


def _parse_sse_jsonrpc(body: str) -> dict[str, Any]:
    """Extract the first JSON-RPC object from an SSE ``text/event-stream`` body.

    GitHub remote MCP returns ``event: message`` / ``data: {...}`` frames.
    """
    data_lines: list[str] = []
    for raw in (body or "").splitlines():
        line = raw.rstrip("\r")
        if not line:
            if data_lines:
                break
            continue
        if line.startswith(":"):
            # SSE comment / keepalive
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        # Ignore event:/id:/retry: — we only need data payloads.
    if not data_lines:
        raise RuntimeError("MCP SSE response contained no data payload")
    blob = "\n".join(data_lines).strip()
    data = json.loads(blob)
    if not isinstance(data, dict):
        raise RuntimeError("MCP SSE data was not a JSON object")
    return data


def _decode_http_jsonrpc_response(resp: httpx.Response) -> dict[str, Any]:
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.text or ""
    if "text/event-stream" in ctype or text.lstrip().startswith("event:"):
        return _parse_sse_jsonrpc(text)
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("MCP HTTP response was not a JSON object")
    return data


def http_jsonrpc(
    url: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    notify: bool = False,
) -> Any:
    """POST a JSON-RPC request (or notification) to an HTTP MCP endpoint.

    Accepts both ``application/json`` and SSE ``text/event-stream`` responses
    (required for GitHub ``api.githubcopilot.com/mcp``).
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }
    if not notify:
        payload["id"] = _new_id()
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        if notify:
            # Notifications may return 202/204/empty; treat as success.
            if not (resp.content or b"").strip():
                return None
        data = _decode_http_jsonrpc_response(resp)
    if data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            raise RuntimeError(str(err.get("message") or err)[:400])
        raise RuntimeError(str(err)[:400])
    return data.get("result")


def http_list_tools(url: str, *, token: str | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
    # Some servers want initialize first; try tools/list directly, fall back.
    try:
        http_jsonrpc(
            url,
            "initialize",
            {
                "protocolVersion": HTTP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jarvis-mcp", "version": "0.1"},
            },
            token=token,
            timeout_s=timeout_s,
        )
        try:
            http_jsonrpc(
                url,
                "notifications/initialized",
                {},
                token=token,
                timeout_s=timeout_s,
                notify=True,
            )
        except Exception:
            log.debug("MCP HTTP notifications/initialized skipped", exc_info=True)
    except Exception:
        log.debug("MCP HTTP initialize skipped/failed; continuing to tools/list", exc_info=True)
    result = http_jsonrpc(url, "tools/list", {}, token=token, timeout_s=timeout_s)
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return []
    return [t for t in tools if isinstance(t, dict)]


def http_call_tool(
    url: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Any:
    return http_jsonrpc(
        url,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        token=token,
        timeout_s=timeout_s,
    )


def _normalize_discovered(
    server: dict[str, Any],
    raw_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sid = str(server.get("id") or "")
    trusted = bool(server.get("trusted", False))
    max_tier = server.get("max_tier") or "L5"
    out: list[dict[str, Any]] = []
    for t in raw_tools:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
        # Also accept top-level hints some servers send
        for key in ("readOnlyHint", "destructiveHint", "openWorldHint"):
            if key in t and key not in ann:
                ann[key] = t[key]
        tier = compute_tool_tier(trusted=trusted, max_tier=max_tier, annotations=ann)
        out.append(
            {
                "name": name,
                "namespaced": namespaced_tool(sid, name),
                "description": str(t.get("description") or "")[:500],
                "tier": f"L{int(tier)}",
                "annotations": dict(ann),
            }
        )
    return out


def refresh_server(server: dict[str, Any], *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Discover tools; update status/last_error/discovered_tools; persist."""
    updated = dict(server)
    updated["updated_at"] = time.time()
    if not updated.get("enabled", True):
        updated["status"] = "disabled"
        updated["last_error"] = None
        return upsert_server(updated)

    transport = (updated.get("transport") or "stdio").strip().lower()
    token = decrypt_token(updated.get("token_enc"))
    try:
        if transport == "http":
            url = str(updated.get("url") or "").strip()
            if not url:
                raise ValueError("HTTP MCP server requires a url")
            raw = http_list_tools(url, token=token or None, timeout_s=timeout_s)
        elif transport == "stdio":
            command = str(updated.get("command") or "").strip()
            if not command:
                raise ValueError("stdio MCP server requires a command")
            args = list(updated.get("args") or [])
            with StdioMcpSession(command, args, timeout_s=timeout_s) as session:
                raw = session.list_tools()
        else:
            raise ValueError(f"unsupported transport: {transport}")
        updated["discovered_tools"] = _normalize_discovered(updated, raw)
        updated["status"] = "ok"
        updated["last_error"] = None
    except Exception as exc:
        # Degrade gracefully — keep prior tools, mark failed
        updated["status"] = "failed"
        updated["last_error"] = str(exc)[:400]
        log.warning("MCP refresh failed for %s: %s", updated.get("id"), updated["last_error"])
    return upsert_server(updated)


def call_mcp_tool(
    server: dict[str, Any],
    tool_short_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> McpCallResult:
    """Invoke tools/call. Never raises — returns ok:false on failure."""
    if not server.get("enabled", True):
        return McpCallResult(False, error="MCP server is disabled")
    if (server.get("status") or "") == "failed":
        err = server.get("last_error") or "MCP server is in a failed state"
        return McpCallResult(False, error=str(err)[:300])

    transport = (server.get("transport") or "stdio").strip().lower()
    token = decrypt_token(server.get("token_enc"))
    try:
        if transport == "http":
            url = str(server.get("url") or "").strip()
            if not url:
                return McpCallResult(False, error="HTTP MCP server has no url")
            result = http_call_tool(
                url, tool_short_name, arguments, token=token or None, timeout_s=timeout_s
            )
        elif transport == "stdio":
            command = str(server.get("command") or "").strip()
            if not command:
                return McpCallResult(False, error="stdio MCP server has no command")
            args = list(server.get("args") or [])
            with StdioMcpSession(command, args, timeout_s=timeout_s) as session:
                result = session.call_tool(tool_short_name, arguments)
        else:
            return McpCallResult(False, error=f"unsupported transport: {transport}")
        return McpCallResult(True, result=result)
    except Exception as exc:
        msg = str(exc)[:300]
        log.warning("MCP tools/call failed (%s/%s): %s", server.get("id"), tool_short_name, msg)
        return McpCallResult(False, error=msg)
