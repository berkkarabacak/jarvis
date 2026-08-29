#!/usr/bin/env python3
"""Mint cached first-hello clips with OpenAI TTS (marin).

Writes deploy/jarvis-public/hello/en.mp3 and tr.mp3. Uses OPENAI_API_KEY /
HOSTED_OPENAI_KEY when set, otherwise JARVIS_HOSTED_TALK_URL (defaults to the
public talk host). Never prints or writes a key.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.jarvis.talk_auth import DEFAULT_HOSTED_TALK_URL
from app.jarvis.tts import synthesize_speech

OUT = ROOT / "deploy" / "jarvis-public" / "hello"
CLIPS = (("en", "Hello."), ("tr", "Merhaba."))
VOICE = "marin"


def _looks_like_local_robot(data: bytes) -> bool:
    return b"Lavf" in data[:80] or len(data) < 10000


async def _mint() -> int:
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("HOSTED_OPENAI_KEY"):
        os.environ.setdefault("JARVIS_HOSTED_TALK_URL", DEFAULT_HOSTED_TALK_URL)
    OUT.mkdir(parents=True, exist_ok=True)
    for code, text in CLIPS:
        audio = await synthesize_speech(text, VOICE)
        if not audio or (audio[:1] != b"\xff" and audio[:3] != b"ID3"):
            print(f"failed to mint {code}", file=sys.stderr)
            return 1
        if _looks_like_local_robot(audio):
            print(f"refusing robot-sized {code} clip ({len(audio)} bytes)", file=sys.stderr)
            return 1
        dest = OUT / f"{code}.mp3"
        dest.write_bytes(audio)
        print(f"wrote {dest} ({len(audio)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_mint()))
