from __future__ import annotations

import copy
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.control_plane.service import build_control_plane
from app.db import Database
from app.executive.adapters.prime import (
    PrimeMessageResult,
    PrimeSessionInfo,
    PrimeUnavailableError,
)
from app.integrations.executive_control_plane import (
    ExecutiveControlPlaneAdapter,
    ExecutiveControlPlaneIntegrationError,
)

AUTH = {"X-Api-Key": "test-secret"}


class SafePrime:
    name = "safe-test-prime"

    def __init__(self) -> None:
        self.sessions: dict[str, PrimeSessionInfo] = {}
        self.message_count = 0

    async def health(self) -> dict[str, object]:
        return {"ok": True, "available": True, "live": True, "rpc": True}

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PrimeSessionInfo:
        session = PrimeSessionInfo(
            session_id=str(uuid.uuid4()),
            role_name=role_name,
            parent_session_id=parent_session_id,
            model=model,
            metadata=dict(metadata or {}),
        )
        self.sessions[session.session_id] = session
        return session

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        if session_id in self.sessions:
            self.sessions[session_id].status = reason

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return list(self.sessions.values())

    async def send_message(
        self,
        session_id: str,
        *,
        message: str,
    ) -> PrimeMessageResult:
        del message
        self.message_count += 1
        return PrimeMessageResult(
            message_id=f"message-{self.message_count}",
            session_id=session_id,
            text="Final safe answer.",
        )

    async def close(self) -> None:
        self.sessions.clear()


class FailingPrime(SafePrime):
    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PrimeSessionInfo:
        del role_name, parent_session_id, model, metadata
        raise PrimeUnavailableError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL")


def _configure(monkeypatch, database_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")


def _safe_batch(mission_id: str) -> dict[str, object]:
    return {
        "target_contract": "orch.control-plane.event",
        "target_contract_version": "1.0",
        "mission_id": mission_id,
        "authorization": "required_at_orch70_publish_adapter",
        "events": [
            {
                "type": "executive_message",
                "data": {
                    "summary": "Final safe answer.",
                    "severity": "info",
                    "action_required": False,
                },
            },
            {
                "type": "evidence",
                "data": {
                    "evidence_id": "message-1",
                    "kind": "trace",
                    "reference_id": "prime-turn:message-1",
                    "label": "Prime executive RPC turn completed",
                    "verification_status": "verified",
                },
            },
            {
                "type": "confidence",
                "data": {
                    "subject_type": "mission",
                    "subject_id": mission_id,
                    "score": 0,
                    "basis": ["status", "evidence"],
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_http_turn_persists_safe_history_and_stream(tmp_path, monkeypatch):
    database_path = tmp_path / "integrated.db"
    _configure(monkeypatch, database_path)
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    private_marker = "SYNTHETIC_BRIEF_SECRET"
    async with app.router.lifespan_context(app):
        app.state.executive_runtime.prime = SafePrime()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.post(
                "/api/executive/runtime/missions",
                json={"brief": "unauthenticated"},
            )
            assert denied.status_code == 401
            assert await app.state.control_plane.list_missions() == []

            client_id = await client.post(
                "/api/executive/runtime/missions",
                headers=AUTH,
                json={"mission_id": "client-owned", "brief": "not accepted"},
            )
            assert client_id.status_code == 422
            assert await app.state.control_plane.list_missions() == []

            opened = await client.post(
                "/api/executive/runtime/missions",
                headers=AUTH,
                json={"brief": f"Plan safely API_KEY={private_marker}"},
            )
            assert opened.status_code == 200, opened.text
            snapshot = opened.json()
            mission_id = snapshot["mission_id"]
            uuid.UUID(mission_id)
            assert snapshot["control_plane"]["status"] == "running"
            assert private_marker not in json.dumps(snapshot)

            mission = await app.state.control_plane.get_mission(mission_id)
            assert mission is not None
            assert mission.title == "Executive AI session"
            assert mission.brief == ""

            turn = await client.post(
                f"/api/executive/runtime/sessions/{snapshot['session_id']}/messages",
                headers=AUTH,
                json={"message": "Give me the executive recommendation"},
            )
            assert turn.status_code == 200, turn.text
            turn_body = turn.json()
            assert turn_body["message"]["text"] == "Final safe answer."
            assert turn_body["event_publication"]["persisted"] is True
            assert [
                event["type"] for event in turn_body["event_publication"]["events"]
            ] == ["executive_message", "evidence", "confidence"]

            history = await client.get(
                f"/api/control-plane/v1/missions/{mission_id}/events",
                headers=AUTH,
            )
            assert history.status_code == 200, history.text
            types = [event["type"] for event in history.json()["events"]]
            assert types == [
                "mission_status",
                "mission_status",
                "mission_status",
                "executive_message",
                "evidence",
                "confidence",
            ]

            stream = await client.get(
                f"/api/control-plane/v1/missions/{mission_id}/events/stream?once=true",
                headers=AUTH,
            )
            assert stream.status_code == 200, stream.text
            assert "event: executive_message" in stream.text
            assert "event: evidence" in stream.text
            assert "event: confidence" in stream.text
            assert private_marker not in stream.text

            stopped = await client.post(
                f"/api/executive/runtime/sessions/{snapshot['session_id']}/stop",
                headers=AUTH,
                json={"status": "stopped", "reason": "ceo_stopped"},
            )
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["control_plane"] == {
                "mission_id": mission_id,
                "status": "killed",
                "synchronized": True,
            }

        cursor = await app.state.db.conn.execute(
            "SELECT title, brief FROM cp_missions WHERE id = ?", (mission_id,)
        )
        mission_row = await cursor.fetchone()
        audit_cursor = await app.state.db.conn.execute(
            "SELECT detail_json FROM cp_audit_events WHERE mission_id = ?",
            (mission_id,),
        )
        audit_rows = await audit_cursor.fetchall()
        durable_text = json.dumps(
            [dict(mission_row), *[dict(row) for row in audit_rows]]
        )
        assert private_marker not in durable_text
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["version", "mission", "extra_event", "private_reasoning"],
)
async def test_bridge_rejects_unsafe_batch_before_public_write(tmp_path, mutation):
    db = Database(tmp_path / f"rejection-{mutation}.db")
    await db.connect()
    service = build_control_plane(db)
    await service.ensure_ready()
    adapter = ExecutiveControlPlaneAdapter(service)
    try:
        mission = await adapter.start_mission()
        batch = copy.deepcopy(_safe_batch(mission.id))
        if mutation == "version":
            batch["target_contract_version"] = "2.0"
        elif mutation == "mission":
            batch["mission_id"] = "different-mission"
        elif mutation == "extra_event":
            batch["events"].append(copy.deepcopy(batch["events"][0]))
        else:
            batch["events"][0]["data"]["summary"] = "private reasoning: hidden"

        with pytest.raises(ExecutiveControlPlaneIntegrationError):
            await adapter.publish_turn(
                batch,
                expected_mission_id=mission.id,
                expected_message_id="message-1",
                expected_final_text="Final safe answer.",
            )
        audit = await service.list_audit(mission_id=mission.id, limit=100)
        assert not any(row["event_type"].startswith("public.") for row in audit)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prime_open_failure_is_safe_and_kills_control_plane_mission(
    tmp_path, monkeypatch
):
    _configure(monkeypatch, tmp_path / "failed-open.db")
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        app.state.executive_runtime.prime = FailingPrime()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/executive/runtime/missions",
                headers=AUTH,
                json={"brief": "fail safely"},
            )
        assert response.status_code == 503
        assert response.json() == {"detail": "Prime RPC is unavailable"}
        assert "SYNTHETIC" not in response.text
        missions = await app.state.control_plane.list_missions()
        assert len(missions) == 1
        assert missions[0].status == "killed"
        assert app.state.executive_registry.list_sessions() == []
        audit = await app.state.control_plane.list_audit(
            mission_id=missions[0].id,
            limit=100,
        )
        assert "SYNTHETIC" not in json.dumps(audit)
        killed = next(row for row in audit if row["event_type"] == "mission.killed")
        assert killed["detail"]["reason"] == "executive_open_failed"
    get_settings.cache_clear()
