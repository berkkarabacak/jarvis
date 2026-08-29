from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.auth.constants import ACCESS_TOKEN_REFRESH_SKEW_SECONDS, XAI_OAUTH_TOKEN_URL_FALLBACK
from app.auth.oauth import is_terminal_auth_error, refresh_tokens
from app.auth.store import AuthTokenStore
from app.config import Settings


@dataclass
class AuthStatus:
    healthy: bool
    needs_reauth: bool
    provider_type: str
    expires_at: float | None
    last_refresh_at: float | None
    last_error: str | None
    has_tokens: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "needs_reauth": self.needs_reauth,
            "provider_type": self.provider_type,
            "expires_at": self.expires_at,
            "last_refresh_at": self.last_refresh_at,
            "last_error": self.last_error,
            "has_tokens": self.has_tokens,
        }


class TokenProvider(ABC):
    @abstractmethod
    async def get_access_token(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def status(self) -> AuthStatus:
        raise NotImplementedError


class ApiKeyTokenProvider(TokenProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = (api_key or "").strip()

    async def get_access_token(self) -> str:
        if not self._api_key:
            raise RuntimeError("XAI_API_KEY is not configured")
        return self._api_key

    async def status(self) -> AuthStatus:
        ok = bool(self._api_key)
        return AuthStatus(
            healthy=ok,
            needs_reauth=not ok,
            provider_type="api_key",
            expires_at=None,
            last_refresh_at=None,
            last_error=None if ok else "XAI_API_KEY missing",
            has_tokens=ok,
        )


class OAuthTokenProvider(TokenProvider):
    def __init__(self, store: AuthTokenStore) -> None:
        self.store = store
        self._lock = asyncio.Lock()

    async def status(self) -> AuthStatus:
        tok = await self.store.load()
        if tok is None:
            return AuthStatus(
                healthy=False,
                needs_reauth=True,
                provider_type="oauth",
                expires_at=None,
                last_refresh_at=None,
                last_error="No OAuth tokens stored — run local login and /oauth/import",
                has_tokens=False,
            )
        healthy = bool(tok.refresh_token) and not tok.needs_reauth
        return AuthStatus(
            healthy=healthy,
            needs_reauth=tok.needs_reauth or not tok.refresh_token,
            provider_type="oauth",
            expires_at=tok.expires_at or None,
            last_refresh_at=tok.last_refresh_at,
            last_error=tok.last_error,
            has_tokens=bool(tok.access_token or tok.refresh_token),
        )

    async def get_access_token(self) -> str:
        async with self._lock:
            conn = self.store.db.conn
            await conn.execute("BEGIN IMMEDIATE")
            try:
                tok = await self.store.load()
                if tok is None or not tok.refresh_token:
                    raise RuntimeError("No OAuth tokens — needs reauth")
                if tok.needs_reauth:
                    raise RuntimeError(f"OAuth needs reauth: {tok.last_error or 'invalid_grant'}")

                now = time.time()
                if tok.access_token and (tok.expires_at - now) >= ACCESS_TOKEN_REFRESH_SKEW_SECONDS:
                    await conn.execute("COMMIT")
                    return tok.access_token

                endpoint = tok.token_endpoint or XAI_OAUTH_TOKEN_URL_FALLBACK
                try:
                    fresh = await refresh_tokens(
                        token_endpoint=endpoint,
                        refresh_token=tok.refresh_token,
                    )
                except Exception as exc:
                    if is_terminal_auth_error(exc):
                        await conn.execute(
                            """
                            UPDATE auth_tokens
                            SET needs_reauth = 1, last_error = ?, updated_at = ?
                            WHERE id = 1
                            """,
                            (str(exc)[:2000], time.time()),
                        )
                        await conn.execute("COMMIT")
                        raise RuntimeError(f"OAuth refresh failed terminally: {exc}") from exc
                    await conn.execute("ROLLBACK")
                    raise

                # Persist BEFORE return (including rotated refresh_token).
                now = time.time()
                await conn.execute(
                    """
                    UPDATE auth_tokens SET
                        access_token_enc = ?,
                        refresh_token_enc = ?,
                        expires_at = ?,
                        token_endpoint = ?,
                        token_type = ?,
                        needs_reauth = 0,
                        last_refresh_at = ?,
                        last_error = NULL,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (
                        self.store.cipher.encrypt(fresh.access_token),
                        self.store.cipher.encrypt(fresh.refresh_token),
                        fresh.expires_at,
                        endpoint,
                        fresh.token_type,
                        now,
                        now,
                    ),
                )
                await conn.execute("COMMIT")
                return fresh.access_token
            except Exception:
                try:
                    await conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise


def build_token_provider(settings: Settings, store: AuthTokenStore) -> TokenProvider:
    kind = (settings.token_provider or "oauth").strip().lower()
    if kind == "api_key":
        return ApiKeyTokenProvider(settings.xai_api_key)
    return OAuthTokenProvider(store)
