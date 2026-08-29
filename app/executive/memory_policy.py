from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.executive.safety import ExecutiveSafetyError


@dataclass(frozen=True)
class ExecutiveMemoryPolicy:
    """Host-selected persistent-memory policy fixed for one runtime session.

    The default preserves the authenticated/operator behavior. Public adapters
    can explicitly pass ``disabled()`` when opening an untrusted guest mission;
    chat messages and model output never participate in this decision.
    """

    approved_persistent_memory: bool = True

    @classmethod
    def disabled(cls) -> ExecutiveMemoryPolicy:
        return cls(approved_persistent_memory=False)


DEFAULT_EXECUTIVE_MEMORY_POLICY = ExecutiveMemoryPolicy()


class ExecutiveMemoryCapture(Protocol):
    reply: str
    status: dict[str, Any]


class ExecutiveMemoryRecall(Protocol):
    context: str
    status: dict[str, Any]


@runtime_checkable
class ExecutiveMemoryPort(Protocol):
    """Adapter boundary for approved persistent memory implementations."""

    async def remember(self, text: str) -> ExecutiveMemoryCapture: ...

    async def recall_context(self) -> ExecutiveMemoryRecall: ...

    def safe_status(self) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


def is_explicit_remember_command(message: str) -> bool:
    value = str(message or "").strip()
    return value == "/remember" or (
        value.startswith("/remember")
        and len(value) > len("/remember")
        and value[len("/remember")].isspace()
    )


def explicit_remember_text(message: str) -> str:
    """Extract explicit capture text without consulting a persistence adapter."""

    value = str(message or "").strip()
    if value == "/remember":
        raise ExecutiveSafetyError("use /remember <safe text>")
    if not is_explicit_remember_command(value):
        raise ExecutiveSafetyError("persistent memory command is invalid")
    candidate = value[len("/remember") :].strip()
    if not candidate:
        raise ExecutiveSafetyError("use /remember <safe text>")
    return candidate
