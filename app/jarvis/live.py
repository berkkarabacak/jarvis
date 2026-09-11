"""GPT-Live session config, event unwrap, and tool-result mapping.

Public Talk defaults to OpenAI GPT-Live-1. The browser sends an SDP offer to
``POST /api/jarvis/live/session``; this module builds the trusted-server
payload (short voice prompt + Responses delegation) and maps nested
``response.event`` function calls back onto the existing Jarvis gateway.

The long-lived OpenAI key never leaves the server. Live audio does not accept
images: ``see_screen`` / screenshot stay on the delegated backend and return
short text facts.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.jarvis.hosted_openai import openai_api_key
from app.jarvis.realtime import (
    build_instructions,
    locale_default_instruction,
    resolve_realtime_voice,
    tools_for_realtime,
)


def _force_english() -> bool:
    from app.jarvis import realtime as rt

    return bool(rt.TEST_FORCE_ENGLISH)

LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"
DEFAULT_LIVE_MODEL = "gpt-live-1"
DEFAULT_BACKEND_MODEL = "gpt-5.6-terra"
MAX_SDP_CHARS = 96 * 1024

# Voice prompt stays short. Look / click / confirm / tool rules live on the
# delegated Responses backend — do not dump the Realtime mega-prompt here.
_LIVE_VOICE_INSTRUCTIONS = """
You are Jarvis, a calm, friendly voice colleague for berkly.
Speak warmly and naturally, in short spoken sentences. Not a robot.
If a last conversation recap is present, continue that chat. Do not greet as if new.
Hello / how are you / say hi / reply-with-exactly: just talk. No tools. No chrome. No disk.
Never speak a leftover last_look or screen caption (focused window, weather page, old see_screen).
Stop means stop. Say OK. Do not offer more details.
Pronunciation / improve my English: stay in conversation. No tools.
Really? / what do you think: one or two sentences on THE last Talk topic.

Backchannel policy: Use moderate backchannels. Acknowledge naturally without competing with the main response.

Interruption policy: Stop speaking when the user interrupts. Listen to what they say.

You cannot see images or the screen yourself. The Live audio path does not accept pictures.
When they ask what is on the screen, or to look / click / type / open / close / install,
delegate. Speak only the short text facts the backend returns. Never claim you can see
the screen. Never invent headlines, disk numbers, or that a window is gone.

Delegation policy:
Backend tools:
- Computer: look at jarvis-computer, click, type, keys, open apps or URLs, close windows
- Facts: disk space, GitHub repos, files, memory, helpers (spawn_child)
- Confirm: the app itself reads a one-time code; you never invent or approve a code

Delegate to the backend when:
- The request needs a computer action, a look, current facts, files, helpers, or confirm
- A correction changes work already requested
- They asked what you see / what's on the screen / look

Do not delegate to the backend when:
- You can answer from the last Talk words (never a leftover last_look / window caption)
- Hello, say hi, reply-with-exactly, math, or a brief clarification
- They only asked you to stop or repeat

Delegate before giving an answer that depends on backend work.
Do not guess the result while waiting.
Greet first in one short line, then listen. Do not call tools on that hello.
"""

_LIVE_VOICE_TEST_ENGLISH = """
TEST_FORCE_ENGLISH: Speak English only. First hello in English.
Do not greet in the phone locale. Do not invent Italian, Korean, or Portuguese.
Do not switch language because of locale, timezone, name, or accent.
Stay in English for this test session.
"""

_LIVE_BACKEND_VISION = """
Live audio cannot accept images. see_screen and screenshot run on this backend.
Return short text facts only (vision_description / summary). Never send image
bytes or data URLs back to the voice model. Never claim vision is deferred.
If they asked what is on the screen, look, then one short line from that fresh look.
"""


def voice_path() -> str:
    """``live`` (default) or emergency ``realtime``.

    ``JARVIS_VOICE=realtime`` keeps the old Realtime mint path. Unset / ``live``
    / any other value uses GPT-Live-1.
    """
    raw = (os.environ.get("JARVIS_VOICE") or "live").strip().lower()
    if raw in {"realtime", "openai_realtime"}:
        return "realtime"
    return "live"


def webrtc_voice_available() -> bool:
    from app.jarvis.realtime import realtime_flag_enabled

    return realtime_flag_enabled() and bool(openai_api_key())


def live_available() -> bool:
    return webrtc_voice_available() and voice_path() == "live"


def live_model() -> str:
    return (os.environ.get("OPENAI_LIVE_MODEL") or DEFAULT_LIVE_MODEL).strip() or (
        DEFAULT_LIVE_MODEL
    )


def live_backend_model() -> str:
    return (
        os.environ.get("OPENAI_LIVE_BACKEND_MODEL") or DEFAULT_BACKEND_MODEL
    ).strip() or DEFAULT_BACKEND_MODEL


def build_voice_instructions(
    locale: str | None = None,
    timezone: str | None = None,
) -> str:
    """Short colleague / interrupt / delegate prompt for ``session.instructions``."""
    extra = locale_default_instruction(locale, timezone).strip()
    parts: list[str] = []
    if _force_english():
        parts.append(_LIVE_VOICE_TEST_ENGLISH.strip())
    elif extra:
        parts.append(extra)
    parts.append(_LIVE_VOICE_INSTRUCTIONS.strip())
    try:
        from app.jarvis.talk_log import talk_recap_for_session

        recap = talk_recap_for_session().strip()
    except Exception:
        recap = ""
    if recap:
        parts.append(
            "A last conversation recap exists. Continue that chat. Do not greet as if new."
        )
    return "\n\n".join(p for p in parts if p)


def build_backend_instructions(
    locale: str | None = None,
    timezone: str | None = None,
) -> str:
    """Look / click / confirm / tool rules for the delegated Responses model."""
    base = build_instructions(locale=locale, timezone=timezone).strip()
    return base + "\n\n" + _LIVE_BACKEND_VISION.strip()


def tools_for_live() -> list[dict[str, Any]]:
    """Responses function tools. Same Jarvis surface as Realtime; no images."""
    return tools_for_realtime()


def build_live_session_config(
    voice: str | None = None,
    locale: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    chosen = resolve_realtime_voice(voice)
    transcription: dict[str, Any] = {"model": "gpt-4o-mini-transcribe"}
    if _force_english():
        transcription["language"] = "en"
    return {
        "model": live_model(),
        "instructions": build_voice_instructions(locale=locale, timezone=timezone),
        "audio": {
            "output": {"voice": chosen},
            "input": {"transcription": transcription},
        },
        "delegation": {
            "type": "responses",
            "responses": {
                "model": live_backend_model(),
                "instructions": build_backend_instructions(
                    locale=locale, timezone=timezone
                ),
                "tools": tools_for_live(),
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            },
        },
    }


def build_minimal_live_session_config(voice: str | None = None) -> dict[str, Any]:
    """Fallback when OpenAI rejects the rich Live session."""
    return {
        "model": live_model(),
        "instructions": build_voice_instructions(),
        "audio": {"output": {"voice": resolve_realtime_voice(voice)}},
        "delegation": {
            "type": "responses",
            "responses": {
                "model": live_backend_model(),
                "instructions": build_backend_instructions(),
                "tools": tools_for_live(),
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            },
        },
    }


def validate_sdp_offer(sdp: str | None) -> str:
    raw = str(sdp or "")
    if len(raw) > MAX_SDP_CHARS:
        raise ValueError("SDP offer is too large")
    text = raw.strip()
    if not text or "v=" not in text:
        raise ValueError("An SDP offer is required")
    return text


def build_live_create_payload(
    sdp: str,
    *,
    voice: str | None = None,
    locale: str | None = None,
    timezone: str | None = None,
    minimal: bool = False,
) -> dict[str, Any]:
    session = (
        build_minimal_live_session_config(voice=voice)
        if minimal
        else build_live_session_config(voice=voice, locale=locale, timezone=timezone)
    )
    return {
        "session": session,
        "transport": {"type": "webrtc", "sdp": sdp},
    }


def parse_live_create_response(data: Any) -> dict[str, Any]:
    """Pull session id + SDP answer. Never treat a client_secret as success."""
    if not isinstance(data, dict):
        raise ValueError("Live session response was not an object")
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    transport = data.get("transport") if isinstance(data.get("transport"), dict) else {}
    session_id = str(session.get("id") or data.get("id") or "").strip()
    answer = str(transport.get("sdp") or data.get("sdp") or "").strip()
    if not answer:
        raise ValueError("No SDP answer in Live session response")
    return {
        "session_id": session_id,
        "sdp": answer,
        "transport_type": str(transport.get("type") or "webrtc"),
    }


def unwrap_live_event(event: Any) -> dict[str, Any]:
    """Unwrap ``response.event``; pass other events through.

    Nested Responses lifecycle events stay on ``event``. Preserve
    ``delegation_id`` so tool results can stay on the same backend turn.
    """
    if not isinstance(event, dict):
        return {}
    if event.get("type") == "response.event" and isinstance(event.get("event"), dict):
        inner = dict(event["event"])
        if event.get("delegation_id") is not None:
            inner["_delegation_id"] = event.get("delegation_id")
        if event.get("event_id") is not None:
            inner["_envelope_event_id"] = event.get("event_id")
        return inner
    return event


def parse_function_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def function_call_from_output_item(event: Any) -> dict[str, Any] | None:
    """Completed function call from nested ``response.output_item.done``."""
    if not isinstance(event, dict):
        return None
    if event.get("type") != "response.output_item.done":
        return None
    item = event.get("item")
    if not isinstance(item, dict):
        return None
    if item.get("type") not in {"function_call", "function_call_item"}:
        return None
    call_id = str(item.get("call_id") or item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not call_id or not name:
        return None
    return {
        "call_id": call_id,
        "name": name,
        "arguments": parse_function_arguments(item.get("arguments")),
        "delegation_id": event.get("_delegation_id"),
    }


def function_call_output_event(call_id: str, output: str) -> dict[str, Any]:
    """Browser/data-channel event that returns a tool result to Responses."""
    return {
        "type": "response.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": str(call_id),
            "output": str(output)[:12000],
        },
    }


def continue_response_event() -> dict[str, Any]:
    """Continue delegated Responses work after every required tool result."""
    return {"type": "response.create"}
