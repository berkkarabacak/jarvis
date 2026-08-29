from __future__ import annotations

import logging

import pytest

from app.crypto import TokenCipher


def test_roundtrip_with_dedicated_key():
    cipher = TokenCipher("k" * 44, "fallback-unused")
    token = cipher.encrypt("secret-value")
    assert cipher.decrypt(token) == "secret-value"


def test_fallback_secret_used_when_no_key():
    cipher = TokenCipher("", "some-api-secret")
    assert cipher.decrypt(cipher.encrypt("x")) == "x"


def test_refuses_wellknown_constant_when_both_empty():
    with pytest.raises(ValueError, match="well-known key"):
        TokenCipher("", "")


def test_warns_on_fallback(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_orchestrator.crypto"):
        TokenCipher("", "some-api-secret")
    assert any("TOKEN_ENCRYPTION_KEY is empty" in r.message for r in caplog.records)
