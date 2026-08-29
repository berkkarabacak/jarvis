"""HTTP for the ORCH-410 on-demand Jarvis screen viewer."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.jarvis.screen_viewer import screen_status, start_computer

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
VIEWER_HTML = STATIC_DIR / "jarvis-screen.html"

router = APIRouter(tags=["jarvis-screen"])


def _peer_host(request: Request) -> str:
    try:
        return (request.client.host if request.client else "") or ""
    except Exception:
        return ""


def _is_loopback(request: Request) -> bool:
    peer = _peer_host(request)
    return (not peer) or peer in {
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
        "test",
    }


def _require_local_start(request: Request) -> None:
    """Start is localhost-only. The desktop itself is bound to 127.0.0.1."""
    if _is_loopback(request):
        return
    raise HTTPException(
        status_code=403,
        detail="Jarvis's screen is localhost only. Open it from the Windows app or this machine.",
    )


@router.get("/ceo/jarvis-screen", response_class=HTMLResponse)
async def jarvis_screen_page() -> FileResponse:
    if not VIEWER_HTML.is_file():
        raise HTTPException(status_code=404, detail="Jarvis's screen is missing")
    return FileResponse(VIEWER_HTML, media_type="text/html; charset=utf-8")


@router.get("/api/jarvis/computer/screen")
async def jarvis_screen_status() -> dict:
    return screen_status()


@router.post("/api/jarvis/computer/screen/start")
async def jarvis_screen_start(request: Request) -> dict:
    _require_local_start(request)
    return start_computer()
