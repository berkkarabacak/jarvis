from __future__ import annotations

import re

# Redact secrets so memory never retains credentials.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|api[_-]?secret|access[_-]?token|refresh[_-]?token|bearer|password|passwd|secret|authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"\bATATT[A-Za-z0-9_\-=]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\b"),
    re.compile(r"(?i)x-api-key\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(token|password)\s*[:=]\s*\S+"),
]


def sanitize_text(text: str | None, *, max_chars: int | None = None) -> str:
    s = text or ""
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    s = s.replace("\x00", "")
    if max_chars is not None and len(s) > max_chars:
        s = s[: max_chars - 20].rstrip() + "\n…[truncated]"
    return s


def summarize_for_log(result: str | None, *, max_chars: int = 1200) -> str:
    """Bounded one-entry summary derived from a run result (source of truth)."""
    s = sanitize_text(result, max_chars=max_chars * 2)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return "(empty result)"
    # Prefer headings + first bullets
    keep: list[str] = []
    for ln in lines:
        if ln.startswith("#") or ln.startswith("-") or ln.startswith("*") or ln[:2].isdigit():
            keep.append(ln)
        elif not keep:
            keep.append(ln)
        if sum(len(x) + 1 for x in keep) >= max_chars:
            break
    if not keep:
        keep = lines[:12]
    out = "\n".join(keep)
    return sanitize_text(out, max_chars=max_chars)
