from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("agent_orchestrator.crypto")


def _derive_fernet(key_material: str) -> Fernet:
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class TokenCipher:
    """Encrypts token fields at rest.

    A missing encryption key falls back to deriving from ``fallback_secret``;
    when that is also missing, construction fails rather than silently
    encrypting with a publicly-known constant (issue #146).
    """

    def __init__(self, encryption_key: str, fallback_secret: str) -> None:
        material = (encryption_key or "").strip()
        if material:
            try:
                self._fernet = Fernet(material.encode("utf-8"))
            except (ValueError, TypeError):
                self._fernet = _derive_fernet(material)
            return
        fallback = (fallback_secret or "").strip()
        if not fallback:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is empty and no fallback secret was provided; "
                "refusing to encrypt tokens with a well-known key "
                "(generate: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\")"
            )
        log.warning(
            "TOKEN_ENCRYPTION_KEY is empty; deriving the token cipher from API_SECRET. "
            "Set a dedicated TOKEN_ENCRYPTION_KEY."
        )
        self._fernet = _derive_fernet(fallback)

    def encrypt(self, plaintext: str | None) -> str:
        if plaintext is None:
            plaintext = ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str | None) -> str:
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt token field; check TOKEN_ENCRYPTION_KEY") from exc
