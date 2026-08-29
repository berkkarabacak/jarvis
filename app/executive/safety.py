from __future__ import annotations

import re
from typing import Any


class ExecutiveSafetyError(ValueError):
    """Raised when data cannot cross the executive/public boundary safely."""


_REASONING_MARKERS = re.compile(
    r"(?i)(chain[ _-]?of[ _-]?thought|private[ _-]?reasoning|scratchpad|"
    r"<thinking>|browser[ _-]?session|session[ _-]?cookie|document\.cookie|"
    r"localstorage|sessionstorage|begin[ _-]?private[ _-]?key)"
)
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{8,}"),
    re.compile(
        r"(?i)\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION)"
        r"\s*=\s*[^\s,;\"}\]]+"
    ),
    re.compile(
        r"(?i)\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"password|secret|cookie|session)\s*[:=]\s*[^\s,;\"}\]]+"
    ),
    re.compile(r"\b(?:sk-|xai-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"),
    re.compile(r"(?i)https?://[^\s/@:\"]+:[^\s/@\"]+@[^\s\"}\]]+"),
    re.compile(r"(?i)https?://[^\s?#\"]+[?#][^\s\"}\]]+"),
)
_FORBIDDEN_KEY_PARTS = (
    "reasoning",
    "chainofthought",
    "scratchpad",
    "credential",
    "token",
    "apikey",
    "password",
    "secret",
    "authorization",
    "cookie",
    "sessionfile",
    "browser",
    "rawresponse",
    "prompt",
    "privatememory",
)


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def sanitize_private_input(value: Any, *, maximum: int = 16_000) -> str:
    """Bound/redact CEO input before it reaches an external process."""

    if not isinstance(value, str):
        raise ExecutiveSafetyError("Executive message must be text")
    text = value.replace("\x00", "").strip()
    if not text:
        raise ExecutiveSafetyError("Executive message is required")
    if len(text) > maximum:
        raise ExecutiveSafetyError("Executive message exceeds its size limit")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def sanitize_public_text(
    value: Any,
    *,
    maximum: int = 1_000,
    withheld_text: str = "Executive response withheld by safety policy",
) -> tuple[str, bool]:
    """Return public text and whether any content was redacted/withheld."""

    if not isinstance(value, str):
        return withheld_text, True
    text = value.replace("\x00", "").strip()
    if not text or _REASONING_MARKERS.search(text):
        return withheld_text, True
    changed = False
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[redacted]", text)
        changed = changed or scrubbed != text
        text = scrubbed
    if len(text) > maximum:
        text = text[: maximum - 16].rstrip() + " …[truncated]"
        changed = True
    return text, changed


def require_public_identifier(value: Any) -> str:
    """Validate an identifier against the ORCH-70 V1 public contract."""

    text, filtered = sanitize_public_text(value, maximum=128, withheld_text="")
    if filtered or not _PUBLIC_IDENTIFIER.fullmatch(text):
        raise ExecutiveSafetyError("Executive mission identifier is not publishable")
    return text


def sanitize_public_metadata(value: Any, *, _depth: int = 0) -> Any:
    """Fail closed for metadata that might otherwise expose adapter internals."""

    if _depth > 4:
        return "[withheld]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in list(value.items())[:40]:
            if any(part in _normalized_key(key) for part in _FORBIDDEN_KEY_PARTS):
                continue
            out[str(key)[:64]] = sanitize_public_metadata(child, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [
            sanitize_public_metadata(item, _depth=_depth + 1) for item in value[:40]
        ]
    if isinstance(value, str):
        return sanitize_public_text(value, maximum=500, withheld_text="[withheld]")[0]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "[withheld]"
