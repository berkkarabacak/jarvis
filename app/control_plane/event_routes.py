from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.control_plane.events import (
    EventAccess,
    EventAuthorizationError,
    EventContractError,
    EventNotFoundError,
    EventValidationError,
)

router = APIRouter(prefix="/api/control-plane/v1", tags=["control-plane-events-v1"])


class PublishEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["executive_message", "handoff", "evidence", "confidence"]
    data: dict[str, Any]


def _control_plane(request: Request):
    control_plane = getattr(request.app.state, "control_plane", None)
    if control_plane is None:
        raise HTTPException(status_code=503, detail="Control plane not initialized")
    return control_plane


def _event_access(request: Request) -> EventAccess:
    """Temporary API-key adapter; ORCH-69 will supply a trusted tenant principal."""

    # The parent api_router authenticates the shared API key. Until ORCH-69 is
    # integrated, that authenticated key is honestly modeled as the existing
    # operator-wide legacy owner. No organization or capability claim is
    # accepted from a request header.
    return EventAccess.legacy_global_owner()


def _event_http(exc: EventContractError) -> HTTPException:
    if isinstance(exc, EventNotFoundError):
        return HTTPException(status_code=404, detail="Mission not found")
    if isinstance(exc, EventAuthorizationError):
        return HTTPException(status_code=403, detail="Event access denied")
    if isinstance(exc, EventValidationError):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=400, detail="Event contract error")


def format_sse_event(event: dict[str, Any]) -> str:
    """Serialize the exact history envelope as one SSE record."""

    payload = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return f"id: {event['cursor']}\nevent: {event['type']}\ndata: {payload}\n\n"


@router.get("/missions/{mission_id}/events")
async def event_history(
    mission_id: str,
    request: Request,
    after: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return await _control_plane(request).events.history(
            access=_event_access(request),
            mission_id=mission_id,
            after=after,
            limit=limit,
        )
    except EventContractError as exc:
        raise _event_http(exc) from exc


@router.post("/missions/{mission_id}/events")
async def publish_event(
    mission_id: str,
    body: PublishEventBody,
    request: Request,
) -> dict[str, Any]:
    try:
        event = await _control_plane(request).events.publish(
            access=_event_access(request),
            mission_id=mission_id,
            event_type=body.type,
            data=body.data,
        )
    except EventContractError as exc:
        raise _event_http(exc) from exc
    return {"event": event}


@router.get("/missions/{mission_id}/events/stream")
async def event_stream(
    mission_id: str,
    request: Request,
    after: str | None = Query(default=None),
    once: bool = Query(default=False),
) -> StreamingResponse:
    access = _event_access(request)
    start_cursor = after or request.headers.get("last-event-id")
    control_plane = _control_plane(request)
    try:
        # Authorize and validate the cursor before response headers are emitted.
        await control_plane.events.history(
            access=access,
            mission_id=mission_id,
            after=start_cursor,
            limit=1,
        )
    except EventContractError as exc:
        raise _event_http(exc) from exc

    async def generate():
        cursor = start_cursor
        last_heartbeat = time.monotonic()
        while True:
            page = await control_plane.events.history(
                access=access,
                mission_id=mission_id,
                after=cursor,
                limit=100,
            )
            for event in page["events"]:
                yield format_sse_event(event)
                last_heartbeat = time.monotonic()
            if page["next_cursor"]:
                cursor = page["next_cursor"]
            if once or await request.is_disconnected():
                return
            if time.monotonic() - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
