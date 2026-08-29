"""Last-N public Talk turns on the host (one public session).

Durable JSON next to settings: ``{workspace}/Memory/public_talk.json``.
Not a daily journal dump — full You / Jarvis / tool lines so an operator
can read the hosted Talk struggle after the browser is gone.

Writes are public-safe (no API key). Secrets, cookies, Authorization
headers, raw JWTs, and long base64 are stripped before disk.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.audit import scrub_speech, scrub_text
from app.jarvis.workspace import default_workspace
from app.memory.sanitize import sanitize_text

FILENAME = "public_talk.json"
MAX_TURNS = 80
MAX_TEXT = 2000
MAX_RESULT = 400
MAX_TOOL_NAME = 64
DEDUP_WINDOW_SEC = 15.0
RATE_WINDOW_SEC = 60.0
DEFAULT_RATE_PER_MIN = 60
ROLES = frozenset({"you", "jarvis", "tool"})
SPEECH_ROLES = frozenset({"you", "jarvis"})
# A quiet gap starts a new visit. Thin visits still get the last chat.
SESSION_GAP_SEC = 45 * 60
THIN_SESSION_TURNS = 4
ONESHOT_MAX_TURNS = 12
ONESHOT_TURN_CHARS = 400
RECAP_MAX_TURNS = 8
RECAP_MAX_CHARS = 900
RECAP_LINE_CHARS = 360

# Cookies / Set-Cookie / Cookie: name=value; ...
_COOKIE_RE = re.compile(
    r"(?i)\b(?:set-)?cookie(?:s)?\s*[:=]\s*[^\s,;]+(?:\s*;\s*[^\s,;]+=[^\s,;]+)*"
)
# Authorization / X-Api-Key header-shaped assignments (after sanitize_text).
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(?:authorization|x-api-key|x-auth-token)\s*[:=]\s*\S+"
)
# Long base64 / base64url blobs (screenshots, JWTs already half-caught).
_LONG_B64_RE = re.compile(
    r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{80,}={0,2}(?![A-Za-z0-9+/_\-])"
)
_SECRET_KEYS = frozenset(
    {
        "nonce",
        "nonce_code",
        "nonce_prompt",
        "confirm_id",
        "client_secret",
        "authorization",
        "cookie",
        "set_cookie",
        "api_key",
        "token",
        "password",
        "secret",
        "jwt",
    }
)

_lock = threading.Lock()
_rate: dict[str, list[float]] = {}


def talk_log_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else default_workspace()
    return base / "Memory" / FILENAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None = None) -> str:
    stamp = ts or _utc_now()
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rate_limit() -> int:
    raw = (os.environ.get("JARVIS_TALK_LOG_RATE_PER_MIN") or "").strip()
    if raw.isdigit():
        return max(1, min(600, int(raw)))
    return DEFAULT_RATE_PER_MIN


def allow_write(key: str) -> bool:
    """Sliding-window rate limit for public log writes. True = allowed."""
    now = time.time()
    bucket = (key or "anon").strip() or "anon"
    limit = _rate_limit()
    with _lock:
        window = [t for t in _rate.get(bucket, []) if now - t < RATE_WINDOW_SEC]
        if len(window) >= limit:
            _rate[bucket] = window
            return False
        window.append(now)
        _rate[bucket] = window
        return True


def reset_rate_limits() -> None:
    with _lock:
        _rate.clear()


def sanitize_talk_text(text: str | None, *, max_chars: int = MAX_TEXT) -> str:
    """Public-safe snippet: no keys, cookies, Authorization, JWTs, long b64."""
    raw = str(text or "")
    raw = _COOKIE_RE.sub("[REDACTED]", raw)
    raw = _AUTH_HEADER_RE.sub("[REDACTED]", raw)
    raw = _LONG_B64_RE.sub("[REDACTED]", raw)
    raw = scrub_speech(raw)
    raw = scrub_text(raw)
    raw = sanitize_text(raw, max_chars=max_chars)
    return raw.replace("\x00", "").strip()


def _short_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        cleaned = {
            k: v
            for k, v in result.items()
            if str(k).lower().replace("-", "_") not in _SECRET_KEYS
        }
        summary = cleaned.get("summary") or cleaned.get("error") or cleaned.get("reply")
        if isinstance(summary, str) and summary.strip():
            return sanitize_talk_text(summary, max_chars=MAX_RESULT)
        try:
            blob = json.dumps(cleaned, ensure_ascii=False, default=str)
        except TypeError:
            blob = str(cleaned)
        return sanitize_talk_text(blob, max_chars=MAX_RESULT)
    return sanitize_talk_text(str(result), max_chars=MAX_RESULT)


def _empty() -> dict[str, Any]:
    return {"started_at": None, "turns": []}


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    started = raw.get("started_at")
    if not (isinstance(started, str) and started.strip()):
        started = None
    turns: list[dict[str, Any]] = []
    for row in raw.get("turns") or []:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip().lower()
        if role not in ROLES:
            continue
        text = sanitize_talk_text(row.get("text"), max_chars=MAX_TEXT)
        ts = str(row.get("ts") or "").strip() or _iso()
        item: dict[str, Any] = {"ts": ts, "role": role, "text": text}
        tool = str(row.get("tool") or "").strip()[:MAX_TOOL_NAME]
        if tool:
            item["tool"] = tool
        result = row.get("result")
        if result not in (None, ""):
            item["result"] = sanitize_talk_text(str(result), max_chars=MAX_RESULT)
        turns.append(item)
    return {"started_at": started, "turns": turns[-MAX_TURNS:]}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": data.get("started_at"),
        "turns": list(data.get("turns") or [])[-MAX_TURNS:],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _same_turn(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("role") != right.get("role"):
        return False
    if (left.get("text") or "") != (right.get("text") or ""):
        return False
    if (left.get("tool") or "") != (right.get("tool") or ""):
        return False
    return True


def _parse_ts(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        stamp = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def append_turn(
    role: str,
    text: str = "",
    *,
    tool: str | None = None,
    result: Any = None,
    root: Path | None = None,
    ts: str | None = None,
) -> dict[str, Any] | None:
    """Append one public-safe turn. Returns the stored turn, or None if skipped."""
    who = str(role or "").strip().lower()
    if who not in ROLES:
        return None
    said = sanitize_talk_text(text, max_chars=MAX_TEXT)
    tool_name = str(tool or "").strip()[:MAX_TOOL_NAME]
    short = _short_result(result) if result not in (None, "") else ""
    if not said and not tool_name:
        return None
    if not said and tool_name:
        said = tool_name
    now = ts or _iso()
    item: dict[str, Any] = {"ts": now, "role": who, "text": said}
    if tool_name:
        item["tool"] = tool_name
    if short:
        item["result"] = short

    path = talk_log_path(root)
    with _lock:
        data = _read(path)
        turns = list(data.get("turns") or [])
        if turns:
            prev = turns[-1]
            prev_ts = _parse_ts(str(prev.get("ts") or ""))
            now_ts = _parse_ts(now) or time.time()
            if (
                _same_turn(prev, item)
                and prev_ts is not None
                and abs(now_ts - prev_ts) <= DEDUP_WINDOW_SEC
            ):
                return dict(prev)
        if not data.get("started_at"):
            data["started_at"] = now
        turns.append(item)
        data["turns"] = turns[-MAX_TURNS:]
        _write(path, data)
    return dict(item)


def last_conversation(root: Path | None = None) -> dict[str, Any]:
    """Last turns, oldest first / newest last, plus started_at."""
    path = talk_log_path(root)
    with _lock:
        data = _read(path)
    return {
        "started_at": data.get("started_at"),
        "turns": list(data.get("turns") or []),
    }


def _speech_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """You / Jarvis lines only. Already public-safe; keep them short for chat."""
    out: list[dict[str, Any]] = []
    for row in turns:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip().lower()
        if role not in SPEECH_ROLES:
            continue
        text = sanitize_talk_text(row.get("text"), max_chars=ONESHOT_TURN_CHARS)
        if not text:
            continue
        item = {"ts": str(row.get("ts") or ""), "role": role, "text": text}
        out.append(item)
    return out


def _split_sessions(turns: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    prev_ts: float | None = None
    for row in turns:
        ts = _parse_ts(str(row.get("ts") or ""))
        if (
            current
            and prev_ts is not None
            and ts is not None
            and (ts - prev_ts) > SESSION_GAP_SEC
        ):
            groups.append(current)
            current = []
        current.append(row)
        if ts is not None:
            prev_ts = ts
    if current:
        groups.append(current)
    return groups


def recent_talk_turns(
    asked: str | None = None,
    *,
    root: Path | None = None,
    limit: int = ONESHOT_MAX_TURNS,
) -> list[dict[str, Any]]:
    """Same-session You/Jarvis turns; last conversation if this visit is thin.

    Drops the current utterance when the page already posted it to /talk/log.
    """
    cap = max(1, min(int(limit), MAX_TURNS))
    try:
        convo = last_conversation(root=root)
    except Exception:
        return []
    speech = _speech_turns(list(convo.get("turns") or []))
    sessions = _split_sessions(speech)
    if not sessions:
        return []
    current = sessions[-1]
    if len(current) < THIN_SESSION_TURNS and len(sessions) >= 2:
        chosen = sessions[-2] + current
    else:
        chosen = current
    chosen = chosen[-cap:]
    asked_norm = sanitize_talk_text(asked, max_chars=MAX_TEXT) if asked else ""
    if asked_norm and chosen and chosen[-1].get("role") == "you":
        last_text = str(chosen[-1].get("text") or "")
        if last_text.casefold() == asked_norm.casefold():
            chosen = chosen[:-1]
    return chosen


def talk_messages_for_oneshot(
    asked: str | None = None,
    *,
    root: Path | None = None,
) -> list[dict[str, str]]:
    """Chat turns for cheap oneshot. Never includes tool dumps or secrets."""
    messages: list[dict[str, str]] = []
    for row in recent_talk_turns(asked, root=root, limit=ONESHOT_MAX_TURNS):
        role = "user" if row.get("role") == "you" else "assistant"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        messages.append({"role": role, "content": text})
    return messages


def talk_recap_for_session(
    *,
    root: Path | None = None,
    max_chars: int = RECAP_MAX_CHARS,
) -> str:
    """Short last-conversation recap for Realtime instructions. Not a dump."""
    turns = recent_talk_turns(root=root, limit=RECAP_MAX_TURNS)
    if not turns:
        return ""
    lines = [
        "Last conversation (continue as a friend already talking; "
        "do not greet as if new; Really? / what do you think / more on that "
        "stay on THIS thread, not leftover browser text; react, do not repeat "
        "your last lines; Stop just stops; "
        "one or two short sentences, no Wikipedia):"
    ]
    for row in turns:
        who = "You" if row.get("role") == "you" else "Jarvis"
        bit = str(row.get("text") or "").strip()[:RECAP_LINE_CHARS]
        if bit:
            lines.append(f"{who}: {bit}")
    recap = "\n".join(lines).strip()
    cap = max(80, min(int(max_chars), 2000))
    if len(recap) > cap:
        recap = recap[: cap - 1].rstrip() + "…"
    return recap


def has_talk_history(
    asked: str | None = None,
    *,
    root: Path | None = None,
) -> bool:
    return bool(recent_talk_turns(asked, root=root, limit=2))


def persist_ask(user_text: str, payload: dict[str, Any] | None, *, root: Path | None = None) -> None:
    """Record a /ask exchange so a refresh is not required."""
    try:
        asked = str(user_text or "").strip()
        if asked:
            append_turn("you", asked, root=root)
        body = payload if isinstance(payload, dict) else {}
        reply = str(body.get("reply") or "").strip()
        if reply in {"{}", "[]", "null", "None"}:
            reply = ""
        if not reply:
            try:
                from app.jarvis.virtual_pc import goal_is_hire_job
                from app.jarvis.voice_ask import hire_fallback_reply

                if goal_is_hire_job(asked):
                    reply = hire_fallback_reply(asked)
            except Exception:
                reply = ""
        if reply:
            append_turn("jarvis", reply, root=root)
        for name in body.get("tools_used") or []:
            label = str(name or "").strip()
            if not label:
                continue
            append_turn(
                "tool",
                label,
                tool=label,
                result=_short_result(body.get("result")),
                root=root,
            )
    except Exception:
        return


def persist_tool(name: str, result: Any, *, root: Path | None = None) -> None:
    """Record a Realtime /tools/run outcome (model-safe projection only)."""
    try:
        label = str(name or "").strip()
        if not label:
            return
        append_turn("tool", _short_result(result) or label, tool=label, result=result, root=root)
    except Exception:
        return
