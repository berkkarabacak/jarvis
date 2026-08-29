"""Public family Jarvis page: talk and type in the browser.

Talk is the site root. Old /jarvis/... bookmarks 301 to the same path
without the prefix.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
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


def _redirect_off_jarvis_prefix(path: str, request: Request | None = None) -> RedirectResponse:
    """301 /jarvis and /jarvis/foo to / and /foo."""
    raw = (path or "").strip()
    if raw in {"/jarvis", "/jarvis/"}:
        dest = "/"
    elif raw.startswith("/jarvis/"):
        dest = raw[len("/jarvis") :]
        if not dest.startswith("/"):
            dest = "/" + dest
    else:
        dest = "/"
    if request is not None and request.url.query:
        dest = dest + ("&" if "?" in dest else "?") + request.url.query
    return RedirectResponse(url=dest, status_code=301)


async def _talk_page() -> FileResponse:
    if not PUBLIC_HTML.is_file():
        raise HTTPException(status_code=404, detail="Jarvis page missing")
    return FileResponse(PUBLIC_HTML, media_type="text/html; charset=utf-8")


async def _voice_orb_js() -> FileResponse:
    if not VOICE_ORB_JS.is_file():
        raise HTTPException(status_code=404, detail="Voice orb missing")
    return FileResponse(
        VOICE_ORB_JS,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def _hello_clip(code: str) -> FileResponse:
    path = hello_clip_path(code)
    if path is None:
        raise HTTPException(status_code=404, detail="Hello clip missing")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


async def _screen_page() -> FileResponse:
    if not SCREEN_HTML.is_file():
        raise HTTPException(status_code=404, detail="Jarvis screen missing")
    return FileResponse(SCREEN_HTML, media_type="text/html; charset=utf-8")


async def _setup_exe() -> FileResponse:
    path = setup_exe_path()
    if path is None:
        raise HTTPException(status_code=404, detail="Download not on this host")
    return FileResponse(
        path,
        filename=DOWNLOAD_NAME,
        media_type="application/octet-stream",
    )


async def _screen_status() -> dict:
    from app.jarvis.screen_viewer import screen_status

    return screen_status()


async def _screen_start() -> dict:
    from app.jarvis.screen_viewer import start_computer

    return start_computer()


async def _screen_png() -> Response:
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


@router.get("/", response_class=HTMLResponse)
async def talk_home() -> FileResponse:
    return await _talk_page()


@router.get("/voice-orb.js")
async def talk_voice_orb_js() -> FileResponse:
    return await _voice_orb_js()


@router.get("/hello/{code}.mp3")
async def talk_hello_clip(code: str) -> FileResponse:
    return await _hello_clip(code)


@router.get("/screen", response_class=HTMLResponse)
async def talk_screen() -> FileResponse:
    return await _screen_page()


@router.get("/download/Jarvis-Setup.exe")
async def talk_setup_exe() -> FileResponse:
    return await _setup_exe()


@router.get("/api/jarvis/computer/screen")
async def talk_screen_status() -> dict:
    return await _screen_status()


@router.post("/api/jarvis/computer/screen/start")
async def talk_screen_start() -> dict:
    return await _screen_start()


@router.get("/api/jarvis/screen.png")
async def talk_screen_png() -> Response:
    return await _screen_png()


@router.get("/jarvis")
async def jarvis_public_redirect(request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix("/jarvis", request)


@router.get("/jarvis/", response_class=HTMLResponse)
async def jarvis_public_page(request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix("/jarvis/", request)


@router.get("/jarvis/voice-orb.js")
async def jarvis_voice_orb_js(request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix("/jarvis/voice-orb.js", request)


@router.get("/jarvis/hello/{code}.mp3")
async def jarvis_hello_clip(code: str, request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix(f"/jarvis/hello/{code}.mp3", request)


@router.get("/jarvis/screen", response_class=HTMLResponse)
async def jarvis_public_screen(request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix("/jarvis/screen", request)


@router.get("/jarvis/api/jarvis/computer/screen")
async def jarvis_public_screen_status() -> dict:
    return await _screen_status()


@router.post("/jarvis/api/jarvis/computer/screen/start")
async def jarvis_public_screen_start() -> dict:
    return await _screen_start()


@router.get("/jarvis/api/jarvis/screen.png")
async def jarvis_public_screen_png() -> Response:
    return await _screen_png()


@router.get("/jarvis/download/Jarvis-Setup.exe")
async def jarvis_setup_exe(request: Request) -> RedirectResponse:
    return _redirect_off_jarvis_prefix("/jarvis/download/Jarvis-Setup.exe", request)
