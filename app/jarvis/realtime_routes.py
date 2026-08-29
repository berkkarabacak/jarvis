"""Jarvis Realtime HTTP API — mint ephemeral OpenAI session + run local tools."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.jarvis.gateway import get_gateway, model_view
from app.jarvis.realtime import (
    TEST_FORCE_ENGLISH,
    build_minimal_session_config,
    build_realtime_session_config,
    locale_from_accept_language,
    openai_api_key,
    prepare_realtime_tool_call,
    realtime_flag_enabled,
    resolve_realtime_voice,
    sanitize_talk_locale,
    sanitize_talk_timezone,
)
from app.jarvis.talk_log import (
    allow_write,
    append_turn,
    last_conversation,
    persist_ask,
    persist_tool,
)
from app.jarvis.voice_ask import (
    ASK_HIRE_MAX,
    attach_public_talk_sheet,
    ask_text_max,
    listen_health,
    run_voice_ask,
)
from app.jarvis.workspace import default_workspace

log = logging.getLogger("jarvis.realtime")

router = APIRouter(prefix="/api/jarvis", tags=["jarvis-realtime"])


class ToolRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Public Talk Settings: yes/ask/no for apps/files/computer. Per-request.
    allowed: dict[str, str] | None = None


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=32)
    confirm_id: str | None = Field(default=None, max_length=80)
    # Raw ASR transcript, not model-authored text — see confirm_local_tool.
    utterance: str | None = Field(default=None, max_length=400)
    # Recogniser confidence for that transcript, when the client has it. Below
    # nonce.MIN_CONFIDENCE the challenge re-prompts instead of resolving, and
    # does not consume its single use.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def _realtime_enabled() -> bool:
    return realtime_flag_enabled()


def _session_unavailable_response() -> JSONResponse:
    """Realtime is an optional upgrade. Missing OpenAI must not block talk."""
    health = listen_health(lite=True)
    can_listen = bool(health.get("can_listen"))
    payload: dict[str, Any] = {
        "ok": False,
        "realtime": False,
        "can_listen": can_listen,
        "listen_mode": health.get("listen_mode") or "none",
        "can_speak": bool(health.get("can_speak")),
        "speak_mode": health.get("speak_mode") or "none",
        "neural_tts": bool(health.get("neural_tts")),
        "openrouter": bool(health.get("openrouter")),
        "fallback": "browser_speech" if can_listen else "none",
    }
    if can_listen:
        return JSONResponse(
            payload, status_code=409, headers={"Cache-Control": "no-store"}
        )
    from app.jarvis.talk_auth import CANT_TALK

    payload["detail"] = CANT_TALK
    return JSONResponse(
        payload, status_code=503, headers={"Cache-Control": "no-store"}
    )


@router.get("/health")
async def jarvis_health(lite: bool = False) -> dict[str, Any]:
    """Listen capability is independent of OpenAI Realtime.

    ``realtime`` is the optional OpenAI upgrade. ``can_listen`` is true when
    OpenRouter is configured (browser speech + /ask) or when Realtime can mint.

    ``?lite=1`` skips the helper-model catalog and spend sheet so first open
    is not blocked on ``public_talk_sheet``. Full health is for Settings.
    """
    return listen_health(lite=lite)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Casual /ask stays 400. Hire / create-many-files may use ASK_HIRE_MAX.
    # Field ceiling is the hire cap; ask_text_max enforces the split.
    text: str = Field(min_length=1, max_length=ASK_HIRE_MAX)
    # Public Talk Settings: yes/ask/no for apps/files/computer. Per-request.
    allowed: dict[str, str] | None = None

    @field_validator("text")
    @classmethod
    def split_ask_cap(cls, value: str) -> str:
        raw = (value or "").strip()
        limit = ask_text_max(raw)
        if len(raw) > limit:
            raise ValueError(f"text longer than {limit} characters")
        return value


class SpeakBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    voice: str | None = Field(default=None, max_length=32)


class TalkLogBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=16)
    text: str = Field(default="", max_length=4000)
    tool: str | None = Field(default=None, max_length=64)
    result: str | None = Field(default=None, max_length=800)


def _client_key(request: Request) -> str:
    try:
        return (request.client.host if request.client else "") or "anon"
    except Exception:
        return "anon"


@router.post("/ask")
async def jarvis_ask(body: AskBody) -> dict[str, Any]:
    """Spoken or typed ask via OpenRouter + tools (no OpenAI key required)."""
    from app.jarvis.talk_allow import reset_request_allow, set_request_allow

    token = set_request_allow(body.allowed)
    try:
        result = await run_voice_ask(body.text)
    finally:
        reset_request_allow(token)
    if isinstance(result, dict):
        persist_ask(body.text, result)
        return attach_public_talk_sheet(result)
    return result


@router.post("/talk/log")
async def post_public_talk_log(body: TalkLogBody, request: Request) -> dict[str, Any]:
    """Append one public Talk turn. No API key — rate-limited and size-capped."""
    if not allow_write(_client_key(request)):
        raise HTTPException(status_code=429, detail="Talk log rate limit")
    stored = append_turn(body.role, body.text, tool=body.tool, result=body.result)
    if stored is None:
        raise HTTPException(status_code=400, detail="invalid talk turn")
    return {"ok": True, "turn": stored}


@router.get("/talk/last")
async def get_public_talk_last() -> dict[str, Any]:
    """Last public Talk turns, newest last, plus started_at. No secrets."""
    convo = last_conversation()
    return {"ok": True, "started_at": convo.get("started_at"), "turns": convo.get("turns") or []}


@router.post("/speak")
async def jarvis_speak(body: SpeakBody) -> Response:
    """Neural TTS for OpenRouter-only speak-back and confirm-code readback.

    Uses OpenAI ``audio/speech`` or OpenRouter ``audio/speech``. Never SAPI.
    Voice is the stored Realtime allow-list id (default marin).
    """
    from app.jarvis.tts import neural_tts_available, synthesize_speech

    if not neural_tts_available():
        raise HTTPException(
            status_code=503,
            detail="Neural TTS is not available",
        )
    audio = await synthesize_speech(body.text, body.voice)
    if not audio:
        raise HTTPException(
            status_code=503,
            detail="Neural TTS is not available",
        )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/realtime/session")
async def mint_realtime_session(request: Request) -> JSONResponse:
    """Mint an ephemeral OpenAI Realtime client secret with Jarvis tools baked in.

    When the OpenAI key is missing, talk continues on OpenRouter
    (browser speech + /ask + neural TTS). This endpoint must not tell
    anyone that an OpenAI key is required to talk.
    """
    if not _realtime_enabled():
        return _session_unavailable_response()
    key = openai_api_key()
    if not key:
        return _session_unavailable_response()

    voice_override = None
    locale = ""
    timezone = ""
    try:
        body = await request.json()
        if isinstance(body, dict):
            voice_override = body.get("voice")
            locale = sanitize_talk_locale(str(body.get("locale") or ""))
            timezone = sanitize_talk_timezone(str(body.get("timezone") or ""))
    except Exception:
        voice_override = None
    if not locale:
        locale = locale_from_accept_language(request.headers.get("accept-language"))
    # TEST: public Talk is not selling yet. Ignore phone locale / Accept-Language
    # so Italy / Korea / Brazil do not get a first hello in another language.
    # Flip TEST_FORCE_ENGLISH to False to restore locale-again worldwide.
    if TEST_FORCE_ENGLISH:
        locale = "en"
    voice = resolve_realtime_voice(str(voice_override) if voice_override else None)

    session = build_realtime_session_config(
        voice=voice,
        locale=locale or None,
        timezone=None if TEST_FORCE_ENGLISH else (timezone or None),
    )
    applied = True
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"session": session},
        )
        if res.status_code == 400:
            log.warning("realtime rich session rejected: %s", res.text[:400])
            applied = False
            res = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"session": build_minimal_session_config(voice=voice)},
            )
        if res.status_code >= 400:
            log.error("realtime mint failed %s: %s", res.status_code, res.text[:400])
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI realtime mint failed ({res.status_code})",
            )
        data = res.json()

    value = data.get("value") or (data.get("client_secret") or {}).get("value")
    if not value:
        raise HTTPException(status_code=502, detail="No client secret in OpenAI response")

    # If mint dropped tools/instructions, client applies full session over data channel
    payload: dict[str, Any] = {
        "value": value,
        "applied": applied,
        "workspace": str(default_workspace()),
        "voice": voice,
    }
    if not applied:
        # strip type/model if needed — client sends session.update
        replay = {k: v for k, v in session.items() if k != "model"}
        payload["session"] = replay

    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post("/tools/run")
async def run_local_tool(body: ToolRunBody) -> dict[str, Any]:
    """Execute one permissioned local tool; called by the Realtime browser client."""
    from app.jarvis.talk_allow import reset_request_allow, set_request_allow

    allow_token = set_request_allow(body.allowed)
    try:
        return await _run_local_tool(body)
    finally:
        reset_request_allow(allow_token)


async def _run_local_tool(body: ToolRunBody) -> dict[str, Any]:
    name = body.name.strip()
    if name in {"get_disk_space", "diskSpace", "free_space"}:
        name = "get_disk_space"
    if name in {"get_github_repos", "github_repos"}:
        name = "list_github_repos"
    gw = get_gateway()
    user_goal = ""
    try:
        user_goal = str(gw._tracker("realtime-model").user_goal or "")
    except Exception:
        user_goal = ""
    name, arguments, early = prepare_realtime_tool_call(
        name,
        body.arguments or {},
        user_goal=user_goal,
    )
    if early is not None:
        safe = model_view(early)
        persist_tool(name, safe)
        return {"name": name, "result": safe, "ui": early}
    # ORCH-319: this endpoint carries MODEL tool calls, so everything arriving
    # here is model-authored. gateway.run() lets it cancel and refuses to let
    # it approve; the result is then narrowed to the model-safe projection so
    # no one-time code or confirm_id goes back into the model's context.
    result = gw.run(
        name,
        arguments,
        source="realtime-model",
        confirmed=False,
    )
    if name == "spawn_child":
        from app.jarvis.voice_ask import recover_spawn_child_limit

        result = recover_spawn_child_limit(
            name,
            arguments,
            result if isinstance(result, dict) else {},
            lambda args: gw.run(
                "spawn_child",
                args,
                source="realtime-model",
                confirmed=False,
            ),
        )
    # Two projections, named so the safe one is the obvious thing to forward:
    #   result -> may go into model context
    #   ui     -> everything, for the local interface only (panel, readback)
    # The browser previously received one blob and had to remember to delete
    # the secret fields before forwarding. It deleted one of the two.
    safe = model_view(result)
    persist_tool(name, safe)
    return {"name": name, "result": safe, "ui": result}


@router.post("/tools/confirm")
async def confirm_local_tool(body: ConfirmBody) -> dict[str, Any]:
    """Approve or deny a pending L3+ action — the HUMAN channel (ORCH-319).

    Reached only by the browser itself: the Allow/Cancel buttons, and the raw
    ASR transcript of what the user actually said. The model cannot call this;
    it can only emit tool calls, which land on /tools/run and cannot approve.
    That difference is the whole control — `utterance` here is speech-to-text
    output, not something a model composed.
    """
    gw = get_gateway()
    if body.utterance:
        result = gw.resolve_spoken(
            body.utterance, source="realtime-asr", confidence=body.confidence
        )
        return {"ok": bool(result.get("ok", True)), "result": result}
    if body.confirm_id:
        result = gw.confirm(body.confirm_id, body.decision, source="realtime-ui")
    else:
        result = gw.confirm_latest(body.decision, source="realtime-ui")
    return {"ok": bool(result.get("ok", True)), "result": result}


@router.get("/tools/pending")
async def list_pending_confirms() -> dict[str, Any]:
    return {"pending": get_gateway().pending_confirms()}


class TaintClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="realtime", max_length=80)
    goal: str = Field(default="", max_length=4000)


@router.post("/taint/clear")
async def clear_taint(body: TaintClearBody | None = None) -> dict[str, Any]:
    """Clear session taint after a fresh user utterance (ORCH-297 / ORCH-376)."""
    src = (body.source if body else None) or "realtime"
    goal = (body.goal if body else "") or ""
    get_gateway().clear_taint(
        str(src).strip() or "realtime",
        goal=goal.strip() or None,
    )
    return {"ok": True, "source": str(src).strip() or "realtime"}


@router.get("/prime/progress")
async def prime_progress(since: float = 0.0) -> dict[str, Any]:
    """B4: rate-limited Prime narration events for Realtime client polling."""
    from app.jarvis.prime_progress import get_progress_bus

    bus = get_progress_bus()
    return {
        "events": bus.recent(since_ts=since, limit=10),
        "silenced": bus.is_silenced(),
        "enabled": bus.narration_enabled(),
    }


@router.post("/prime/silence")
async def prime_silence(seconds: float = 300.0) -> dict[str, Any]:
    from app.jarvis.prime_progress import get_progress_bus

    get_progress_bus().silence(seconds)
    return {"ok": True, "silenced_for_sec": seconds}
