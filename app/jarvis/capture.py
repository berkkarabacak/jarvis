"""Screen capture with a near-black detector (ORCH-378 / ORCH-379).

Desktop BitBlt / ImageGrab / mss of the full desktop is often a solid black
frame when the laptop display is off or the session is remote. PrintWindow of
a real HWND with PW_RENDERFULLCONTENT often still has pixels.

ORCH-379: when the look has a preferred app/title/URL (see_screen goal or
the last run_app page), PrintWindow that HWND. Do not fall back to
GetForegroundWindow or the largest non-black window (Explorer / lock screen).
A black preferred Chrome frame is a failed look, not a desktop-icons shot.

Tests inject grabbers via set_capture_backend so they never touch the display.
"""

from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

log = logging.getLogger("jarvis.capture")

# A failed look must say this so the model does not invent headlines.
BLACK_FRAME_ERROR = (
    "Screenshot is a black frame — the capture produced no visible pixels "
    "(display off, locked, or remote session). Do not describe a website or "
    "invent headlines. The look failed."
)

# Pixel max(R,G,B) at or below this counts as dark.
_DARK_MAX = 8
# Flag the frame when this fraction of sampled pixels are dark.
_DARK_FRAC = 0.99
_SAMPLE = 64

# Test seam. When set, desktop/window grabbers replace OS capture.
_BACKEND: dict[str, Callable[..., Any]] | None = None

# Last successful run_app URL/app so a later see_screen can prefer that window.
_LAST_TARGET: dict[str, str] = {"app": "", "url": "", "title": ""}
# Last see_screen payload (title / vision / url). Click uses this to know
# whether the page is still a search-results page after a pixel click.
_LAST_LOOK: dict[str, Any] = {}
_SERP_CLICK_MISSES = 0

_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_HOST_RE = re.compile(r"\b(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.IGNORECASE)
_LOCK_OR_DESKTOP_PROC = frozenset({"explorer", "lockapp", "logonui", "dwm"})
_LOCK_OR_DESKTOP_TITLE = (
    "program manager",
    "windows default lock screen",
    "windows lock screen",
    "lock app",
)


def set_capture_backend(
    backend: dict[str, Callable[..., Any]] | None,
) -> None:
    """Replace OS screen grabbers (tests). Pass None to restore."""
    global _BACKEND
    _BACKEND = backend


def reset_look_target() -> None:
    remember_look_target(app="", url="", title="")
    reset_last_look()


def remember_last_look(looked: dict[str, Any] | None) -> None:
    """Store the last see_screen title/vision so click can test SERP-is-not-done."""
    global _LAST_LOOK, _SERP_CLICK_MISSES
    item = dict(looked or {})
    _LAST_LOOK = {
        "ok": item.get("ok"),
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "vision_description": str(item.get("vision_description") or ""),
        "error": str(item.get("error") or ""),
        "note": str(item.get("note") or ""),
        "vision_error": str(item.get("vision_error") or ""),
        "still_search": bool(item.get("still_search")),
    }
    try:
        from app.jarvis.serp import look_is_serp

        if not look_is_serp(_LAST_LOOK) and not _LAST_LOOK.get("still_search"):
            _SERP_CLICK_MISSES = 0
    except Exception:
        pass


def last_look() -> dict[str, Any]:
    return dict(_LAST_LOOK)


def reset_last_look() -> None:
    global _LAST_LOOK, _SERP_CLICK_MISSES
    _LAST_LOOK = {}
    _SERP_CLICK_MISSES = 0


def note_serp_click_miss() -> int:
    global _SERP_CLICK_MISSES
    _SERP_CLICK_MISSES += 1
    return _SERP_CLICK_MISSES


def serp_click_misses() -> int:
    return int(_SERP_CLICK_MISSES)


def reset_serp_click_misses() -> None:
    global _SERP_CLICK_MISSES
    _SERP_CLICK_MISSES = 0


def remember_look_target(*, app: str = "", url: str = "", title: str = "") -> None:
    """Record the page run_app just opened so see_screen can prefer that HWND."""
    _LAST_TARGET["app"] = str(app or "").strip()
    _LAST_TARGET["url"] = str(url or "").strip()
    _LAST_TARGET["title"] = str(title or "").strip()


def remember_tab_switch() -> None:
    """After keys Ctrl+Tab, keep preferring Chrome without wiping the last URL."""
    last = last_look_target()
    remember_look_target(
        app=last.get("app") or "chrome",
        url=last.get("url") or "",
        title=last.get("title") or "",
    )


def last_look_target() -> dict[str, str]:
    return dict(_LAST_TARGET)


def reset_capture_backend() -> None:
    set_capture_backend(None)
    reset_look_target()
    reset_last_look()


def _real_capture_allowed() -> bool:
    """Refuse live screen grabs while pytest is running unless explicitly on."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = (os.environ.get("JARVIS_ALLOW_REAL_CAPTURE") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}
    return True


def _as_image(source: Any) -> Any:
    """Load a PIL RGB-capable image from Image / PNG bytes / path."""
    if source is None:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, (bytes, bytearray, memoryview)):
        raw = bytes(source)
        if not raw:
            return None
        try:
            return Image.open(io.BytesIO(raw))
        except Exception:
            return None
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            return None
        try:
            return Image.open(path)
        except Exception:
            return None
    return None


def is_near_black(
    source: Any,
    *,
    dark_max: int = _DARK_MAX,
    dark_frac: float = _DARK_FRAC,
) -> bool:
    """True when almost every pixel is ~0 (a failed capture, not a real look)."""
    img = _as_image(source)
    if img is None:
        # Unreadable / missing bytes are not a detected black frame.
        return False
    try:
        rgb = img.convert("RGB")
    except Exception:
        return False
    width, height = rgb.size
    if width <= 0 or height <= 0:
        return False
    if width * height > _SAMPLE * _SAMPLE:
        rgb = rgb.resize((_SAMPLE, _SAMPLE))
    raw = rgb.tobytes()
    if not raw:
        return True
    # RGB triples; tobytes avoids Image.getdata (deprecated in Pillow 12).
    n = len(raw) // 3
    if n <= 0:
        return True
    dark = 0
    ceiling = int(dark_max)
    for i in range(0, n * 3, 3):
        if max(raw[i], raw[i + 1], raw[i + 2]) <= ceiling:
            dark += 1
    return (dark / n) >= float(dark_frac)


@dataclass
class CaptureResult:
    ok: bool
    image: Any = None
    method: str = ""
    error: str = ""
    black_frame: bool = False
    attempts: list[str] = field(default_factory=list)
    title: str = ""
    process: str = ""
    preferred: list[str] = field(default_factory=list)


def _host_of(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        if "://" not in raw:
            raw = "https://" + raw
        host = (urlsplit(raw).hostname or "").removeprefix("www.")
    except Exception:
        return ""
    return host


def _host_label(host: str) -> str:
    head = (host or "").split(".", 1)[0].strip().lower()
    if head in {"www", "com", "net", "org", "co", ""}:
        return ""
    return head


def preferred_needles(
    *,
    app: str = "",
    title: str = "",
    goal: str = "",
    include_last: bool = True,
) -> list[str]:
    """Needles for the HWND that matches the look (chrome / ntv.com.tr / NTV Haber)."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(text)

    add(app)
    add(title)
    last = last_look_target() if include_last else {}
    add(last.get("app") or "")
    add(last.get("title") or "")
    add(last.get("url") or "")

    blob = " ".join(
        x
        for x in (app, title, goal, last.get("url") or "", last.get("title") or "")
        if x
    )
    for match in _URL_RE.finditer(blob):
        add(match.group(0))
        host = _host_of(match.group(0))
        add(host)
        add(_host_label(host))
    for match in _HOST_RE.finditer(blob):
        host = (match.group(1) or "").removeprefix("www.")
        add(host)
        add(_host_label(host))
    low = blob.lower()
    if "google chrome" in low or re.search(r"\bchrome\b", low):
        add("chrome")
    if re.search(r"\b(msedge|edge)\b", low):
        add("msedge")
    if re.search(r"\bfirefox\b", low):
        add("firefox")
    if re.search(r"\bntv\b", low):
        add("ntv")
        add("NTV Haber")
    return found


def is_desktop_or_lock_window(title: str, process: str) -> bool:
    from app.jarvis.desktop import _norm_proc

    proc = _norm_proc(process)
    text = (title or "").strip().lower()
    if proc in _LOCK_OR_DESKTOP_PROC:
        return True
    return any(token in text for token in _LOCK_OR_DESKTOP_TITLE)


def look_has_http_url(
    *,
    app: str = "",
    title: str = "",
    goal: str = "",
    needles: list[str] | None = None,
    include_last: bool = True,
) -> bool:
    """True when this look is aimed at a real http(s) page, not a new tab."""
    last = last_look_target() if include_last else {}
    blob = " ".join(
        x
        for x in (
            app,
            title,
            goal,
            last.get("url") or "",
            *(needles or ()),
        )
        if x
    )
    return bool(_URL_RE.search(blob))


def _wait_for_non_placeholder(needles: list[str], *, timeout_s: float) -> bool:
    """Poll listed windows until a matching title is not about:blank / empty / Untitled."""
    from app.jarvis.desktop import is_placeholder_title

    if os.environ.get("PYTEST_CURRENT_TEST") and timeout_s > 0.5:
        # Tests inject titles; do not sleep the default live budget.
        timeout_s = min(float(timeout_s), 0.3)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        for hwnd, title, process in _list_windows():
            if not hwnd:
                continue
            if is_placeholder_title(title) and (
                _window_score(title, process, needles) > 0 or _is_browser_process(process)
            ):
                continue
            if _window_score(title, process, needles) > 0 and not is_placeholder_title(title):
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _skip_blank_hwnds(needles: list[str]) -> bool:
    """Skip about:blank when this look is aimed at a real page or Chrome."""
    if look_has_http_url(needles=needles, include_last=True):
        return True
    last = last_look_target()
    if _is_browser_process(last.get("app") or ""):
        return True
    for raw in needles or ():
        text = str(raw or "").strip().lower()
        if text in {"chrome", "msedge", "firefox", "google chrome"}:
            return True
        if _is_browser_process(text):
            return True
    return False


def _is_browser_process(process: str) -> bool:
    from app.jarvis.desktop import _norm_proc

    return _norm_proc(process) in {"chrome", "msedge", "firefox"}


def _call_backend(name: str, **kwargs: Any) -> Any:
    fn = (_BACKEND or {}).get(name)
    if fn is None:
        return None
    if not kwargs:
        return fn()
    try:
        return fn(**kwargs)
    except TypeError:
        return fn()


def _grab(name: str, **kwargs: Any) -> Any:
    if _BACKEND is not None:
        if name not in _BACKEND:
            return None
        return _call_backend(name, **kwargs)
    from app.jarvis.computer import JARVIS_ANDROID, JARVIS_COMPUTER, current_desktop_backend

    backend = current_desktop_backend()
    if backend == JARVIS_ANDROID and name == "desktop":
        from app.jarvis.android_computer import android_screenshot_image

        return android_screenshot_image()
    if backend == JARVIS_COMPUTER and name == "desktop":
        from app.jarvis.computer import screenshot_image

        return screenshot_image()
    if not _real_capture_allowed():
        return None
    if name == "desktop":
        return _os_grab_desktop()
    if name == "window":
        return _os_grab_window(**kwargs)
    return None


def _as_rgb(source: Any) -> Any:
    img = source
    try:
        from PIL import Image

        if not isinstance(img, Image.Image):
            img = _as_image(img)
    except Exception:
        img = _as_image(img)
    if img is None:
        return None
    try:
        return img.convert("RGB")
    except Exception:
        return None


def _result_from_image(
    img: Any,
    *,
    method: str,
    attempts: list[str],
    preferred: list[str],
    title: str = "",
    process: str = "",
) -> CaptureResult:
    rgb = _as_rgb(img)
    if rgb is None:
        attempts.append(f"{method}: unreadable")
        return CaptureResult(
            ok=False,
            black_frame=True,
            error=BLACK_FRAME_ERROR,
            method=method,
            attempts=attempts,
            title=title,
            process=process,
            preferred=list(preferred),
        )
    if is_near_black(rgb):
        attempts.append(f"{method}: black frame")
        return CaptureResult(
            ok=False,
            black_frame=True,
            error=BLACK_FRAME_ERROR,
            method=method,
            attempts=attempts,
            title=title,
            process=process,
            preferred=list(preferred),
        )
    return CaptureResult(
        ok=True,
        image=rgb,
        method=method,
        attempts=attempts,
        title=title,
        process=process,
        preferred=list(preferred),
    )


def _window_score(title: str, process: str, needles: list[str]) -> int:
    from app.jarvis.desktop import _window_matches

    score = 0
    for needle in needles:
        if not _window_matches(needle, title, process):
            continue
        score += 10
        n = (needle or "").strip()
        if n and n.lower() in (title or "").lower() and len(n) > 3:
            score += len(n)
    if is_desktop_or_lock_window(title, process):
        asked_desktop = any(
            (n or "").strip().lower().removesuffix(".exe") in {"explorer", "desktop"}
            for n in needles
        )
        if not asked_desktop:
            return -1
    return score


def _list_windows() -> list[tuple[int, str, str]]:
    if _BACKEND is not None:
        if "list_windows" not in _BACKEND:
            return []
        raw = _call_backend("list_windows")
        out: list[tuple[int, str, str]] = []
        for row in raw or []:
            if isinstance(row, dict):
                out.append(
                    (
                        int(row.get("hwnd") or 0),
                        str(row.get("title") or ""),
                        str(row.get("process") or ""),
                    )
                )
            elif isinstance(row, (tuple, list)) and len(row) >= 3:
                out.append((int(row[0]), str(row[1]), str(row[2])))
        return out
    from app.jarvis.computer import JARVIS_ANDROID, JARVIS_COMPUTER, current_desktop_backend

    backend = current_desktop_backend()
    if backend == JARVIS_ANDROID:
        from app.jarvis.android_computer import android_list_windows

        return android_list_windows()
    if backend == JARVIS_COMPUTER:
        from app.jarvis.computer import linux_list_windows

        return linux_list_windows()
    if not _real_capture_allowed():
        return []
    if sys.platform != "win32":
        return []
    return _win_list_visible_windows()


def _print_hwnd(hwnd: int) -> Any:
    if _BACKEND is not None:
        fn = _BACKEND.get("print_window")
        if fn is None:
            return None
        try:
            return fn(hwnd=int(hwnd))
        except TypeError:
            return fn(int(hwnd))
    if not _real_capture_allowed():
        return None
    return _win_print_window(int(hwnd))


def _capture_preferred(needles: list[str], *, waited: bool = False) -> CaptureResult:
    """PrintWindow the matching HWND only. Never substitute Explorer / lock screen."""
    attempts: list[str] = [f"preferred:{','.join(needles)}"]
    use_listed = _BACKEND is None or "list_windows" in (_BACKEND or {})
    if _BACKEND is not None and "window" in _BACKEND and not use_listed:
        try:
            img = _call_backend(
                "window",
                app=needles[0] if needles else "",
                title="",
                needles=needles,
            )
        except Exception as exc:
            attempts.append(f"window: {exc}")
            img = None
        if img is not None:
            return _result_from_image(
                img, method="window", attempts=attempts, preferred=needles
            )
        attempts.append("window: no image")

    from app.jarvis.desktop import BLANK_PAGE_ERROR, is_placeholder_title

    skip_blank = _skip_blank_hwnds(needles)
    ranked: list[tuple[int, int, str, str]] = []
    blank_seen = ""
    blank_process = ""
    for hwnd, title, process in _list_windows():
        if not hwnd:
            continue
        score = _window_score(title, process, needles)
        blank_browser = (
            skip_blank
            and is_placeholder_title(title)
            and (score > 0 or _is_browser_process(process))
        )
        if blank_browser:
            blank_seen = title or "about:blank"
            blank_process = process
            attempts.append(f"window {title!r}: about:blank / not a loaded page")
            continue
        if score <= 0:
            continue
        ranked.append((score, hwnd, title, process))
    ranked.sort(reverse=True)
    if not ranked:
        if skip_blank and blank_seen:
            if not waited and _wait_for_non_placeholder(needles, timeout_s=3.0):
                return _capture_preferred(needles, waited=True)
            return CaptureResult(
                ok=False,
                black_frame=False,
                error=BLANK_PAGE_ERROR,
                attempts=attempts,
                title=blank_seen,
                process=blank_process,
                preferred=list(needles),
            )
        return CaptureResult(
            ok=False,
            black_frame=False,
            error=(
                "no visible window matching "
                + "/".join(needles)
                + " — not substituting the desktop or lock screen. "
                "Do not invent headlines."
            ),
            attempts=attempts,
            preferred=list(needles),
        )

    last_black = False
    last_title = ""
    last_process = ""
    for _score, hwnd, title, process in ranked:
        try:
            img = _print_hwnd(hwnd)
        except Exception as exc:
            attempts.append(f"window {title!r}: {exc}")
            continue
        if img is None:
            attempts.append(f"window {title!r}: no image")
            continue
        rgb = _as_rgb(img)
        if rgb is None:
            attempts.append(f"window {title!r}: unreadable")
            continue
        if is_near_black(rgb):
            last_black = True
            last_title = title
            last_process = process
            attempts.append(f"window {title!r}: black frame")
            continue
        return CaptureResult(
            ok=True,
            image=rgb,
            method="window",
            attempts=attempts,
            title=title,
            process=process,
            preferred=list(needles),
        )
    return CaptureResult(
        ok=False,
        black_frame=last_black or True,
        error=BLACK_FRAME_ERROR,
        method="window",
        attempts=attempts,
        title=last_title,
        process=last_process,
        preferred=list(needles),
    )


def _chrome_title_from_list() -> tuple[str, str]:
    """Best Chrome title on this look — real page first, else Restore / any."""
    from app.jarvis.desktop import is_dismissible_chrome_dialog, is_placeholder_title

    rows = _list_windows()
    chrome: list[tuple[int, str, str]] = []
    for hwnd, title, process in rows:
        blob = f"{title} {process}".lower()
        # linux_list_windows sets process "x11". Match Chrome by title,
        # and Restore/Translate dialogs even when the process name is blank.
        if "chrome" in blob or "chromium" in blob:
            chrome.append((hwnd, title, process))
        elif title and is_dismissible_chrome_dialog(title):
            chrome.append((hwnd, title, process))
    if not chrome:
        return "", ""
    real = [r for r in chrome if r[1] and not is_placeholder_title(r[1])]
    if real:
        return real[0][1], real[0][2]
    dialog = [r for r in chrome if is_dismissible_chrome_dialog(r[1])]
    if dialog:
        return dialog[0][1], dialog[0][2]
    return chrome[0][1], chrome[0][2]


def capture_screen(
    *,
    app: str = "",
    title: str = "",
    goal: str = "",
    prefer_last: bool = False,
) -> CaptureResult:
    """Grab the screen. A page look prints the preferred HWND, not the desktop."""
    include_last = prefer_last or bool(str(app or "").strip() or str(title or "").strip() or str(goal or "").strip())
    needles = preferred_needles(
        app=app, title=title, goal=goal, include_last=include_last
    )
    from app.jarvis.computer import JARVIS_ANDROID, JARVIS_COMPUTER, current_desktop_backend

    backend = current_desktop_backend()
    # ORCH-461: Android box is one framebuffer. Grab screencap. Never Linux.
    if backend == JARVIS_ANDROID:
        attempts: list[str] = ["jarvis-android:screencap"]
        img = _grab("desktop")
        if img is None:
            return CaptureResult(
                ok=False,
                black_frame=True,
                error=BLACK_FRAME_ERROR,
                method="jarvis-android",
                attempts=attempts + ["desktop: no image"],
                preferred=list(needles),
            )
        return _result_from_image(
            img,
            method="jarvis-android",
            attempts=attempts,
            preferred=list(needles),
            title="Android",
            process="android",
        )
    # ORCH-405: Jarvis's machine is one Xvfb display. Grab DISPLAY=:1.
    # Do not PrintWindow a Windows HWND.
    if backend == JARVIS_COMPUTER:
        attempts: list[str] = ["jarvis-computer:DISPLAY=:1"]
        img = _grab("desktop")
        if img is None:
            return CaptureResult(
                ok=False,
                black_frame=True,
                error=BLACK_FRAME_ERROR,
                method="jarvis-computer",
                attempts=attempts + ["desktop: no image"],
                preferred=list(needles),
            )
        chrome_title, chrome_proc = _chrome_title_from_list()
        return _result_from_image(
            img,
            method="jarvis-computer",
            attempts=attempts,
            preferred=list(needles),
            title=chrome_title,
            process=chrome_proc,
        )
    if needles:
        return _capture_preferred(needles)

    attempts: list[str] = []
    last_black = False
    for method in ("desktop", "window"):
        try:
            img = _grab(method)
        except Exception as exc:
            attempts.append(f"{method}: {exc}")
            log.warning("capture %s failed: %s", method, exc)
            continue
        if img is None:
            attempts.append(f"{method}: no image")
            continue
        rgb = _as_rgb(img)
        if rgb is None:
            attempts.append(f"{method}: unreadable")
            continue
        if is_near_black(rgb):
            last_black = True
            attempts.append(f"{method}: black frame")
            continue
        return CaptureResult(ok=True, image=rgb, method=method, attempts=attempts)
    return CaptureResult(
        ok=False,
        black_frame=last_black or True,
        error=BLACK_FRAME_ERROR,
        attempts=attempts,
    )


def _os_grab_desktop() -> Any:
    from app.jarvis.computer import JARVIS_ANDROID, JARVIS_COMPUTER, current_desktop_backend

    backend = current_desktop_backend()
    if backend == JARVIS_ANDROID:
        from app.jarvis.android_computer import android_screenshot_image

        return android_screenshot_image()
    if backend == JARVIS_COMPUTER:
        from app.jarvis.computer import screenshot_image

        return screenshot_image()
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab()
        if img is not None:
            return img
    except Exception as exc:
        log.warning("ImageGrab.grab failed: %s", exc)
    if sys.platform == "win32":
        return _powershell_copy_from_screen()
    return None


def _powershell_copy_from_screen() -> Any:
    """Last-resort BitBlt via PowerShell. Often black in the same cases as ImageGrab."""
    tmp = None
    try:
        from PIL import Image

        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        escaped = tmp.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
            f"$bmp.Save('{escaped}'); "
            "$g.Dispose(); $bmp.Dispose()"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0 or not os.path.isfile(tmp):
            return None
        img = Image.open(tmp)
        return img.copy()
    except Exception as exc:
        log.warning("PowerShell CopyFromScreen failed: %s", exc)
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _os_grab_window(
    *,
    app: str = "",
    title: str = "",
    needles: list[str] | None = None,
) -> Any:
    if sys.platform != "win32":
        return None
    from app.jarvis.desktop import is_placeholder_title

    preferred = [n for n in list(needles or []) + [app, title] if str(n or "").strip()]
    if preferred:
        skip_blank = _skip_blank_hwnds(preferred)
        last = None
        for hwnd, win_title, process in _win_list_visible_windows():
            score = _window_score(win_title, process, preferred)
            if skip_blank and is_placeholder_title(win_title) and (
                score > 0 or _is_browser_process(process)
            ):
                continue
            if score <= 0:
                continue
            img = _win_print_window(hwnd)
            if img is None:
                continue
            if not is_near_black(img):
                return img
            last = img
        return last
    last = None
    for hwnd in _win_candidate_hwnds():
        img = _win_print_window(hwnd)
        if img is None:
            continue
        if not is_near_black(img):
            return img
        last = img
    return last


def _win_list_visible_windows() -> list[tuple[int, str, str]]:
    """Visible titled top-level windows as (hwnd, title, process)."""
    import ctypes
    from ctypes import wintypes

    from app.jarvis.desktop import _process_image_stem

    user32 = ctypes.windll.user32
    found: list[tuple[int, str, str]] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @WNDENUMPROC
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        win_title = buf.value or ""
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = _process_image_stem(int(pid.value))
        found.append((int(hwnd), win_title, process))
        return True

    user32.EnumWindows(_enum, 0)
    return found


def _win_candidate_hwnds() -> list[int]:
    """Foreground first, then the largest visible titled top-level windows."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    seen: set[int] = set()
    ordered: list[int] = []

    fg = int(user32.GetForegroundWindow() or 0)
    if fg:
        seen.add(fg)
        ordered.append(fg)

    sized: list[tuple[int, int]] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @WNDENUMPROC
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length <= 0:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 64 or height < 64:
            return True
        sized.append((width * height, int(hwnd)))
        return True

    user32.EnumWindows(_enum, 0)
    sized.sort(reverse=True)
    for _area, hwnd in sized:
        if hwnd not in seen:
            seen.add(hwnd)
            ordered.append(hwnd)
        if len(ordered) >= 6:
            break
    return ordered


def _win_print_window(hwnd: int) -> Any:
    """PrintWindow(hwnd, PW_RENDERFULLCONTENT) → PIL Image, or None."""
    import ctypes
    from ctypes import wintypes

    try:
        from PIL import Image
    except Exception:
        return None

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    PW_RENDERFULLCONTENT = 0x00000002

    rect = wintypes.RECT()
    if not user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 8 or height < 8:
        return None

    hwnd_dc = user32.GetWindowDC(int(hwnd))
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)
    try:
        painted = user32.PrintWindow(int(hwnd), mem_dc, PW_RENDERFULLCONTENT)
        if not painted:
            painted = user32.PrintWindow(int(hwnd), mem_dc, 0)
        if not painted:
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [
                ("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3),
            ]

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        buf = ctypes.create_string_buffer(width * height * 4)
        got = gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), 0)
        if not got:
            return None
        img = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)
        return img.copy()
    except Exception as exc:
        log.warning("PrintWindow failed hwnd=%s: %s", hwnd, exc)
        return None
    finally:
        try:
            gdi32.SelectObject(mem_dc, old)
        except Exception:
            pass
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(int(hwnd), hwnd_dc)
