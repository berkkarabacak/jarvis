"""Operator / hosted talk credentials.

Berkly holds the talk secret. Family users never type a key. Resolution
order for a local model call:

1. ``OPENROUTER_API_KEY`` from the process / packager / user ``.env``
2. ``JARVIS_OPERATOR_OPENROUTER_KEY`` injected at install/build time

When both are empty, Kimi Code (``KIMI_CODE_API_KEY`` / ``KIMI_API_KEY``)
can still lift cheap talk locally. If that is also empty, the desktop
talks through ``JARVIS_HOSTED_TALK_URL`` (a berkly server that already
has the operator key). Packaged Windows builds default that URL in the
Electron shell — never in this file as a hardcoded secret.

Do not put a real key, ``sk-or-`` placeholder, or ``sk-`` placeholder here.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Public talk host Berk operates. Not a secret. Packaged desktop injects this
# when the local user ``.env`` has no key.
DEFAULT_HOSTED_TALK_URL = "https://berkkarabacak.com/jarvis"

# User-facing copy when talk cannot run. Never ask for a key.
CANT_TALK = "Can't talk right now"


def local_openrouter_key() -> str:
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def operator_openrouter_key() -> str:
    return (os.environ.get("JARVIS_OPERATOR_OPENROUTER_KEY") or "").strip()


def openrouter_api_key() -> str:
    """Key the local process may use. Operator inject wins after a blank user env."""
    return local_openrouter_key() or operator_openrouter_key()


def kimi_api_key() -> str:
    """Kimi Code key. Prefer KIMI_CODE_API_KEY; KIMI_API_KEY is the alias."""
    return (
        (os.environ.get("KIMI_CODE_API_KEY") or "").strip()
        or (os.environ.get("KIMI_API_KEY") or "").strip()
    )


def hosted_talk_url() -> str:
    return (os.environ.get("JARVIS_HOSTED_TALK_URL") or "").strip().rstrip("/")


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_loopback(url: str) -> bool:
    return _hostname(url) in {"127.0.0.1", "localhost", "::1"}


def _is_self_hosted_url(url: str) -> bool:
    """Refuse to proxy to ourselves (avoids a loop on the hosted server)."""
    if _is_loopback(url):
        return True
    pub = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if pub and url.rstrip("/") == pub.rstrip("/"):
        return True
    return False


def should_use_hosted_talk() -> bool:
    """True when this process has no local/operator key and a remote talk host."""
    if openrouter_api_key() or kimi_api_key():
        return False
    url = hosted_talk_url()
    if not url:
        return False
    if _is_self_hosted_url(url):
        return False
    return True


def talk_ready() -> bool:
    return bool(openrouter_api_key() or kimi_api_key() or should_use_hosted_talk())


def hosted_talk_endpoint(name: str) -> str:
    base = hosted_talk_url()
    slug = (name or "").strip().strip("/")
    if not base:
        return ""
    if base.endswith("/api/jarvis"):
        return f"{base}/{slug}"
    return f"{base}/api/jarvis/{slug}"
