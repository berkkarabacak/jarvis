from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Request

from app.public_access.errors import BrowserMutationRejected

PUBLIC_SESSION_COOKIE_NAME = "__Host-ao_session"
# Local HTTP (127.0.0.1) cannot use the __Host- prefix (requires Secure over
# real HTTPS). Fall back to a plain name so desktop/loopback CEO works.
PUBLIC_SESSION_COOKIE_NAME_LOCAL = "ao_session"
PUBLIC_MUTATION_HEADER = "X-AI-Control-Room-Request"
PUBLIC_MUTATION_HEADER_VALUE = "browser-v1"
PUBLIC_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
GUEST_BOOTSTRAP_HOURLY_LIMIT = 20
GUEST_BOOTSTRAP_DAILY_LIMIT = 100


def public_session_cookie_name(request: Request | None = None) -> str:
    """Cookie name appropriate for this request's transport."""

    if request is None:
        return PUBLIC_SESSION_COOKIE_NAME
    try:
        host = (request.url.hostname or "").lower()
        scheme = (request.url.scheme or "").lower()
        # Prefer forwarded proto when behind a local reverse proxy.
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        effective = forwarded or scheme
        if effective != "https" and host in {"127.0.0.1", "localhost", "::1"}:
            return PUBLIC_SESSION_COOKIE_NAME_LOCAL
    except Exception:
        pass
    return PUBLIC_SESSION_COOKIE_NAME


def public_session_cookie_secure(request: Request | None = None) -> bool:
    if request is None:
        return True
    try:
        host = (request.url.hostname or "").lower()
        scheme = (request.url.scheme or "").lower()
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        effective = forwarded or scheme
        if effective != "https" and host in {"127.0.0.1", "localhost", "::1"}:
            return False
    except Exception:
        pass
    return True


def read_public_session_token(request: Request) -> str | None:
    """Read session token from either production or local cookie name."""

    for name in (
        public_session_cookie_name(request),
        PUBLIC_SESSION_COOKIE_NAME,
        PUBLIC_SESSION_COOKIE_NAME_LOCAL,
    ):
        value = request.cookies.get(name)
        if value:
            return value
    return None

_SESSION_TOKEN_PREFIX = "aps_"
_SESSION_TOKEN_RE = re.compile(r"^aps_[A-Za-z0-9_-]{43}$")


def generate_session_token() -> str:
    """Return a new opaque token with 256 bits of random material."""

    return _SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def valid_session_token(token: str | None) -> bool:
    return _SESSION_TOKEN_RE.fullmatch(str(token or "")) is not None


def _is_loopback(value: str | None) -> bool:
    try:
        return ipaddress.ip_address(str(value or "").strip()).is_loopback
    except ValueError:
        return False


def _normalize_ip(value: str) -> str | None:
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return None


def derive_bootstrap_subject_key(request: Request, server_secret: str) -> str:
    """Derive a stable pseudonym without retaining IP or user-agent values.

    Proxy identity is consumed only when the direct peer is loopback, and only
    from ``X-Real-IP`` because the production proxy overwrites that header.
    Caller-supplied subject and ``X-Forwarded-For`` headers are deliberately
    ignored: unknown headers are forwarded by default and appended forwarding
    chains can both be caller-spoofable.
    """

    peer = request.client.host if request.client else ""
    source = _normalize_ip(peer) or "unknown"
    if _is_loopback(peer):
        real_ip = request.headers.get("x-real-ip", "")
        source = _normalize_ip(real_ip) or source
    key = hmac.new(
        (server_secret or "").encode("utf-8"),
        ("guest-bootstrap:v1:" + source).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return "bootstrap:v1:" + key


def derive_account_subject_key(
    user_id: UUID | str,
    org_id: UUID | str,
    server_secret: str,
) -> str:
    """Return a deterministic quota pseudonym without persisting account IDs."""

    key = hmac.new(
        (server_secret or "").encode("utf-8"),
        f"account-usage:v1:{org_id}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return "account:v1:" + key


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    suffix = "" if port in {None, default_port} else f":{port}"
    return f"{parsed.scheme}://{host.lower()}{suffix}"


def require_browser_mutation(request: Request) -> None:
    """Require a same-origin browser request plus an unforgeable-by-form header."""

    if not hmac.compare_digest(
        request.headers.get(PUBLIC_MUTATION_HEADER, ""),
        PUBLIC_MUTATION_HEADER_VALUE,
    ):
        raise BrowserMutationRejected()

    supplied = _normalized_origin(request.headers.get("origin", ""))
    if supplied is None:
        raise BrowserMutationRejected()

    host = request.headers.get("host", "").strip().lower()
    if not host:
        raise BrowserMutationRejected()
    direct = _normalized_origin(f"{request.url.scheme}://{host}")
    allowed = {direct} if direct else set()

    peer = request.client.host if request.client else ""
    if _is_loopback(peer):
        proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        forwarded_host = (
            request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
        )
        if proto in {"http", "https"}:
            forwarded = _normalized_origin(f"{proto}://{forwarded_host or host}")
            if forwarded:
                allowed.add(forwarded)
    if supplied not in allowed:
        raise BrowserMutationRejected()
