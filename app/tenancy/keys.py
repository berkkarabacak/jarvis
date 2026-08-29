"""Org API key helpers — hash-only storage, never log plaintext."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Iterable


KEY_PREFIX_TAG = "ao_"
RAW_TOKEN_BYTES = 32


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_once, key_prefix, key_hash).

    Plaintext is returned only to the caller at creation time.
    """
    token = secrets.token_urlsafe(RAW_TOKEN_BYTES)
    plaintext = f"{KEY_PREFIX_TAG}{token}"
    prefix = plaintext[:10]
    return plaintext, prefix, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    """SHA-256 hex digest of the full key. Never store plaintext."""
    raw = (plaintext or "").strip().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_api_key(plaintext: str, key_hash: str) -> bool:
    expected = hash_api_key(plaintext)
    return hmac.compare_digest(expected, (key_hash or "").strip())


def sanitize_scopes(scopes: Iterable[str] | None) -> list[str]:
    allowed = {
        "mission.read",
        "mission.run",
        "audit.read",
        "keys.manage",
        "org.manage",
        "members.manage",
        "budget.manage",
    }
    out: list[str] = []
    for s in scopes or ("mission.read",):
        v = (s or "").strip().lower()
        if v in allowed and v not in out:
            out.append(v)
    return out or ["mission.read"]


def redact_key_for_log(plaintext: str | None) -> str:
    """Safe log fragment — prefix only."""
    p = (plaintext or "").strip()
    if len(p) < 8:
        return "***"
    return p[:6] + "…" + ("*" * 6)
