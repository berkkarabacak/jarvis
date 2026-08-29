from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


FENCE_RE = re.compile(r"^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$", re.IGNORECASE)


@dataclass
class ParsedJobOutput:
    result: Any
    memory: str
    raw_text: str
    update_memory: bool = True


def strip_code_fences(text: str) -> str:
    text = text.strip()
    m = FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    # Defensive: leading/trailing fences with extra prose noise
    if "```" in text:
        parts = text.split("```")
        # try fenced block contents
        for i, part in enumerate(parts):
            if i % 2 == 1:
                candidate = part.strip()
                if candidate.lower().startswith("json"):
                    candidate = candidate[4:].lstrip()
                if candidate.startswith("{") and candidate.endswith("}"):
                    return candidate
    return text


def parse_job_output(text: str) -> ParsedJobOutput:
    cleaned = strip_code_fences(text or "")
    data = _loads_json(cleaned)
    if data is None:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            data = _loads_json(cleaned[start : end + 1])
    # Fallback: model returned plain prose — keep result, do not wipe memory.
    if not isinstance(data, dict):
        prose = (text or "").strip()
        if prose:
            return ParsedJobOutput(
                result=prose,
                memory="",
                raw_text=text,
                update_memory=False,
            )
        raise ValueError("Model output is not a JSON object")
    if "result" not in data:
        raise ValueError("JSON must contain 'result' key")
    memory = data.get("memory", "")
    if not isinstance(memory, str):
        memory = json.dumps(memory, ensure_ascii=False, indent=2)
    return ParsedJobOutput(
        result=data["result"],
        memory=memory or "",
        raw_text=text,
        update_memory=True,
    )


def _loads_json(s: str) -> Any | None:
    try:
        return json.loads(s)
    except Exception:
        pass
    # Repair common model mistakes: trailing commas, bare newlines in strings
    try:
        repaired = re.sub(r",\s*([}\]])", r"\1", s)
        return json.loads(repaired)
    except Exception:
        return None


SYSTEM_PROMPT = """You are an unattended task agent with durable per-job memory.

You receive: short working memory, an append-only memory log, and summaries of prior runs for THIS job only.

Rules:
1. Respond with a single JSON object ONLY. No prose before/after, no markdown fences.
2. Exact shape:
{"result":"<human-facing deliverable as a string>","memory":"<updated SHORT working memory as markdown string>"}
3. "result" = today's deliverable (string; use \\n for newlines).
4. "memory" = concise durable working state for NEXT run (decisions, open threads, covered items). Not a full dump of prior results (those are already logged).
5. Never put API keys, tokens, passwords, or Authorization headers in result or memory.
6. Use only this job's memory/history. Do not invent other jobs.
7. Escape double quotes inside JSON strings.
"""


COMPACTION_SYSTEM_PROMPT = """You compact an agent memory document.

Rules:
1. Respond with JSON ONLY. No prose, no markdown, no code fences.
2. Exact shape:
{"result": "compacted", "memory": "<compacted memory markdown string>"}
3. Preserve decisions, open threads, commitments, and unresolved questions.
4. Drop resolved detail, duplicates, and stale chatter.
5. Keep the memory useful for future unattended runs.
"""
