from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.auth.constants import (
    XAI_OAUTH_AUTHORIZE_URL,
    XAI_OAUTH_CLIENT_ID,
    XAI_OAUTH_DISCOVERY_URL,
    XAI_OAUTH_PLAN,
    XAI_OAUTH_REFERRER,
    XAI_OAUTH_SCOPE,
    XAI_OAUTH_TOKEN_URL_FALLBACK,
)


@dataclass
class PkcePair:
    verifier: str
    challenge: str


@dataclass
class XaiDiscovery:
    authorization_endpoint: str
    token_endpoint: str


@dataclass
class TokenPayload:
    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"
    id_token: str | None = None


def generate_pkce() -> PkcePair:
    # Source: opencode-grok-auth src/oauth.ts generatePkce — 48 random bytes base64url
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkcePair(verifier=verifier, challenge=challenge)


def create_oauth_state() -> str:
    return secrets.token_hex(24)


def create_oauth_nonce() -> str:
    return secrets.token_hex(24)


def validate_xai_oauth_endpoint(url: str, field: str = "endpoint") -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"xAI OAuth {field} must be HTTPS: {url}")
    host = (parsed.hostname or "").lower()
    if host != "x.ai" and not host.endswith(".x.ai"):
        raise ValueError(f"xAI OAuth {field} host {host} is not on xAI origin")
    return url


async def discover_xai_oauth(client: httpx.AsyncClient | None = None) -> XaiDiscovery:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(
            XAI_OAUTH_DISCOVERY_URL,
            headers={"Accept": "application/json"},
        )
        if not resp.is_success:
            return XaiDiscovery(
                authorization_endpoint=XAI_OAUTH_AUTHORIZE_URL,
                token_endpoint=XAI_OAUTH_TOKEN_URL_FALLBACK,
            )
        payload = resp.json()
        auth_ep = str(payload.get("authorization_endpoint") or "").strip()
        token_ep = str(payload.get("token_endpoint") or "").strip()
        if not auth_ep or not token_ep:
            raise ValueError("OIDC discovery missing endpoints")
        return XaiDiscovery(
            authorization_endpoint=validate_xai_oauth_endpoint(auth_ep, "authorization_endpoint"),
            token_endpoint=validate_xai_oauth_endpoint(token_ep, "token_endpoint"),
        )
    except Exception:
        return XaiDiscovery(
            authorization_endpoint=XAI_OAUTH_AUTHORIZE_URL,
            token_endpoint=XAI_OAUTH_TOKEN_URL_FALLBACK,
        )
    finally:
        if owns:
            await client.aclose()


def build_authorize_url(
    *,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    nonce: str,
) -> str:
    # Source: opencode-grok-auth src/oauth.ts — hardcode authorize URL + hermes referrer
    params = {
        "response_type": "code",
        "client_id": XAI_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": XAI_OAUTH_SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "plan": XAI_OAUTH_PLAN,
        "referrer": XAI_OAUTH_REFERRER,
    }
    return f"{XAI_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def _jwt_exp_ms(access_token: str) -> float | None:
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(parts[1] + pad)
        import json

        payload = json.loads(raw.decode("utf-8"))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp) * 1000.0
    except Exception:
        return None
    return None


def calculate_token_expiry(started_at_ms: float, expires_in: object, access_token: str) -> float:
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return (started_at_ms + float(expires_in) * 1000.0) / 1000.0
    jwt_ms = _jwt_exp_ms(access_token)
    if jwt_ms:
        return jwt_ms / 1000.0
    return (started_at_ms / 1000.0) + 3600.0


async def parse_token_response(
    response: httpx.Response,
    started_at_ms: float,
    error_prefix: str,
    fallback_refresh: str = "",
) -> TokenPayload:
    text = response.text
    if not response.is_success:
        raise RuntimeError(f"{error_prefix} (HTTP {response.status_code}). {text[:500]}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"{error_prefix}: response was not valid JSON") from exc

    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or fallback_refresh).strip()
    if not access:
        raise RuntimeError(f"{error_prefix}: missing access_token")
    if not refresh:
        raise RuntimeError(f"{error_prefix}: missing refresh_token")

    return TokenPayload(
        access_token=access,
        refresh_token=refresh,
        expires_at=calculate_token_expiry(started_at_ms, payload.get("expires_in"), access),
        token_type=str(payload.get("token_type") or "Bearer").strip() or "Bearer",
        id_token=str(payload.get("id_token") or "").strip() or None,
    )


async def exchange_code_for_tokens(
    *,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    code_challenge: str,
    client: httpx.AsyncClient | None = None,
) -> TokenPayload:
    """Hermes-compatible exchange: includes code_verifier AND code_challenge.

    Source: opencode-grok-auth src/oauth.ts exchangeXaiCodeForTokens
    """
    if not code_verifier:
        raise ValueError("PKCE code verifier is empty")
    token_endpoint = validate_xai_oauth_endpoint(token_endpoint, "token_endpoint")
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    started = time.time() * 1000.0
    try:
        resp = await client.post(
            token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": XAI_OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        return await parse_token_response(resp, started, "xAI token exchange failed")
    finally:
        if owns:
            await client.aclose()


async def refresh_tokens(
    *,
    token_endpoint: str,
    refresh_token: str,
    client: httpx.AsyncClient | None = None,
) -> TokenPayload:
    if not refresh_token:
        raise ValueError("refresh token is empty")
    token_endpoint = validate_xai_oauth_endpoint(token_endpoint, "token_endpoint")
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    started = time.time() * 1000.0
    try:
        resp = await client.post(
            token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "refresh_token",
                "client_id": XAI_OAUTH_CLIENT_ID,
                "refresh_token": refresh_token,
            },
        )
        return await parse_token_response(
            resp, started, "xAI token refresh failed", fallback_refresh=refresh_token
        )
    finally:
        if owns:
            await client.aclose()


def is_terminal_auth_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    markers = (
        "invalid_grant",
        "http 400",
        "http 401",
        "http 403",
        "revoked",
        "expired",
        "unauthorized",
    )
    return any(m in msg for m in markers)
