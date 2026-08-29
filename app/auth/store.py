from __future__ import annotations

import time
from dataclasses import dataclass

from app.crypto import TokenCipher
from app.db import Database


@dataclass
class StoredTokens:
    access_token: str
    refresh_token: str
    expires_at: float
    token_endpoint: str
    redirect_uri: str
    token_type: str
    needs_reauth: bool
    provider_type: str
    updated_at: float
    last_refresh_at: float | None
    last_error: str | None


class AuthTokenStore:
    def __init__(self, db: Database, cipher: TokenCipher) -> None:
        self.db = db
        self.cipher = cipher

    async def load(self) -> StoredTokens | None:
        conn = self.db.conn
        cur = await conn.execute("SELECT * FROM auth_tokens WHERE id = 1")
        row = await cur.fetchone()
        if row is None:
            return None
        return StoredTokens(
            access_token=self.cipher.decrypt(row["access_token_enc"]),
            refresh_token=self.cipher.decrypt(row["refresh_token_enc"]),
            expires_at=float(row["expires_at"] or 0),
            token_endpoint=row["token_endpoint"] or "",
            redirect_uri=row["redirect_uri"] or "",
            token_type=row["token_type"] or "Bearer",
            needs_reauth=bool(row["needs_reauth"]),
            provider_type=row["provider_type"] or "oauth",
            updated_at=float(row["updated_at"] or 0),
            last_refresh_at=float(row["last_refresh_at"]) if row["last_refresh_at"] is not None else None,
            last_error=row["last_error"],
        )

    async def save(
        self,
        *,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        token_endpoint: str,
        redirect_uri: str,
        token_type: str = "Bearer",
        needs_reauth: bool = False,
        provider_type: str = "oauth",
        last_refresh_at: float | None = None,
        last_error: str | None = None,
    ) -> StoredTokens:
        now = time.time()
        conn = self.db.conn
        await conn.execute(
            """
            INSERT INTO auth_tokens (
                id, access_token_enc, refresh_token_enc, expires_at, token_endpoint,
                redirect_uri, token_type, needs_reauth, provider_type, updated_at,
                last_refresh_at, last_error
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                access_token_enc=excluded.access_token_enc,
                refresh_token_enc=excluded.refresh_token_enc,
                expires_at=excluded.expires_at,
                token_endpoint=excluded.token_endpoint,
                redirect_uri=excluded.redirect_uri,
                token_type=excluded.token_type,
                needs_reauth=excluded.needs_reauth,
                provider_type=excluded.provider_type,
                updated_at=excluded.updated_at,
                last_refresh_at=excluded.last_refresh_at,
                last_error=excluded.last_error
            """,
            (
                self.cipher.encrypt(access_token),
                self.cipher.encrypt(refresh_token),
                expires_at,
                token_endpoint,
                redirect_uri,
                token_type,
                1 if needs_reauth else 0,
                provider_type,
                now,
                last_refresh_at,
                last_error,
            ),
        )
        await conn.commit()
        loaded = await self.load()
        assert loaded is not None
        return loaded

    async def mark_needs_reauth(self, error: str) -> None:
        conn = self.db.conn
        now = time.time()
        cur = await conn.execute("SELECT id FROM auth_tokens WHERE id = 1")
        row = await cur.fetchone()
        if row is None:
            await conn.execute(
                """
                INSERT INTO auth_tokens (id, needs_reauth, last_error, updated_at, provider_type)
                VALUES (1, 1, ?, ?, 'oauth')
                """,
                (error[:2000], now),
            )
        else:
            await conn.execute(
                """
                UPDATE auth_tokens
                SET needs_reauth = 1, last_error = ?, updated_at = ?
                WHERE id = 1
                """,
                (error[:2000], now),
            )
        await conn.commit()

    async def save_pending(
        self,
        *,
        state: str,
        code_verifier: str,
        code_challenge: str,
        redirect_uri: str,
        nonce: str,
    ) -> None:
        conn = self.db.conn
        await conn.execute(
            """
            INSERT OR REPLACE INTO oauth_pending
            (state, code_verifier, code_challenge, redirect_uri, nonce, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (state, code_verifier, code_challenge, redirect_uri, nonce, time.time()),
        )
        await conn.commit()

    async def pop_pending(self, state: str) -> dict | None:
        conn = self.db.conn
        cur = await conn.execute("SELECT * FROM oauth_pending WHERE state = ?", (state,))
        row = await cur.fetchone()
        if row is None:
            return None
        await conn.execute("DELETE FROM oauth_pending WHERE state = ?", (state,))
        await conn.commit()
        return dict(row)
