from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ChatResult:
    content: str
    raw: dict[str, Any]
    tokens_in: int | None
    tokens_out: int | None
    model: str | None = None
    provider: str | None = None


@dataclass
class LlmStatus:
    provider: str
    healthy: bool
    mode: str
    default_model: str
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "mode": self.mode,
            "default_model": self.default_model,
            "last_error": self.last_error,
        }


@dataclass
class LlmTestResult:
    ok: bool
    provider: str
    message: str
    model: str | None = None
    latency_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "message": self.message,
            "model": self.model,
            "latency_ms": self.latency_ms,
        }


@runtime_checkable
class LlmProvider(Protocol):
    name: str

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> ChatResult: ...

    async def status(self) -> LlmStatus: ...

    async def list_models(self) -> list[str]: ...

    async def test_connection(self, *, model: str | None = None) -> LlmTestResult: ...
