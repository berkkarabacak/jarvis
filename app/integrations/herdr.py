"""Herdr CLI client — thin async wrapper (ORCH Herdr epic).

Docs: https://herdr.dev/docs/agent-automation/
CLI:  https://herdr.dev/docs/cli-reference/
Prefer CLI over raw socket for Windows portability.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from typing import Any, Sequence

log = logging.getLogger("agent_orchestrator.herdr")

# Herdr agent names: [a-z][a-z0-9_-]{0,31}
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class HerdrError(RuntimeError):
    """Raised when the herdr CLI fails or returns unusable output."""


@dataclass
class HerdrConfig:
    bin: str = "herdr"
    session: str = ""
    timeout_ms: int = 120_000
    enabled: bool = False
    default_kind: str = "opencode"

    @classmethod
    def from_settings(cls, settings: Any) -> "HerdrConfig":
        return cls(
            bin=(getattr(settings, "herdr_bin", None) or "herdr").strip() or "herdr",
            session=(getattr(settings, "herdr_session", None) or "").strip(),
            timeout_ms=int(getattr(settings, "herdr_timeout_ms", None) or 120_000),
            enabled=bool(getattr(settings, "herdr_enabled", False)),
            default_kind=(getattr(settings, "herdr_default_kind", None) or "opencode").strip()
            or "opencode",
        )


def sanitize_agent_name(name: str, *, fallback: str = "orch-agent") -> str:
    """Normalize to Herdr's agent name rules."""
    raw = (name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if not cleaned or not cleaned[0].isalpha():
        base = re.sub(r"[^a-z0-9_-]+", "-", fallback.lower()).strip("-_") or "orch-agent"
        if not base[0].isalpha():
            base = "a" + base
        cleaned = base
    cleaned = cleaned[:32]
    if not _AGENT_NAME_RE.match(cleaned):
        cleaned = "orch-agent"
    return cleaned


def _extract_json(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    for candidate in (text, text.splitlines()[-1] if text.splitlines() else text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return json.loads(text[i:])
            except json.JSONDecodeError:
                continue
    raise HerdrError(f"Herdr CLI returned non-JSON stdout: {text[:400]!r}")


def _dig(data: Any, *path: str) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _pick_id(data: Any, *keys: str) -> str | None:
    """Find a string id by key, walking common Herdr result nests."""
    if not isinstance(data, dict):
        return None
    for k in keys:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Documented shapes: .result.root_pane.pane_id, .result.pane.pane_id
    for path in (
        ("result", "root_pane", "pane_id"),
        ("result", "pane", "pane_id"),
        ("result", "move_result", "pane", "pane_id"),
        ("root_pane", "pane_id"),
        ("pane", "pane_id"),
        ("result", "workspace", "workspace_id"),
    ):
        v = _dig(data, *path)
        if isinstance(v, str) and v.strip() and path[-1] in keys:
            return v.strip()
    for nest in ("result", "workspace", "pane", "root_pane", "data", "agent"):
        if nest in data and isinstance(data[nest], dict):
            nested = _pick_id(data[nest], *keys)
            if nested:
                return nested
    return None


class HerdrClient:
    def __init__(self, config: HerdrConfig | None = None) -> None:
        self.config = config or HerdrConfig()

    def resolved_bin(self) -> str | None:
        path = (self.config.bin or "herdr").strip()
        if os.path.isfile(path):
            return path
        return shutil.which(path)

    async def available(self) -> bool:
        return (await self.status()).get("available") is True

    async def status(self) -> dict[str, Any]:
        bin_path = self.resolved_bin()
        if not bin_path:
            return {
                "available": False,
                "enabled": self.config.enabled,
                "bin": self.config.bin,
                "error": f"herdr binary not found: {self.config.bin}",
            }
        # Prefer `herdr status` (JSON when possible); fall back to --version.
        for args in (["status"], ["status", "server"], ["--version"]):
            try:
                data, stdout = await self._run(args, timeout_ms=15_000, allow_plain=True)
                payload: dict[str, Any] = {
                    "available": True,
                    "enabled": self.config.enabled,
                    "bin": bin_path,
                }
                if isinstance(data, dict):
                    payload["status"] = data
                elif isinstance(data, str) and data.strip():
                    payload["version"] = data.strip()
                elif stdout.strip():
                    payload["raw"] = stdout.strip()[:500]
                return payload
            except HerdrError:
                continue
        return {
            "available": False,
            "enabled": self.config.enabled,
            "bin": bin_path,
            "error": "herdr status/--version failed",
        }

    async def workspace_create(self, cwd: str, label: str = "orchestrator") -> str:
        # Creation commands print JSON; --no-focus keeps operator TUI stable.
        args = ["workspace", "create", "--cwd", cwd, "--label", label, "--no-focus"]
        data, _ = await self._run(args)
        pane_id = _pick_id(data, "pane_id", "root_pane_id", "id")
        if not pane_id:
            raise HerdrError(f"workspace create: missing pane id in {data!r}"[:500])
        return pane_id

    async def pane_split(self, pane_id: str, direction: str = "right") -> str:
        args = ["pane", "split", pane_id, "--direction", direction, "--no-focus"]
        data, _ = await self._run(args)
        new_id = _pick_id(data, "pane_id", "id", "new_pane_id")
        if not new_id:
            raise HerdrError(f"pane split: missing pane id in {data!r}"[:500])
        return new_id

    async def agent_start(
        self,
        name: str,
        kind: str,
        pane_id: str,
        extra_args: Sequence[str] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        safe_name = sanitize_agent_name(name)
        # herdr agent start <name> --kind KIND --pane ID [--timeout MS] [-- <args...>]
        start_timeout = timeout_ms
        if start_timeout is None:
            start_timeout = min(30_000, max(3_001, self.config.timeout_ms))
        start_timeout = max(3_001, min(300_000, int(start_timeout)))
        args = [
            "agent",
            "start",
            safe_name,
            "--kind",
            kind,
            "--pane",
            pane_id,
            "--timeout",
            str(start_timeout),
        ]
        if extra_args:
            args.append("--")
            args.extend(str(x) for x in extra_args)
        data, _ = await self._run(args, timeout_ms=start_timeout + 5_000)
        return data if isinstance(data, dict) else {"raw": data, "name": safe_name}

    async def agent_prompt(
        self,
        target: str,
        text: str,
        *,
        wait: bool = True,
        until: Sequence[str] = ("idle", "done", "blocked"),
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        # Do not log full prompt text (may contain secrets).
        log.info("herdr agent prompt target=%s wait=%s chars=%s", target, wait, len(text or ""))
        # herdr agent prompt <target> <text> [--wait] [--until STATUS]... [--timeout MS]
        args = ["agent", "prompt", target, text]
        t_ms = int(timeout_ms or self.config.timeout_ms)
        if wait:
            args.append("--wait")
            for u in until:
                args.extend(["--until", u])
            args.extend(["--timeout", str(t_ms)])
        data, stdout = await self._run(
            args, timeout_ms=t_ms + 5_000, allow_plain=True
        )
        if isinstance(data, dict):
            return data
        return {"raw": data if data is not None else stdout}

    async def agent_wait(
        self,
        target: str,
        *,
        until: Sequence[str] = ("idle", "done", "blocked"),
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        t_ms = int(timeout_ms or self.config.timeout_ms)
        args = ["agent", "wait", target]
        for u in until:
            args.extend(["--until", u])
        args.extend(["--timeout", str(t_ms)])
        data, stdout = await self._run(args, timeout_ms=t_ms + 5_000, allow_plain=True)
        if isinstance(data, dict):
            return data
        return {"raw": data if data is not None else stdout}

    async def agent_read(
        self,
        target: str,
        *,
        source: str = "recent-unwrapped",
        lines: int = 120,
    ) -> str:
        # agent read prints UTF-8 text by default (not JSON).
        args = [
            "agent",
            "read",
            target,
            "--source",
            source,
            "--lines",
            str(lines),
        ]
        data, stdout = await self._run(args, timeout_ms=30_000, allow_plain=True)
        if isinstance(data, dict):
            nested = _dig(data, "result", "read", "text")
            if isinstance(nested, str) and nested.strip():
                return nested
            for key in ("text", "content", "output", "recent"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
            for nest in ("data", "result", "pane", "read"):
                if isinstance(data.get(nest), dict):
                    for key in ("text", "content", "output"):
                        val = data[nest].get(key)
                        if isinstance(val, str) and val.strip():
                            return val
        if isinstance(data, str) and data.strip():
            return data
        return (stdout or "").strip()

    async def agent_list(self) -> list[dict[str, Any]]:
        data, _ = await self._run(["agent", "list"], timeout_ms=30_000, allow_plain=True)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("agents", "items", "data", "result"):
                val = data.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
                if isinstance(val, dict):
                    inner = val.get("agents") or val.get("items")
                    if isinstance(inner, list):
                        return [x for x in inner if isinstance(x, dict)]
        return []

    async def _run(
        self,
        args: list[str],
        *,
        timeout_ms: int | None = None,
        allow_plain: bool = False,
    ) -> tuple[Any, str]:
        bin_path = self.resolved_bin()
        if not bin_path:
            raise HerdrError(f"herdr binary not found: {self.config.bin}")

        cmd = [bin_path, *args]
        if self.config.session:
            cmd = [bin_path, "--session", self.config.session, *args]

        timeout_s = max(1.0, (timeout_ms or self.config.timeout_ms) / 1000.0)
        log.debug("herdr exec: %s", " ".join(cmd[:8]) + ("…" if len(cmd) > 8 else ""))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
        except FileNotFoundError as exc:
            raise HerdrError(f"failed to spawn herdr: {exc}") from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise HerdrError(f"herdr timed out after {timeout_s:.0f}s: {' '.join(args[:4])}") from exc

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        if proc.returncode not in (0, None):
            raise HerdrError(
                f"herdr exit {proc.returncode} for {' '.join(args[:5])}: "
                f"{(stderr or stdout)[:600]}"
            )
        try:
            data = _extract_json(stdout)
            return data, stdout
        except HerdrError:
            if allow_plain and stdout.strip():
                return stdout.strip(), stdout
            if allow_plain and not stdout.strip():
                return None, stdout
            if stdout.strip():
                return stdout.strip(), stdout
            raise HerdrError(
                f"herdr produced empty/non-JSON output for {' '.join(args[:5])}: "
                f"stderr={stderr[:400]!r}"
            )

