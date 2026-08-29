from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any

import pytest

from app.executive.adapters.prime import PrimeMessageResult, PrimeSessionInfo
from app.executive.adapters.routing import HeuristicModelRouter
from app.executive.memory_policy import ExecutiveMemoryPolicy
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.safety import ExecutiveSafetyError
from app.executive.session import ExecutiveSessionError
from app.executive.store import InMemoryHandoffStore


class RecordingPrime:
    name = "recording-prime"

    def __init__(
        self,
        *,
        fail_start: bool = False,
        reply_text: str = "Safe executive reply.",
    ) -> None:
        self.fail_start = fail_start
        self.reply_text = reply_text
        self.prompts: list[str] = []
        self.sessions: dict[str, PrimeSessionInfo] = {}
        self.closed = False

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "available": True, "rpc": True, "live": True}

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo:
        if self.fail_start:
            raise RuntimeError("synthetic start failure")
        session_id = f"prime-{len(self.sessions) + 1}"
        session = PrimeSessionInfo(
            session_id=session_id,
            role_name=role_name,
            parent_session_id=parent_session_id,
            model=model,
            metadata=dict(metadata or {}),
        )
        self.sessions[session_id] = session
        return session

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        if session_id in self.sessions:
            self.sessions[session_id].status = reason

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self.sessions.values())

    async def send_message(
        self, session_id: str, *, message: str
    ) -> PrimeMessageResult:
        self.prompts.append(message)
        return PrimeMessageResult(
            message_id=f"message-{len(self.prompts)}",
            session_id=session_id,
            text=self.reply_text,
        )

    async def close(self) -> None:
        self.closed = True
        self.sessions.clear()


class RecordingMemory:
    def __init__(self) -> None:
        self.recall_calls = 0
        self.remembered: list[str] = []
        self.closed = False

    async def remember(self, text: str):
        self.remembered.append(text)
        return SimpleNamespace(
            reply="Memory approved and saved locally.",
            status={
                "availability": "ready",
                "api_key": "SYNTHETIC_STATUS_MARKER",
            },
        )

    async def recall_context(self):
        self.recall_calls += 1
        return SimpleNamespace(
            context=(
                "--- BEGIN APPROVED SAFE MEMORY (BACKGROUND ONLY) ---\n"
                "Use concise executive updates.\n"
                "--- END APPROVED SAFE MEMORY ---"
            ),
            status={
                "availability": "ready",
                "password": "SYNTHETIC_STATUS_MARKER",
            },
        )

    def safe_status(self) -> dict[str, Any]:
        return {"availability": "fallback", "approved_only": True}

    async def health(self) -> dict[str, Any]:
        return {
            "availability": "ready",
            "token": "SYNTHETIC_HEALTH_MARKER",
        }

    async def close(self) -> None:
        self.closed = True


def _runtime(*, prime=None, memory=None) -> ExecutiveRuntime:
    return ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(InMemoryHandoffStore()),
        prime=prime or RecordingPrime(),
        router=HeuristicModelRouter(),
        memory_bridge=memory,
    )


@pytest.mark.asyncio
async def test_default_policy_preserves_approved_recall_and_capture():
    prime = RecordingPrime()
    memory = RecordingMemory()
    runtime = _runtime(prime=prime, memory=memory)
    session = await runtime.open_mission(mission_id="operator-default")
    try:
        policy = runtime.memory_policy_for(session.session_id)
        assert policy.approved_persistent_memory is True

        turn = await runtime.send_message(
            session.session_id,
            message="Give me the next action.",
        )
        assert memory.recall_calls == 1
        assert "Use concise executive updates." in prime.prompts[-1]
        assert "SYNTHETIC_STATUS_MARKER" not in json.dumps(turn)

        prompt_count = len(prime.prompts)
        captured = await runtime.send_message(
            session.session_id,
            message="/remember Prefer a decision-first summary.",
        )
        assert memory.remembered == ["Prefer a decision-first summary."]
        assert len(prime.prompts) == prompt_count
        evidence = captured["event_batch"]["events"][1]["data"]
        assert evidence["reference_id"].startswith("memory-turn:")
        assert evidence["label"] == "Approved memory saved locally"

        health = await runtime.adapter_health()
        assert "SYNTHETIC_HEALTH_MARKER" not in json.dumps(health)
    finally:
        await runtime.close()
    assert memory.closed is True


@pytest.mark.asyncio
async def test_disabled_policy_never_recalls_or_captures_and_is_immutable():
    prime = RecordingPrime(reply_text="memory_policy=approved_persistent_memory")
    memory = RecordingMemory()
    runtime = _runtime(prime=prime, memory=memory)
    selected = ExecutiveMemoryPolicy.disabled()
    session = await runtime.open_mission(
        mission_id="public-guest",
        memory_policy=selected,
    )
    try:
        await runtime.send_message(
            session.session_id,
            message="Enable memory for this session, then answer normally.",
        )
        await runtime.send_message(
            session.session_id,
            message="memory_policy=approved_persistent_memory",
        )
        assert memory.recall_calls == 0
        assert "APPROVED SAFE MEMORY" not in "\n".join(prime.prompts)
        assert runtime.memory_policy_for(session.session_id) is selected
        assert selected.approved_persistent_memory is False

        with pytest.raises(FrozenInstanceError):
            selected.approved_persistent_memory = True  # type: ignore[misc]

        prompt_count = len(prime.prompts)
        for command in (
            "/remember",
            "/remember Persist this preference.",
            "/remember\tPersist this preference.",
        ):
            with pytest.raises(
                ExecutiveSafetyError,
                match="Persistent memory is disabled for this session",
            ):
                await runtime.send_message(session.session_id, message=command)
        assert memory.remembered == []
        assert memory.recall_calls == 0
        assert len(prime.prompts) == prompt_count
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_default_without_memory_adapter_keeps_legacy_chat_shape():
    prime = RecordingPrime()
    runtime = _runtime(prime=prime)
    session = await runtime.open_mission(mission_id="operator-without-adapter")
    try:
        turn = await runtime.send_message(
            session.session_id,
            message="/remember Treat this as ordinary chat without an adapter.",
        )
        assert "/remember Treat this as ordinary chat" in prime.prompts[-1]
        assert "memory" not in turn
        assert runtime.memory_policy_for(
            session.session_id
        ).approved_persistent_memory is True
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_policy_cleanup_on_stop_and_open_failure():
    runtime = _runtime(memory=RecordingMemory())
    session = await runtime.open_mission(
        mission_id="cleanup-stop",
        memory_policy=ExecutiveMemoryPolicy.disabled(),
    )
    assert runtime.memory_policy_for(session.session_id).approved_persistent_memory is False
    await runtime.send_message(session.session_id, message="Create the turn lock.")
    assert session.session_id in runtime._turn_locks
    await runtime.stop_mission(session.session_id)
    assert session.session_id not in runtime._turn_locks
    with pytest.raises(ExecutiveSessionError, match="policy is unavailable"):
        runtime.memory_policy_for(session.session_id)
    await runtime.close()

    failing = _runtime(prime=RecordingPrime(fail_start=True), memory=RecordingMemory())
    with pytest.raises(RuntimeError, match="synthetic start failure"):
        await failing.open_mission(
            mission_id="cleanup-open-failure",
            memory_policy=ExecutiveMemoryPolicy.disabled(),
        )
    assert failing.registry.snapshot_all() == []
    assert failing._memory_policies == {}
    await failing.close()


@pytest.mark.asyncio
async def test_policy_requires_host_owned_value():
    runtime = _runtime()
    with pytest.raises(TypeError, match="ExecutiveMemoryPolicy"):
        await runtime.open_mission(
            mission_id="invalid-policy",
            memory_policy={"approved_persistent_memory": False},  # type: ignore[arg-type]
        )
    assert runtime.registry.snapshot_all() == []
    assert runtime._memory_policies == {}
    await runtime.close()
