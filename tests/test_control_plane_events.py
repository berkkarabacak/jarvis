import json

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from httpx import ASGITransport, AsyncClient

from app.control_plane.event_routes import format_sse_event
from app.control_plane.event_routes import router as event_router
from app.control_plane.events import (
    AUDIT_READ,
    BUDGET_AUDIT_DECISION,
    CONFIDENCE,
    EVENT_PUBLISH,
    EVIDENCE,
    EXECUTIVE_MESSAGE,
    HANDOFF,
    MISSION_READ,
    MISSION_STATUS,
    EventAccess,
    EventAuthorizationError,
    EventNotFoundError,
    EventValidationError,
    decode_cursor,
)
from app.control_plane.models import BudgetError
from app.control_plane.service import build_control_plane
from app.db import Database


@pytest.fixture
async def control_plane(tmp_path):
    db = Database(tmp_path / "events.db")
    await db.connect()
    service = build_control_plane(db)
    await service.ensure_ready()
    try:
        yield service, db
    finally:
        await db.close()


async def _seed_all_types(control_plane):
    service, _ = control_plane
    access = EventAccess.owner("org-a")
    mission = await service.create_mission(
        title="PRIVATE_TITLE_MUST_NOT_PROJECT",
        brief="PRIVATE_BRIEF_MUST_NOT_PROJECT",
        org_id="org-a",
        budget_limit_cents=1000,
    )
    await service.start_mission(mission.id)
    await service.reserve_budget(mission.id, amount_cents=100, note="private note")
    await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=EXECUTIVE_MESSAGE,
        data={"summary": "Planning complete", "severity": "info", "action_required": False},
    )
    await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=HANDOFF,
        data={
            "handoff_id": "handoff-1",
            "from_role": "executive",
            "to_role": "researcher",
            "status": "accepted",
            "summary": "Research scope accepted",
            "evidence_ids": ["evidence-1"],
        },
    )
    await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=EVIDENCE,
        data={
            "evidence_id": "evidence-1",
            "kind": "test",
            "reference_id": "test-run-1",
            "label": "Contract tests",
            "verification_status": "verified",
        },
    )
    await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=CONFIDENCE,
        data={
            "subject_type": "mission",
            "subject_id": mission.id,
            "score": 84,
            "basis": ["tests", "evidence"],
        },
    )
    return service, access, mission


@pytest.mark.asyncio
async def test_v1_all_types_history_cursor_and_replay(control_plane):
    service, access, mission = await _seed_all_types(control_plane)
    history = await service.events.history(
        access=access, mission_id=mission.id, limit=100
    )
    types = {event["type"] for event in history["events"]}
    assert {
        MISSION_STATUS,
        BUDGET_AUDIT_DECISION,
        EXECUTIVE_MESSAGE,
        HANDOFF,
        EVIDENCE,
        CONFIDENCE,
    } <= types

    sequences = [decode_cursor(event["cursor"]) for event in history["events"]]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
    serialized = json.dumps(history)
    assert "PRIVATE_TITLE_MUST_NOT_PROJECT" not in serialized
    assert "PRIVATE_BRIEF_MUST_NOT_PROJECT" not in serialized
    assert "private note" not in serialized
    for event in history["events"]:
        assert event["contract"] == "orch.control-plane.event"
        assert event["contract_version"] == "1.0"
        assert event["visibility"] == "executive_safe"
        assert event["org_id"] == "org-a"
        assert event["mission_id"] == mission.id

    collected = []
    cursor = None
    while True:
        page = await service.events.history(
            access=access, mission_id=mission.id, after=cursor, limit=2
        )
        collected.extend(page["events"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert collected == history["events"]
    replay = await service.events.history(
        access=access, mission_id=mission.id, after=cursor, limit=10
    )
    assert replay["events"] == []
    appended = await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=EXECUTIVE_MESSAGE,
        data={"summary": "Live append after checkpoint"},
    )
    resumed = await service.events.history(
        access=access, mission_id=mission.id, after=cursor, limit=10
    )
    assert resumed["events"] == [appended]
    no_duplicate = await service.events.history(
        access=access,
        mission_id=mission.id,
        after=resumed["next_cursor"],
        limit=10,
    )
    assert no_duplicate["events"] == []


@pytest.mark.asyncio
async def test_authorization_projection_and_secret_boundaries(control_plane):
    service, db = control_plane
    owner = EventAccess.owner("org-a")
    mission = await service.create_mission(
        title="Safe mission", org_id="org-a", budget_limit_cents=100
    )
    await service.reserve_budget(mission.id, amount_cents=10)
    with pytest.raises(BudgetError) as denied:
        await service.reserve_budget(mission.id, amount_cents=1000)
    assert denied.value.denial is not None

    with pytest.raises(EventNotFoundError):
        await service.events.history(
            access=EventAccess.owner("org-b"), mission_id=mission.id
        )
    with pytest.raises(EventAuthorizationError):
        await service.events.history(
            access=EventAccess("org-a", frozenset()), mission_id=mission.id
        )
    with pytest.raises(EventAuthorizationError):
        await service.events.publish(
            access=EventAccess("org-a", frozenset({MISSION_READ, AUDIT_READ})),
            mission_id=mission.id,
            event_type=EXECUTIVE_MESSAGE,
            data={"summary": "Safe"},
        )
    with pytest.raises(EventValidationError):
        await service.events.publish(
            access=owner,
            mission_id=mission.id,
            event_type=MISSION_STATUS,
            data={"status": "succeeded"},
        )
    with pytest.raises(EventValidationError):
        await service.events.publish(
            access=owner,
            mission_id=mission.id,
            event_type=EXECUTIVE_MESSAGE,
            data={
                "summary": "Safe",
                "private_reasoning": "SYNTHETIC_PRIVATE_SENTINEL",
            },
        )

    scrubbed = await service.events.publish(
        access=owner,
        mission_id=mission.id,
        event_type=EXECUTIVE_MESSAGE,
        data={
            "summary": "Connected with Authorization: Bearer SYNTHETIC_FAKE_TOKEN_123456",
            "severity": "warning",
        },
    )
    assert "SYNTHETIC_FAKE_TOKEN" not in json.dumps(scrubbed)
    assert "[redacted]" in scrubbed["data"]["summary"]

    mission_only = EventAccess("org-a", frozenset({MISSION_READ, EVENT_PUBLISH}))
    filtered = await service.events.history(
        access=mission_only, mission_id=mission.id, limit=100
    )
    assert BUDGET_AUDIT_DECISION not in {event["type"] for event in filtered["events"]}
    owner_history = await service.events.history(
        access=owner, mission_id=mission.id, limit=100
    )
    denied_events = [
        event
        for event in owner_history["events"]
        if event["type"] == BUDGET_AUDIT_DECISION
        and event["data"]["outcome"] == "denied"
    ]
    assert denied_events[0]["data"]["reason_code"] == "insufficient_budget"

    cur = await db.conn.execute(
        "SELECT detail_json FROM cp_audit_events WHERE mission_id = ?",
        (mission.id,),
    )
    persisted = "\n".join(row["detail_json"] for row in await cur.fetchall())
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in persisted
    assert "SYNTHETIC_FAKE_TOKEN" not in persisted


@pytest.mark.asyncio
async def test_invalid_cursor_confidence_bounds_and_corrupt_row_fail_closed(control_plane):
    service, _ = control_plane
    access = EventAccess.owner("org-a")
    mission = await service.create_mission(title="Cursor test", org_id="org-a")

    with pytest.raises(EventValidationError):
        await service.events.history(
            access=access, mission_id=mission.id, after="timestamp-pretending-to-be-cursor"
        )
    with pytest.raises(EventValidationError):
        await service.events.publish(
            access=access,
            mission_id=mission.id,
            event_type=CONFIDENCE,
            data={
                "subject_type": "mission",
                "subject_id": mission.id,
                "score": 101,
                "basis": ["tests"],
            },
        )

    corrupt = await service.store.append_audit(
        event_type="public.executive_message",
        actor="synthetic-test",
        mission_id=mission.id,
        detail={
            "summary": "Must not project",
            "token": "SYNTHETIC_CORRUPT_TOKEN",
        },
    )
    corrupt_sequence = await service.store.audit_sequence(corrupt.id)
    later = await service.events.publish(
        access=access,
        mission_id=mission.id,
        event_type=EXECUTIVE_MESSAGE,
        data={"summary": "Valid event after poison row"},
    )
    history = await service.events.history(
        access=access, mission_id=mission.id, limit=100
    )
    assert "SYNTHETIC_CORRUPT_TOKEN" not in json.dumps(history)
    assert corrupt_sequence < decode_cursor(later["cursor"])
    assert history["events"][-1] == later
    assert decode_cursor(history["next_cursor"]) == decode_cursor(later["cursor"])
    assert history["has_more"] is False


@pytest.mark.asyncio
async def test_status_projection_uses_actual_previous_status(control_plane):
    service, _ = control_plane
    access = EventAccess.owner("org-a")
    mission = await service.create_mission(title="Status test", org_id="org-a")
    await service.queue_mission(mission.id)
    await service.store.update_mission_fields(mission.id, status="blocked")
    await service.queue_mission(mission.id)
    history = await service.events.history(
        access=access, mission_id=mission.id, limit=100
    )
    status_events = [
        event for event in history["events"] if event["type"] == MISSION_STATUS
    ]
    assert status_events[-1]["data"]["status"] == "queued"
    assert status_events[-1]["data"]["previous_status"] == "blocked"


def test_sse_formatter_is_single_safe_envelope():
    event = {
        "contract": "orch.control-plane.event",
        "contract_version": "1.0",
        "id": "event-1",
        "cursor": "v1.AAAAAAAAAAE",
        "type": EXECUTIVE_MESSAGE,
        "occurred_at": "2026-08-08T00:00:00.000Z",
        "source": "control_plane",
        "org_id": "org-a",
        "mission_id": "mission-1",
        "visibility": "executive_safe",
        "data": {"summary": "Safe", "severity": "info", "action_required": False},
    }
    record = format_sse_event(event)
    assert record.startswith("id: v1.AAAAAAAAAAE\nevent: executive_message\n")
    assert json.loads(record.split("data: ", 1)[1]) == event


@pytest.mark.parametrize(
    "unsafe",
    [
        "OPENROUTER_API_KEY=SYNTHETIC_ENV_VALUE_123456",
        "Authorization: Basic U1lOVEhFVElDX0ZBS0VfQVVUSA==",
        "https://demo:SYNTHETIC_PASSWORD@demo.invalid/path",
        "https://demo.invalid/path?token=SYNTHETIC_QUERY_VALUE",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
@pytest.mark.asyncio
async def test_credential_shapes_are_scrubbed_before_persistence(control_plane, unsafe):
    service, db = control_plane
    mission = await service.create_mission(title="Scrub test", org_id="org-a")
    event = await service.events.publish(
        access=EventAccess.owner("org-a"),
        mission_id=mission.id,
        event_type=EXECUTIVE_MESSAGE,
        data={"summary": f"Operational update {unsafe}"},
    )
    assert unsafe not in json.dumps(event)
    assert "[redacted]" in event["data"]["summary"]
    cur = await db.conn.execute(
        "SELECT detail_json FROM cp_audit_events WHERE id = ?", (event["id"],)
    )
    row = await cur.fetchone()
    assert unsafe not in row["detail_json"]


@pytest.mark.asyncio
async def test_http_demo_history_and_finite_sse_match(control_plane):
    service, _, mission = await _seed_all_types(control_plane)

    async def require_test_api_key(x_api_key: str | None = Header(default=None)):
        if x_api_key != "test-secret":
            raise HTTPException(status_code=401, detail="Invalid API key")

    app = FastAPI()
    app.state.control_plane = service
    authenticated = APIRouter(dependencies=[Depends(require_test_api_key)])
    authenticated.include_router(event_router)
    app.include_router(authenticated)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get(
            f"/api/control-plane/v1/missions/{mission.id}/events"
        )
        assert missing.status_code == 401
        invalid = await client.get(
            f"/api/control-plane/v1/missions/{mission.id}/events",
            headers={"X-Api-Key": "wrong"},
        )
        assert invalid.status_code == 401

        history_response = await client.get(
            f"/api/control-plane/v1/missions/{mission.id}/events",
            headers={"X-Api-Key": "test-secret"},
        )
        assert history_response.status_code == 200
        history = history_response.json()["events"]

        stream_response = await client.get(
            f"/api/control-plane/v1/missions/{mission.id}/events/stream?once=true",
            headers={"X-Api-Key": "test-secret"},
        )
        assert stream_response.status_code == 200
        streamed = [
            json.loads(line.removeprefix("data: "))
            for line in stream_response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert streamed == history

        last_cursor = history[-1]["cursor"]
        resumed = await client.get(
            f"/api/control-plane/v1/missions/{mission.id}/events/stream?once=true",
            headers={"X-Api-Key": "test-secret", "Last-Event-ID": last_cursor},
        )
        assert "data: " not in resumed.text

    assert json.loads(format_sse_event(history[0]).split("data: ", 1)[1]) == history[0]
