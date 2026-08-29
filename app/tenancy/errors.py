from __future__ import annotations


class TenantNotFound(LookupError):
    """Resource missing *or* not visible in the caller's org (leak-safe 404)."""

    def __init__(self, message: str = "not found") -> None:
        super().__init__(message)
        self.message = message


class TenantAccessError(PermissionError):
    """Authenticated but role insufficient for the operation."""

    def __init__(self, message: str = "forbidden") -> None:
        super().__init__(message)
        self.message = message
