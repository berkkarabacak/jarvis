from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.executive.safety import sanitize_public_metadata
from app.executive.telemetry import GenerationTelemetry

PrimeTelemetryDiagnostic = Literal[
    "telemetry_payload_callback_unobserved",
    "telemetry_payload_policy_rejected",
    "telemetry_provider_response_unobserved",
    "telemetry_provider_response_2xx",
    "telemetry_provider_http_400",
    "telemetry_provider_http_402",
    "telemetry_provider_http_404",
    "telemetry_provider_http_429",
    "telemetry_provider_http_4xx_other",
    "telemetry_provider_http_5xx",
    "telemetry_provider_http_other",
    "telemetry_generation_header_missing",
    "telemetry_generation_header_invalid",
    "telemetry_message_receipt_unobserved",
    "telemetry_message_receipt_invalid",
    "telemetry_adapter_correlation_failed",
    "telemetry_adapter_correlated",
    "telemetry_diagnostic_invalid",
]

PRIME_TELEMETRY_DIAGNOSTICS = frozenset(PrimeTelemetryDiagnostic.__args__)


class PrimeRuntimeError(RuntimeError):
    """Safe operational error from the Prime adapter boundary."""


class PrimeUnavailableError(PrimeRuntimeError):
    pass


@dataclass
class PrimeSessionInfo:
    """Handle for a headless Prime Agent session (no credentials embedded)."""

    session_id: str
    role_name: str
    status: str = "active"
    parent_session_id: str | None = None
    model: str | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "role_name": self.role_name,
            "status": self.status,
            "parent_session_id": self.parent_session_id,
            "model": self.model,
            "created_at": self.created_at,
            "metadata": sanitize_public_metadata(self.metadata),
        }


@dataclass(frozen=True)
class PrimeMessageResult:
    """Public-safe result of one completed Prime RPC prompt."""

    message_id: str
    session_id: str
    text: str
    safety_filtered: bool = False
    generation: GenerationTelemetry | None = field(default=None, repr=False)
    telemetry_diagnostic: PrimeTelemetryDiagnostic | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.telemetry_diagnostic is not None and (
            not isinstance(self.telemetry_diagnostic, str)
            or self.telemetry_diagnostic not in PRIME_TELEMETRY_DIAGNOSTICS
        ):
            raise ValueError("Prime telemetry diagnostic is unavailable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "text": self.text,
            "safety_filtered": self.safety_filtered,
        }


@runtime_checkable
class PrimeAgentRuntime(Protocol):
    """Port for pinned headless Prime Agent RPC (ORCH-59/71).

    Implementations must not require the executive core to import vendor SDKs.
    Null/fake adapters keep the control path testable without binaries.
    """

    name: str

    async def health(self) -> dict[str, Any]: ...

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo: ...

    async def stop_session(
        self, session_id: str, *, reason: str = "stopped"
    ) -> None: ...

    async def list_sessions(self) -> list[PrimeSessionInfo]: ...

    async def send_message(
        self, session_id: str, *, message: str
    ) -> PrimeMessageResult: ...

    async def close(self) -> None: ...


class NullPrimeAgent:
    """Default adapter: explicit no-op until Prime binary is wired.

    Never accepts or logs credentials. Sessions are in-process handles only.
    """

    name = "null"

    def __init__(self) -> None:
        self._sessions: dict[str, PrimeSessionInfo] = {}
        self._last_error: str | None = None

    async def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": False,
            "availability": "unavailable",
            "adapter": self.name,
            "prime_binary": False,
            "rpc": False,
            "live": False,
            "credentials_configured": False,
            "last_error": self._last_error,
            "detail": (
                "NullPrimeAgent — Prime RPC unavailable; executive continues in "
                "compatibility mode without a live binary"
            ),
        }

    def mark_error(self, message: str) -> None:
        """Record a safe operational error (no secrets)."""
        text = (message or "").strip()
        for token in ("key=", "token=", "secret=", "password=", "authorization"):
            if token in text.lower():
                text = "provider error (redacted)"
                break
        self._last_error = text[:240] or None

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo:
        info = PrimeSessionInfo(
            session_id=str(uuid.uuid4()),
            role_name=role_name,
            parent_session_id=parent_session_id,
            model=model,
            metadata=dict(metadata or {}),
            status="active",
        )
        # Track locally for list/stop symmetry without external process.
        self._sessions[info.session_id] = info
        return info

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        info = self._sessions.get(session_id)
        if info is not None:
            info.status = reason or "stopped"

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self._sessions.values())

    async def send_message(
        self, session_id: str, *, message: str
    ) -> PrimeMessageResult:
        del session_id, message
        raise PrimeUnavailableError("Prime RPC is unavailable")

    async def close(self) -> None:
        self._sessions.clear()
