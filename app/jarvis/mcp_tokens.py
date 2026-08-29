"""Encrypted bearer/OAuth tokens for MCP servers (ORCH-323).

Uses the same ``TOKEN_ENCRYPTION_KEY`` / ``TokenCipher`` path as auth tokens.
Plaintext must never leave this module via settings/API responses or logs.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.crypto import TokenCipher

log = logging.getLogger("jarvis.mcp.tokens")


@lru_cache(maxsize=1)
def _cipher() -> TokenCipher:
    key = (os.environ.get("TOKEN_ENCRYPTION_KEY") or "").strip()
    fallback = (os.environ.get("API_SECRET") or "dev-insecure-key").strip()
    return TokenCipher(key, fallback)


def reset_cipher_cache() -> None:
    """Test helper — rebuild cipher after env changes."""
    _cipher.cache_clear()


def encrypt_token(plaintext: str | None) -> str:
    """Return ciphertext for storage. Empty input → empty string."""
    if plaintext is None or plaintext == "":
        return ""
    return _cipher().encrypt(plaintext)


def decrypt_token(ciphertext: str | None) -> str:
    """Decrypt a stored token. Never log the result."""
    if not ciphertext:
        return ""
    try:
        return _cipher().decrypt(ciphertext)
    except ValueError:
        log.warning("mcp token decrypt failed (bad TOKEN_ENCRYPTION_KEY?)")
        return ""


def has_token(ciphertext: str | None) -> bool:
    return bool(ciphertext and str(ciphertext).strip())
