from __future__ import annotations


class PublicAccessError(Exception):
    """Base error for the public account boundary."""


class AccountSessionUnauthorized(PublicAccessError):
    """The opaque browser session is absent, expired, or revoked."""

    def __init__(self) -> None:
        super().__init__("account session required")


class AccountAccessDenied(PublicAccessError):
    """The account lacks a requested public capability."""

    def __init__(self) -> None:
        super().__init__("forbidden")


class AccountResourceNotFound(PublicAccessError, LookupError):
    """A resource is absent or owned by another account (leak-safe 404)."""

    def __init__(self) -> None:
        super().__init__("not found")


class BrowserMutationRejected(PublicAccessError):
    """A cookie-authenticated mutation failed the browser CSRF boundary."""

    def __init__(self) -> None:
        super().__init__("browser mutation rejected")


class UsageQuotaExceeded(PublicAccessError):
    """A deterministic usage window has no remaining capacity."""

    def __init__(
        self,
        *,
        window: str,
        limit: int,
        used: int,
        retry_after_seconds: int,
    ) -> None:
        super().__init__("usage quota exceeded")
        self.window = window
        self.limit = limit
        self.used = used
        self.retry_after_seconds = max(1, int(retry_after_seconds))
