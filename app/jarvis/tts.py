"""Neural HTTP TTS for Jarvis speak-back. Never uses OS / SAPI / speechSynthesis.

OpenAI Realtime already speaks via WebRTC. This module is the OpenRouter-only
(and Realtime-off) path: OpenAI ``audio/speech`` when ``OPENAI_API_KEY`` is
set, otherwise OpenRouter ``/api/v1/audio/speech`` with a published model id.
If neither provider can synthesize, callers stay silent and show text.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.jarvis.realtime import (
    openai_api_key,
    openrouter_api_key,
    realtime_available,
    resolve_realtime_voice,
)
from app.jarvis.talk_auth import hosted_talk_endpoint, should_use_hosted_talk
from app.llm.openrouter import OPENROUTER_BASE
from app.llm.openrouter_attribution import (
    OPENROUTER_APP_TITLE as OPENROUTER_TITLE,
    OPENROUTER_APP_URL as OPENROUTER_SITE,
    openrouter_attribution_headers,
)

log = logging.getLogger("jarvis.tts")

# Official OpenAI Audio Speech model (supports Realtime voice ids including marin).
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"

# Published OpenRouter speech model — do not invent slugs.
# Docs: https://openrouter.ai/docs/guides/overview/multimodal/tts
# Create-speech example: https://openrouter.ai/docs/api/api-reference/tts/create-speech
# Live Models API (output_modalities=speech) lists this id; it does not list
# openai/gpt-4o-mini-tts-2025-12-15.
OPENROUTER_TTS_URL = f"{OPENROUTER_BASE}/audio/speech"
OPENROUTER_TTS_MODEL = "mistralai/voxtral-mini-tts-2603"
# Create-speech API example voice for Voxtral. OpenAI Realtime ids (marin, coral)
# are not in this model's supported_voices list.
OPENROUTER_TTS_VOICE = "en_paul_neutral"
OPENROUTER_TTS_VOICES = frozenset(
    {
        "en_paul_angry",
        "en_paul_cheerful",
        "en_paul_confident",
        "en_paul_excited",
        "en_paul_frustrated",
        "en_paul_happy",
        "en_paul_neutral",
        "en_paul_sad",
        "fr_marie_angry",
        "fr_marie_curious",
        "fr_marie_excited",
        "fr_marie_happy",
        "fr_marie_neutral",
        "fr_marie_sad",
        "gb_jane_confused",
        "gb_jane_confident",
        "gb_jane_curious",
        "gb_jane_frustrated",
        "gb_jane_jealousy",
        "gb_jane_neutral",
        "gb_jane_sad",
        "gb_jane_sarcasm",
        "gb_jane_shameful",
        "gb_oliver_angry",
        "gb_oliver_cheerful",
        "gb_oliver_confident",
        "gb_oliver_curious",
        "gb_oliver_excited",
        "gb_oliver_neutral",
        "gb_oliver_sad",
    }
)


_MAX_INPUT = 2000


def speak_mode() -> str:
    """How Jarvis can produce voice, if at all.

    ``openai_realtime`` — WebRTC output only for replies.
    ``openai_tts`` — HTTP OpenAI audio/speech (Realtime flag off, key present).
    ``openrouter_tts`` — HTTP OpenRouter audio/speech.
    ``none`` — no neural path; stay silent.
    """
    if realtime_available():
        return "openai_realtime"
    if openai_api_key():
        return "openai_tts"
    if openrouter_api_key():
        return "openrouter_tts"
    if should_use_hosted_talk():
        return "hosted_tts"
    return "none"


def can_speak() -> bool:
    return speak_mode() != "none"


def neural_tts_available() -> bool:
    """True when an HTTP neural TTS provider or hosted talk path exists (not OS TTS)."""
    return bool(openai_api_key() or openrouter_api_key() or should_use_hosted_talk())


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()[:_MAX_INPUT]


async def _post_speech(
    url: str, headers: dict[str, str], payload: dict[str, Any]
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=45.0) as client:
        return await client.post(url, headers=headers, json=payload)


async def _openai_speech(text: str, voice: str) -> bytes | None:
    key = openai_api_key()
    if not key:
        return None
    res = await _post_speech(
        OPENAI_TTS_URL,
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        {
            "model": OPENAI_TTS_MODEL,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        },
    )
    if res.status_code >= 400 or not res.content:
        log.warning("openai tts failed %s: %s", res.status_code, res.text[:240])
        return None
    return res.content


def _openrouter_voice(voice: str) -> str:
    """Use a published Voxtral voice. Realtime ids like marin are not in that set."""
    chosen = (voice or "").strip()
    if chosen in OPENROUTER_TTS_VOICES:
        return chosen
    return OPENROUTER_TTS_VOICE


async def _openrouter_speech(text: str, voice: str) -> bytes | None:
    key = openrouter_api_key()
    if not key:
        return None
    res = await _post_speech(
        OPENROUTER_TTS_URL,
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            **openrouter_attribution_headers(),
        },
        {
            "model": OPENROUTER_TTS_MODEL,
            "input": text,
            "voice": _openrouter_voice(voice),
            "response_format": "mp3",
        },
    )
    if res.status_code >= 400 or not res.content:
        log.warning("openrouter tts failed %s: %s", res.status_code, res.text[:240])
        return None
    return res.content


async def _hosted_speech(text: str, voice: str) -> bytes | None:
    url = hosted_talk_endpoint("speak")
    if not url:
        return None
    res = await _post_speech(
        url,
        {"Content-Type": "application/json"},
        {"text": text, "voice": voice},
    )
    if res.status_code >= 400 or not res.content:
        log.warning("hosted tts failed %s: %s", res.status_code, (res.text or "")[:240])
        return None
    return res.content


async def synthesize_speech(text: str, voice: str | None = None) -> bytes | None:
    """Return MP3 bytes, or None when no neural TTS can run.

    Voice is ``resolve_realtime_voice`` (stored settings → env → marin).
    Never invents a Scottish / unofficial slug.
    """
    clean = _clean_text(text)
    if not clean:
        return None
    chosen = resolve_realtime_voice(voice)
    if openai_api_key():
        return await _openai_speech(clean, chosen)
    if openrouter_api_key():
        return await _openrouter_speech(clean, chosen)
    if should_use_hosted_talk():
        return await _hosted_speech(clean, chosen)
    return None
