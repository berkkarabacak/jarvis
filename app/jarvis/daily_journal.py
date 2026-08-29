"""Day-by-day Jarvis memory digests (ORCH-329).

Lightweight rolling journals stored as tagged facts (day:YYYY-MM-DD + daily-journal).
Not full transcripts — topics, decisions, artifacts, open threads only.
Day boundaries use JARVIS_MEMORY_TZ (default Europe/Berlin).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.memory.sanitize import sanitize_text

DEFAULT_TZ = "Europe/Berlin"
DAY_TAG_PREFIX = "day:"
JOURNAL_TAG = "daily-journal"
AUTO_DECISION_TAG = "auto-decision"
AGENTS_CREATED_KEY = "agents_created"
_AGENTS_CREATED_LABEL = "Agents created:"

_TRIVIAL_TOKENS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank",
        "you",
        "thx",
        "ok",
        "okay",
        "yes",
        "no",
        "yep",
        "nope",
        "sure",
        "cool",
        "great",
        "bye",
        "good",
        "morning",
        "evening",
        "night",
        "jarvis",
        "please",
    }
)

_DECISION_RE = re.compile(
    r"(?i)\b("
    r"decided\s+to|we'?ll\s+use|we\s+will\s+use|use\s+\w+\s+for|"
    r"from\s+now\s+on|going\s+with|chose\s+to|decision\s*:|"
    r"let'?s\s+use|switching\s+to"
    r")\b"
)

_ARTIFACT_RE = re.compile(
    r"(?i)("
    r"(?:Exports|Documents|Desktop|Downloads)/[\w./\\-]+\.\w+"
    r"|[\w.-]+\.(?:py|md|tsx?|jsx?|xlsx|csv|json|yml|yaml|txt|html)"
    r"|https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+"
    r"|PR\s*#?\d+"
    r"|ORCH-\d+"
    r")"
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")

_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "have",
        "what",
        "when",
        "where",
        "which",
        "about",
        "your",
        "you",
        "are",
        "was",
        "were",
        "been",
        "being",
        "will",
        "would",
        "could",
        "should",
        "just",
        "like",
        "into",
        "then",
        "than",
        "them",
        "they",
        "their",
        "there",
        "here",
        "also",
        "some",
        "any",
        "all",
        "can",
        "not",
        "but",
        "our",
        "out",
        "how",
        "did",
        "does",
        "doing",
        "please",
        "thanks",
        "jarvis",
        "okay",
        "yes",
        "no",
        "store",
        "token",
    }
)

_NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def memory_tz(tz_name: str | None = None) -> Any:
    name = (tz_name or os.environ.get("JARVIS_MEMORY_TZ") or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        try:
            return ZoneInfo(DEFAULT_TZ)
        except Exception:
            return timezone(timedelta(hours=2))


def day_key(dt: datetime | None = None, tz_name: str | None = None) -> str:
    """Return day:YYYY-MM-DD for dt (UTC-aware or naive-as-UTC) in app TZ."""
    tz = memory_tz(tz_name)
    when = dt if dt is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(tz)
    return f"{DAY_TAG_PREFIX}{local.strftime('%Y-%m-%d')}"


def day_bounds(day_key_str: str, tz_name: str | None = None) -> tuple[float, float]:
    """UTC epoch [start, end) for a day:YYYY-MM-DD (or bare ISO) key."""
    raw = (day_key_str or "").strip()
    if raw.lower().startswith(DAY_TAG_PREFIX):
        raw = raw[len(DAY_TAG_PREFIX) :]
    tz = memory_tz(tz_name)
    local_start = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(timezone.utc).timestamp(),
        local_end.astimezone(timezone.utc).timestamp(),
    )


def redact_for_journal(text: str) -> str:
    return sanitize_text(text or "", max_chars=2000)


def is_trivial_session(turns: list[dict[str, Any]] | None) -> bool:
    """True when the session is only greetings / very short acknowledgements."""
    if not turns:
        return True
    chunks: list[str] = []
    for t in turns:
        content = str(t.get("content") or "").strip()
        if content:
            chunks.append(content)
    if not chunks:
        return True
    joined = " ".join(chunks)
    if len(joined) > 120:
        return False
    cleaned = re.sub(r"[^\w\s]", " ", joined.lower())
    tokens = [tok for tok in cleaned.split() if tok]
    if not tokens:
        return True
    if any(len(tok) > 12 for tok in tokens):
        return False
    return all(tok in _TRIVIAL_TOKENS for tok in tokens)


def digest_turns(
    turns: list[dict[str, Any]] | None,
    source: str | None = None,
) -> dict[str, Any]:
    """Lightweight heuristic digest — no full transcript dump."""
    topics: list[str] = []
    decisions: list[str] = []
    artifacts: list[str] = []
    open_threads: list[str] = []
    notes: list[str] = []
    sources: list[str] = []
    topic_counts: dict[str, int] = {}

    if source and source not in sources:
        sources.append(source)

    for t in turns or []:
        role = str(t.get("role") or "")
        raw = redact_for_journal(str(t.get("content") or ""))
        if not raw.strip():
            continue
        src = str(t.get("source") or "").strip()
        if src and src not in sources:
            sources.append(src)

        if "[REDACTED]" in raw:
            note = re.sub(r"\s+", " ", raw).strip()
            if len(note) > 160:
                note = note[:157] + "..."
            if note and note not in notes:
                notes.append(note)

        for m in _ARTIFACT_RE.finditer(raw):
            art = m.group(0).strip()
            if art and art not in artifacts:
                artifacts.append(art)
            if len(artifacts) >= 8:
                break

        if _DECISION_RE.search(raw):
            snippet = re.sub(r"\s+", " ", raw).strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            if snippet and snippet not in decisions:
                decisions.append(snippet)

        if role == "user" and "?" in raw:
            q = re.sub(r"\s+", " ", raw).strip()
            if len(q) > 20 and not is_trivial_session([{"content": q}]):
                if len(q) > 140:
                    q = q[:137] + "..."
                if q not in open_threads:
                    open_threads.append(q)

        if role in {"user", "assistant", ""}:
            for w in _WORD_RE.findall(raw.lower()):
                if w in _STOP or w in _TRIVIAL_TOKENS:
                    continue
                if w == "redacted":
                    continue
                topic_counts[w] = topic_counts.get(w, 0) + 1

    ranked = sorted(topic_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for word, _n in ranked[:8]:
        topics.append(word)

    return {
        "topics": topics[:8],
        "decisions": decisions[:6],
        "artifacts": artifacts[:8],
        "open_threads": open_threads[:6],
        "notes": notes[:4],
        "sources": sources[:6],
        AGENTS_CREATED_KEY: 0,
    }


def format_digest_fact(day_key_str: str, digest: dict[str, Any]) -> str:
    label = (
        day_key_str
        if str(day_key_str).startswith(DAY_TAG_PREFIX)
        else f"{DAY_TAG_PREFIX}{day_key_str}"
    )
    date_part = label[len(DAY_TAG_PREFIX) :]
    lines = [f"Daily journal {date_part}"]
    # Always persist the integer, including 0. Do not omit the field.
    lines.append(f"{_AGENTS_CREATED_LABEL} {agents_created_int(digest)}")

    def _sec(title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append(f"{title}:")
        for it in items:
            lines.append(f"- {it}")

    _sec("Topics", list(digest.get("topics") or []))
    _sec("Decisions", list(digest.get("decisions") or []))
    _sec("Artifacts", list(digest.get("artifacts") or []))
    _sec("Open threads", list(digest.get("open_threads") or []))
    _sec("Notes", list(digest.get("notes") or []))
    srcs = list(digest.get("sources") or [])
    if srcs:
        lines.append("Sources: " + ", ".join(srcs))
    if len(lines) == 1:
        lines.append("Topics:")
        lines.append("- (light activity)")
    return "\n".join(lines)


def format_journal_fact(day_key_str: str, digest: dict[str, Any]) -> str:
    """Alias used by tests / callers."""
    return format_digest_fact(day_key_str, digest)


def _merge_unique(base: list[str], extra: list[str], *, limit: int) -> list[str]:
    out: list[str] = []
    for item in list(base or []) + list(extra or []):
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def agents_created_int(digest: dict[str, Any] | None) -> int:
    """Non-negative spawn count from a digest. Missing / junk → 0."""
    if not digest:
        return 0
    raw = digest.get(AGENTS_CREATED_KEY, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def merge_digests(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    a = a or {}
    b = b or {}
    return {
        "topics": _merge_unique(a.get("topics") or [], b.get("topics") or [], limit=8),
        "decisions": _merge_unique(a.get("decisions") or [], b.get("decisions") or [], limit=6),
        "artifacts": _merge_unique(a.get("artifacts") or [], b.get("artifacts") or [], limit=8),
        "open_threads": _merge_unique(
            a.get("open_threads") or [], b.get("open_threads") or [], limit=6
        ),
        "notes": _merge_unique(a.get("notes") or [], b.get("notes") or [], limit=4),
        "sources": _merge_unique(a.get("sources") or [], b.get("sources") or [], limit=6),
        # Session merges send 0; keep the running spawn total.
        AGENTS_CREATED_KEY: max(agents_created_int(a), agents_created_int(b)),
    }


def upsert_day_journal(
    memory: Any,
    day_key_str: str,
    digest: dict[str, Any],
    *,
    source: str = "voice",
) -> str | None:
    """Store/update a day journal fact. Returns fact id or None if empty digest."""
    if not digest:
        return None
    has_signal = any(
        digest.get(k)
        for k in ("topics", "decisions", "artifacts", "open_threads", "notes")
    ) or agents_created_int(digest) > 0
    if not has_signal:
        return None
    dk = (
        day_key_str
        if str(day_key_str).startswith(DAY_TAG_PREFIX)
        else f"{DAY_TAG_PREFIX}{day_key_str}"
    )
    existing = None
    try:
        existing = memory.find_fact_by_tag(dk)
    except Exception:
        existing = None
    if existing and JOURNAL_TAG in str(existing.get("tags") or ""):
        prior = _digest_from_fact_text(str(existing.get("fact") or ""))
        digest = merge_digests(prior, digest)
    if source:
        digest = merge_digests(digest, {"sources": [source]})
    text = redact_for_journal(format_digest_fact(dk, digest))
    extra = f"{JOURNAL_TAG},source:{(source or 'voice')[:24]}"
    return memory.upsert_fact_by_tag(
        dk,
        text,
        extra_tags=extra,
        source=source or "voice",
        importance=3,
    )


def _digest_from_fact_text(fact: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "topics": [],
        "decisions": [],
        "artifacts": [],
        "open_threads": [],
        "notes": [],
        "sources": [],
        AGENTS_CREATED_KEY: 0,
    }
    section = None
    mapping = {
        "topics": "topics",
        "decisions": "decisions",
        "artifacts": "artifacts",
        "open threads": "open_threads",
        "notes": "notes",
    }
    for line in (fact or "").splitlines():
        s = line.strip()
        low = s.lower().rstrip(":")
        if low.startswith("agents created"):
            raw = s.split(":", 1)[-1].strip() if ":" in s else ""
            try:
                out[AGENTS_CREATED_KEY] = max(0, int(raw))
            except (TypeError, ValueError):
                out[AGENTS_CREATED_KEY] = 0
            section = None
            continue
        if low in mapping:
            section = mapping[low]
            continue
        if low.startswith("sources:"):
            bits = [b.strip() for b in s.split(":", 1)[-1].split(",") if b.strip()]
            out["sources"] = _merge_unique(out["sources"], bits, limit=6)
            section = None
            continue
        if section and s.startswith("- "):
            item = s[2:].strip()
            if item and item != "(light activity)":
                out[section] = _merge_unique(out[section], [item], limit=8)
    return out


def note_session_activity(
    memory: Any,
    session_id: str,
    *,
    source: str = "voice",
) -> str | None:
    """Rolling digest: merge non-trivial session turns into today's journal."""
    sid = (session_id or "").strip()
    if not sid:
        return None
    turns = memory.recent_turns(sid, limit=40)
    if is_trivial_session(turns):
        return None
    dk = day_key()
    try:
        start, end = day_bounds(dk)
        day_turns = memory.turns_between(start, end, limit=80)
    except Exception:
        day_turns = []
    use_turns = day_turns or turns
    digest = digest_turns(use_turns, source=source)
    return upsert_day_journal(memory, dk, digest, source=source)


def looks_like_day_query(query: str | None) -> bool:
    return resolve_day_key(query) is not None


def parse_relative_day_query(
    query_or_offset: str | int | None, tz_name: str | None = None
) -> str | None:
    """Return day:YYYY-MM-DD if query is a day reference, else None."""
    return resolve_day_key(query_or_offset, tz_name=tz_name)


def resolve_day_key(
    query_or_offset: str | int | None, tz_name: str | None = None
) -> str | None:
    """Parse relative phrases / ISO / day: keys into day:YYYY-MM-DD."""
    if isinstance(query_or_offset, int):
        base = datetime.now(timezone.utc) - timedelta(days=int(query_or_offset))
        return day_key(base, tz_name=tz_name)

    q = str(query_or_offset or "").strip()
    if not q:
        return None
    low = q.lower()

    m = re.search(r"\bday:(\d{4}-\d{2}-\d{2})\b", low)
    if m:
        return f"{DAY_TAG_PREFIX}{m.group(1)}"

    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", low)
    if m:
        return f"{DAY_TAG_PREFIX}{m.group(1)}"

    if low == "today" or low.startswith("today ") or "today?" in low:
        return day_key(tz_name=tz_name)

    if "yesterday" in low or re.search(r"\bd[uü]n\b", q, re.I):
        return day_key(datetime.now(timezone.utc) - timedelta(days=1), tz_name=tz_name)

    m = re.search(r"\b(\d+)\s+days?\s+ago\b", low)
    if m:
        n = int(m.group(1))
        return day_key(datetime.now(timezone.utc) - timedelta(days=n), tz_name=tz_name)

    m = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+days?\s+ago\b",
        low,
    )
    if m:
        n = _NUM_WORDS.get(m.group(1), 0)
        return day_key(datetime.now(timezone.utc) - timedelta(days=n), tz_name=tz_name)

    if "what did we talk" in low:
        return day_key(datetime.now(timezone.utc) - timedelta(days=1), tz_name=tz_name)

    return None


def recall_day(memory: Any, query_or_offset: str | int | None) -> dict[str, Any]:
    """Return day journal fact for a relative/ISO query, or an honest empty message."""
    dk = resolve_day_key(query_or_offset)
    if not dk:
        return {
            "ok": False,
            "empty": True,
            "day_key": None,
            "agents_created": None,
            "message": (
                "Could not parse a day from the query. "
                "Try yesterday, 2 days ago, or day:YYYY-MM-DD."
            ),
            "fact": None,
        }
    row = None
    try:
        row = memory.find_fact_by_tag(dk)
    except Exception:
        row = None
    if row and JOURNAL_TAG in str(row.get("tags") or ""):
        count = agents_created_int(_digest_from_fact_text(str(row.get("fact") or "")))
        return {
            "ok": True,
            "empty": False,
            "day_key": dk,
            "id": row.get("id"),
            "fact": row.get("fact"),
            "tags": row.get("tags"),
            "agents_created": count,
            "message": None,
        }
    try:
        hits = memory.search_facts(dk, limit=5)
        for h in hits:
            tags = str(h.get("tags") or "")
            if JOURNAL_TAG in tags and dk in tags:
                count = agents_created_int(
                    _digest_from_fact_text(str(h.get("fact") or ""))
                )
                return {
                    "ok": True,
                    "empty": False,
                    "day_key": dk,
                    "id": h.get("id"),
                    "fact": h.get("fact"),
                    "tags": tags,
                    "agents_created": count,
                    "message": None,
                }
    except Exception:
        pass
    date_part = dk[len(DAY_TAG_PREFIX) :]
    return {
        "ok": True,
        "empty": True,
        "day_key": dk,
        "id": None,
        "fact": None,
        "tags": None,
        "agents_created": None,
        "message": (
            f"No journal for {date_part}. "
            "Only non-trivial sessions are summarized."
        ),
    }


def increment_agents_created(
    memory: Any,
    n: int = 1,
    *,
    source: str = "child-orch",
) -> str | None:
    """Add n to today's journal spawn count. Writes a row if this is the first event."""
    try:
        add = int(n)
    except (TypeError, ValueError):
        return None
    if add <= 0 or memory is None:
        return None
    dk = day_key()
    prior_count = 0
    try:
        existing = memory.find_fact_by_tag(dk)
        if existing and JOURNAL_TAG in str(existing.get("tags") or ""):
            prior_count = agents_created_int(
                _digest_from_fact_text(str(existing.get("fact") or ""))
            )
    except Exception:
        prior_count = 0
    return upsert_day_journal(
        memory,
        dk,
        {AGENTS_CREATED_KEY: prior_count + add},
        source=source or "child-orch",
    )


def parse_last_n_days_query(query: str | None) -> int | None:
    """Return N for a multi-day recap query, else None.

    Does not steal single-day phrases like '2 days ago' or 'yesterday'.
    """
    q = str(query or "").strip()
    if not q:
        return None
    low = q.lower()
    m = re.search(
        r"\b(?:each\s+of\s+the\s+)?(?:last|past)\s+"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+days\b",
        low,
    )
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _NUM_WORDS.get(raw, 0)
        if n > 0:
            return min(n, 31)
    if re.search(
        r"\bhow many (?:agents|sub-?agents|children|helpers)\b",
        low,
    ) and resolve_day_key(q) is None:
        return 6
    return None


def recall_last_n_days(
    memory: Any,
    n: int = 6,
    *,
    tz_name: str | None = None,
) -> dict[str, Any]:
    """Per-day agents_created for stored journal rows in the last N Berlin days.

    Days with a journal and no spawns return 0. Days that were never stored
    are omitted — this does not invent older rows.
    """
    try:
        window = max(1, min(int(n), 31))
    except (TypeError, ValueError):
        window = 6
    days: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for i in range(window):
        dk = day_key(now - timedelta(days=i), tz_name=tz_name)
        row = None
        try:
            row = memory.find_fact_by_tag(dk)
        except Exception:
            row = None
        if not row or JOURNAL_TAG not in str(row.get("tags") or ""):
            continue
        digest = _digest_from_fact_text(str(row.get("fact") or ""))
        days.append(
            {
                "day_key": dk,
                "id": row.get("id"),
                "fact": row.get("fact"),
                "agents_created": agents_created_int(digest),
            }
        )
    oldest = days[-1]["day_key"] if days else None
    oldest_date = oldest[len(DAY_TAG_PREFIX) :] if oldest else None
    if days:
        message = (
            f"Stored days only ({len(days)} of last {window}). "
            + (
                f"Not stored before {oldest_date}."
                if oldest_date
                else "Older days were never journaled."
            )
        )
    else:
        message = (
            f"No daily journals stored in the last {window} days. "
            "Counts were not recorded for days that have no journal row."
        )
    return {
        "ok": True,
        "n": window,
        "days": days,
        "oldest_stored": oldest,
        "message": message,
    }


def format_last_n_days_recap(recap: dict[str, Any] | None) -> str:
    recap = recap or {}
    lines = [str(recap.get("message") or "Stored days only.")]
    for row in recap.get("days") or []:
        dk = str(row.get("day_key") or "")
        date_part = dk[len(DAY_TAG_PREFIX) :] if dk.startswith(DAY_TAG_PREFIX) else dk
        try:
            count = max(0, int(row.get(AGENTS_CREATED_KEY) or 0))
        except (TypeError, ValueError):
            count = 0
        lines.append(f"- {date_part}: {count} agents created")
    return "\n".join(lines)


def maybe_auto_remember_decision(
    memory: Any,
    text: str,
    *,
    source: str = "agent",
) -> str | None:
    """If text looks like an explicit decision, store a short sanitized fact."""
    raw = (text or "").strip()
    if not raw or not _DECISION_RE.search(raw):
        return None
    snippet = redact_for_journal(re.sub(r"\s+", " ", raw))
    if len(snippet) > 240:
        snippet = snippet[:237] + "..."
    if len(snippet) < 12:
        return None
    fact = f"Decision: {snippet}"
    try:
        return memory.add_fact(
            fact,
            tags=AUTO_DECISION_TAG,
            source=source or "agent",
            importance=2,
        )
    except Exception:
        return None


def journal_source_from_tool_source(tool_source: str | None) -> str:
    ts = (tool_source or "").strip().lower()
    if ts.startswith("bridge"):
        return "bridge"
    if "realtime" in ts:
        return "realtime"
    if "voice" in ts:
        return "voice"
    return "agent"