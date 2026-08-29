"""Public family Jarvis page: talk and type in the browser."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

REPO = Path(__file__).resolve().parents[2]
PUBLIC_HTML = REPO / "deploy" / "jarvis-public" / "index.html"
SCREEN_HTML = REPO / "deploy" / "jarvis-public" / "screen.html"
VOICE_ORB_JS = REPO / "deploy" / "jarvis-public" / "voice-orb.js"
# Optional static OpenAI TTS clips. Public Talk first hello is live gpt-realtime
# audio on the RTC track, not these files and not POST /api/jarvis/speak.
# Regen: scripts/mint_hello_clips.py
HELLO_DIR = REPO / "deploy" / "jarvis-public" / "hello"
HELLO_CLIPS = {
    "en": HELLO_DIR / "en.mp3",
    "tr": HELLO_DIR / "tr.mp3",
}
DOWNLOAD_NAME = "Jarvis-Setup.exe"


def hello_clip_path(code: str) -> Path | None:
    path = HELLO_CLIPS.get((code or "").strip().lower())
    if path is None or not path.is_file():
        return None
    return path

router = APIRouter(tags=["jarvis-public"])


def setup_exe_path() -> Path | None:
    env = (os.environ.get("JARVIS_SETUP_EXE_PATH") or "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            REPO / "deploy" / "jarvis-public" / "download" / DOWNLOAD_NAME,
            Path("/var/www/jarvis/download") / DOWNLOAD_NAME,
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


@router.get("/jarvis")
async def jarvis_public_redirect() -> RedirectResponse:
    return RedirectResponse(url="/jarvis/", status_code=307)


@router.get("/jarvis/", response_class=HTMLResponse)
async def jarvis_public_page() -> FileResponse:
    if not PUBLIC_HTML.is_file():
        raise HTTPException(status_code=404, detail="Jarvis page missing")
    return FileResponse(PUBLIC_HTML, media_type="text/html; charset=utf-8")


@router.get("/jarvis/voice-orb.js")
async def jarvis_voice_orb_js() -> FileResponse:
    if not VOICE_ORB_JS.is_file():
        raise HTTPException(status_code=404, detail="Voice orb missing")
    return FileResponse(
        VOICE_ORB_JS,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/jarvis/hello/{code}.mp3")
async def jarvis_hello_clip(code: str) -> FileResponse:
    path = hello_clip_path(code)
    if path is None:
        raise HTTPException(status_code=404, detail="Hello clip missing")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/jarvis/screen", response_class=HTMLResponse)
async def jarvis_public_screen() -> FileResponse:
    if not SCREEN_HTML.is_file():
        raise HTTPException(status_code=404, detail="Jarvis screen missing")
    return FileResponse(SCREEN_HTML, media_type="text/html; charset=utf-8")


@router.get("/jarvis/api/jarvis/computer/screen")
async def jarvis_public_screen_status() -> dict:
    from app.jarvis.screen_viewer import screen_status

    return screen_status()


@router.post("/jarvis/api/jarvis/computer/screen/start")
async def jarvis_public_screen_start() -> dict:
    from app.jarvis.screen_viewer import start_computer

    return start_computer()


@router.get("/jarvis/api/jarvis/screen.png")
async def jarvis_public_screen_png() -> Response:
    from app.jarvis.computer import screenshot_png

    grabbed = screenshot_png()
    if not grabbed.get("ok"):
        raise HTTPException(
            status_code=503,
            detail="Jarvis's computer is not running.",
        )
    raw = grabbed.get("png") or b""
    if not raw:
        raise HTTPException(
            status_code=503,
            detail="Jarvis's computer is not running.",
        )
    return Response(
        content=bytes(raw),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/jarvis/download/Jarvis-Setup.exe")
async def jarvis_setup_exe() -> FileResponse:
    path = setup_exe_path()
    if path is None:
        raise HTTPException(status_code=404, detail="Download not on this host")
    return FileResponse(
        path,
        filename=DOWNLOAD_NAME,
        media_type="application/octet-stream",
    )
