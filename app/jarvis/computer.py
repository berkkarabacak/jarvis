"""Jarvis's computer backends (ORCH-405 / ORCH-461).

When a job targets Jarvis's machine, look / click / type / keys / scroll /
focus_app / run_app talk to the selected box:

* Linux (default) — existing ``jarvis-computer`` container (DISPLAY=:1)
  via ``docker exec`` + xdotool / scrot.
* Android — ``jarvis-android`` via ``docker exec`` + Android toolbox.
  Not the Play Store phone app under ``android/``.

They do not touch the user's Windows session (ORCH-365) and they do not
spawn extra containers. Children inherit the parent's desktop backend.

Live I/O is docker exec. Tests inject ``set_computer_exec`` /
``set_android_exec`` so pytest never needs a running desktop.
"""

from __future__ import annotations

import contextvars
import os
import re
import sys
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.jarvis.android_computer import JARVIS_ANDROID
from app.jarvis.virtual_pc import (
    goal_is_computer_job,
    goal_is_virtual_pc_job,
    hosted_linux_talk,
    host_is_windows,
)

WINDOWS = "windows"
JARVIS_COMPUTER = "jarvis-computer"
JARVIS_BOXES = frozenset({JARVIS_COMPUTER, JARVIS_ANDROID})
CONTAINER_NAME = "jarvis-computer"
DISPLAY = ":1"
CONTAINER_USER = "jarvis"
DESKTOP_DIR = "/home/jarvis/Desktop"
EXPORTS_DIR = "/home/jarvis/Exports"

# One computer. Helpers only exec into this name. Never docker run / compose up.
_FORBIDDEN_SPAWN = (
    "docker run",
    "docker compose up",
    "docker-compose up",
    "podman run",
)

_JARVIS_ALIASES = frozenset(
    {
        "jarvis",
        "jarvis-computer",
        "jarvis_computer",
        "linux",
        "his",
        "own",
        "container",
    }
)
_WINDOWS_ALIASES = frozenset(
    {
        "windows",
        "win32",
        "user",
        "pc",
        "laptop",
        "user-pc",
        "user_windows",
    }
)
_ANDROID_ALIASES = frozenset(
    {
        "android",
        "jarvis-android",
        "jarvis_android",
        "redroid",
    }
)

_JARVIS_GOAL = re.compile(
    r"\b("
    r"your (?:own )?(?:linux )?(?:computer|desktop|machine|box|screen)|"
    r"jarvis(?:['’]s)? (?:own )?(?:linux )?(?:computer|desktop|machine|box)|"
    r"the (?:linux|jarvis) (?:computer|desktop|machine)|"
    r"the browser|"
    r"on (?:the )?jarvis-computer"
    r")\b",
    re.I,
)
_ANDROID_GOAL = re.compile(
    r"\b("
    r"your (?:own )?android|"
    r"jarvis(?:['’]s)? (?:own )?android|"
    r"the android (?:computer|desktop|machine|box)|"
    r"android (?:computer|desktop|machine|box)|"
    r"on (?:the )?jarvis-android"
    r")\b",
    re.I,
)
_WINDOWS_GOAL = re.compile(
    r"\b("
    r"my (?:windows )?(?:pc|computer|laptop|screen|desktop|machine)|"
    r"this windows|"
    r"the user(?:['’]s)? windows|"
    r"user(?:['’]s)? (?:windows )?(?:pc|computer|laptop|screen)|"
    r"on my (?:pc|screen|windows)"
    r")\b",
    re.I,
)
_HOST_DISK_GOAL = re.compile(
    r"\b("
    r"free space|disk space|disk free|storage left|how much space|storage free"
    r")\b",
    re.I,
)
_LINUX_DESKTOP_ACT = re.compile(
    r"\b(click|type|close|scroll|press|dismiss|see_screen|screenshot|"
    r"notepad|chrome|"
    r"look at|what.?s on|what do you see|what are you seeing|visible on|"
    r"the browser|the tabs?|this tab|popup|"
    r"gmail|inbox|ibox|mail)\b",
    re.I,
)

_XDOTOOL_NAMED = {
    "tab": "Tab",
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "home": "Home",
    "end": "End",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "pgup": "Page_Up",
    "pgdn": "Page_Down",
    "prior": "Page_Up",
    "next": "Page_Down",
}

_LINUX_APPS = {
    "chrome": ["/usr/local/bin/chrome"],
    "chromium": ["chromium"],
    "notepad": ["mousepad"],
    "notepad++": ["mousepad"],
    "notepadpp": ["mousepad"],
    "mousepad": ["mousepad"],
    "editor": ["mousepad"],
    "text-editor": ["mousepad"],
    "texteditor": ["mousepad"],
    "files": ["thunar"],
    "thunar": ["thunar"],
    "explorer": ["thunar"],
    "terminal": ["xfce4-terminal"],
    "xfce4-terminal": ["xfce4-terminal"],
    "calc": ["galculator"],
    "calculator": ["galculator"],
    "galculator": ["galculator"],
    "image-viewer": ["ristretto"],
    "ristretto": ["ristretto"],
}

# Spoken names → apt package / binary already on the Linux VM image.
# Unknown words are not invented; talk lists these instead of docker/exec.
_APT_ALIASES = {
    "mines": "gnome-mines",
    "minesweeper": "gnome-mines",
    "mine": "gnome-mines",
    "game": "gnome-mines",
    "games": "gnome-mines",
    "solitaire": "aisleriot",
    "klondike": "aisleriot",
    "patience": "aisleriot",
    "cards": "aisleriot",
    "calculator": "galculator",
    "calc": "galculator",
    "galculator": "galculator",
    "editor": "mousepad",
    "text-editor": "mousepad",
    "texteditor": "mousepad",
    "notepad": "mousepad",
    "mousepad": "mousepad",
}
LISTED_LINUX_APPS = (
    "mines",
    "solitaire",
    "calculator",
    "text editor",
)

_SAFE_PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+-]*$")

# Test seam. When set, docker exec is replaced (pytest never talks to Docker).
_EXEC: Callable[..., dict[str, Any]] | None = None
_current_backend: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_desktop_backend", default=None
)
# Skip a second focus_app docker exec after one already failed this job.
_FOCUS_FAIL: dict[str, float] = {}
_FOCUS_FAIL_SKIP_S = 30.0
_FOCUS_EXEC_TIMEOUT_S = 4.0

# Close every Chrome/Chromium window in one exec. Prefer wmctrl / xdotool
# windowclose over killing the display. pkill chrome is the leftover fallback
# (this image launches Chromium via /usr/local/bin/chrome).
CLOSE_CHROME_SH = (
    "set +e; "
    "if command -v wmctrl >/dev/null 2>&1; then "
    "wmctrl -c Chromium; wmctrl -c Chrome; wmctrl -c chromium; "
    "wmctrl -c Mousepad; wmctrl -c Galculator; wmctrl -c mousepad; "
    "wmctrl -c galculator; wmctrl -c gedit; wmctrl -c Leafpad; "
    "wmctrl -c Ristretto; wmctrl -c 'Image Viewer'; wmctrl -c eog; "
    "wmctrl -c Thunar; wmctrl -c thunar; wmctrl -c Files; wmctrl -c Nautilus; "
    "wmctrl -c Nemo; wmctrl -c 'File Manager'; wmctrl -c Explorer; "
    "wmctrl -c Error; wmctrl -c 'Error'; "
    "wmctrl -l 2>/dev/null | awk 'BEGIN{IGNORECASE=1} "
    "/chrome|chromium|mousepad|galculator|gedit|leafpad|ristretto|eog|image viewer|"
    "thunar|nautilus|nemo|file manager|explorer|^error | error$/ {print $1}' | "
    "while read -r id; do [ -n \"$id\" ] && wmctrl -ic \"$id\"; done; "
    "fi; "
    "xdotool search --onlyvisible --class Chromium windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class chromium windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class google-chrome windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Chromium windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Chrome windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class mousepad windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class galculator windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class ristretto windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class eog windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class Thunar windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class thunar windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class Nautilus windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class nautilus windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class Nemo windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --class nemo windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Mousepad windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Galculator windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Ristretto windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name 'Image Viewer' windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Thunar windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Files windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name 'File Manager' windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Nautilus windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Nemo windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Explorer windowclose 2>/dev/null; "
    "xdotool search --onlyvisible --name Error windowclose 2>/dev/null; "
    "pkill -x chromium 2>/dev/null; "
    "pkill -x chrome 2>/dev/null; "
    "pkill -x mousepad 2>/dev/null; "
    "pkill -x galculator 2>/dev/null; "
    "pkill -x gedit 2>/dev/null; "
    "pkill -x leafpad 2>/dev/null; "
    "pkill -x ristretto 2>/dev/null; "
    "pkill -x eog 2>/dev/null; "
    "pkill -x thunar 2>/dev/null; "
    "pkill -x nautilus 2>/dev/null; "
    "pkill -x nemo 2>/dev/null; "
    "true"
)


def set_computer_exec(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Replace docker exec (tests). Pass None to restore."""
    global _EXEC
    _EXEC = fn


def _focus_fail_key(app: str) -> str:
    return str(app or "").strip().lower()


def note_focus_fail(app: str) -> None:
    _FOCUS_FAIL[_focus_fail_key(app)] = time.monotonic()


def recent_focus_fail(app: str) -> bool:
    stamp = _FOCUS_FAIL.get(_focus_fail_key(app))
    if stamp is None:
        return False
    return (time.monotonic() - stamp) < _FOCUS_FAIL_SKIP_S


def reset_computer_state() -> None:
    """Clear test seams and the job desktop binding."""
    global _EXEC
    _EXEC = None
    _FOCUS_FAIL.clear()
    _current_backend.set(None)
    try:
        from app.jarvis.android_computer import reset_android_state

        reset_android_state()
    except Exception:
        pass


def current_desktop_backend() -> str | None:
    return _current_backend.get()


def bind_desktop_backend(backend: str | None) -> contextvars.Token[str | None]:
    """Pin this job/child to one machine. Children call this with the parent value."""
    return _current_backend.set(normalize_computer(backend) or backend or None)


def reset_desktop_backend(token: contextvars.Token[str | None]) -> None:
    _current_backend.reset(token)


def normalize_computer(value: str | None) -> str | None:
    raw = (value or "").strip().lower().replace(" ", "-")
    if not raw:
        return None
    if raw in _ANDROID_ALIASES:
        return JARVIS_ANDROID
    if raw in _JARVIS_ALIASES:
        return JARVIS_COMPUTER
    if raw in _WINDOWS_ALIASES:
        return WINDOWS
    return None


def goal_targets_android_computer(goal: str) -> bool:
    return bool(_ANDROID_GOAL.search(goal or ""))


def selected_jarvis_box(env: dict[str, str] | None = None) -> str:
    """Which of Jarvis's boxes Settings picked. Default Linux."""
    try:
        from app.jarvis.settings_store import get_computer_kind

        kind = get_computer_kind(env=env)
    except Exception:
        kind = "linux"
    if kind == "android":
        return JARVIS_ANDROID
    return JARVIS_COMPUTER


def is_jarvis_box(backend: str | None) -> bool:
    return backend in JARVIS_BOXES


def goal_targets_jarvis_computer(goal: str) -> bool:
    return bool(_JARVIS_GOAL.search(goal or ""))


def goal_targets_user_windows(goal: str) -> bool:
    return bool(_WINDOWS_GOAL.search(goal or ""))


def goal_asks_host_disk(goal: str) -> bool:
    """True when the user wants host free space, not a Linux-desktop look."""
    return bool(_HOST_DISK_GOAL.search(goal or ""))


def goal_needs_linux_desktop(goal: str) -> bool:
    return bool(_LINUX_DESKTOP_ACT.search(goal or ""))


def resolve_desktop_backend(
    *,
    goal: str = "",
    computer: str = "",
    inherit: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Pick windows (ORCH-365), jarvis-computer (ORCH-405), or android (ORCH-461).

    Order: explicit computer= → env JARVIS_DESKTOP_BACKEND → inherited
    job/child backend → goal text → Settings computer_kind for Jarvis's
    own box → windows (user PC path stays the default for unspecified jobs).

    Default start for Jarvis's box is Linux. Android is opt-in.
    """
    explicit = normalize_computer(computer)
    if explicit:
        return explicit
    environ = env if env is not None else os.environ
    env_val = normalize_computer(str(environ.get("JARVIS_DESKTOP_BACKEND") or ""))
    if env_val:
        return env_val
    inherited = normalize_computer(inherit) or (
        inherit if inherit in {WINDOWS, JARVIS_COMPUTER, JARVIS_ANDROID} else None
    )
    if inherited:
        return inherited
    if goal_targets_user_windows(goal):
        return WINDOWS
    if goal_asks_host_disk(goal) and not goal_needs_linux_desktop(goal):
        return WINDOWS
    if goal_targets_android_computer(goal):
        return JARVIS_ANDROID
    if goal_targets_jarvis_computer(goal):
        return selected_jarvis_box(environ)
    # Public / hosted talk: computer and look jobs use Jarvis's selected box
    # (Linux by default). Real win32 keeps the user PC.
    look_job = goal_is_virtual_pc_job(goal) or goal_is_computer_job(goal)
    if look_job and hosted_linux_talk(environ):
        return selected_jarvis_box(environ)
    if look_job and not host_is_windows(environ):
        return selected_jarvis_box(environ)
    return WINDOWS


def bind_job_desktop(*, goal: str = "", computer: str = "") -> str:
    """Re-resolve from a fresh user utterance. Does not inherit the last job."""
    backend = resolve_desktop_backend(goal=goal, computer=computer, inherit=None)
    _current_backend.set(backend)
    return backend


def activate_desktop_backend(*, goal: str = "", computer: str = "") -> str:
    """Backend for this tool call. Explicit computer= wins; else the job pin."""
    explicit = normalize_computer(computer)
    if explicit:
        _current_backend.set(explicit)
        return explicit
    current = _current_backend.get()
    if current in {WINDOWS, JARVIS_COMPUTER, JARVIS_ANDROID}:
        return current
    backend = resolve_desktop_backend(goal=goal, computer=computer, inherit=current)
    _current_backend.set(backend)
    return backend


def uses_jarvis_computer(*, goal: str = "", computer: str = "") -> bool:
    return activate_desktop_backend(goal=goal, computer=computer) == JARVIS_COMPUTER


def uses_jarvis_android(*, goal: str = "", computer: str = "") -> bool:
    return activate_desktop_backend(goal=goal, computer=computer) == JARVIS_ANDROID


def uses_jarvis_box(*, goal: str = "", computer: str = "") -> bool:
    return activate_desktop_backend(goal=goal, computer=computer) in JARVIS_BOXES


def docker_exec_argv(
    inner: list[str],
    *,
    user: str = CONTAINER_USER,
    display: str = DISPLAY,
    detach: bool = False,
) -> list[str]:
    """Host argv that execs into the one jarvis-computer container."""
    cmd = ["docker", "exec"]
    if detach:
        cmd.append("-d")
    cmd.extend(["-u", user, "-e", f"DISPLAY={display}", CONTAINER_NAME])
    cmd.extend(inner)
    return cmd


def _real_computer_allowed() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = (os.environ.get("JARVIS_ALLOW_REAL_COMPUTER") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}
    return True


def exec_in_computer(
    inner: list[str],
    *,
    user: str = CONTAINER_USER,
    display: str = DISPLAY,
    detach: bool = False,
    timeout: float = 20,
    binary: bool = False,
) -> dict[str, Any]:
    """Run a command on Jarvis's one computer. Never docker run / compose up."""
    argv = docker_exec_argv(inner, user=user, display=display, detach=detach)
    joined = " ".join(argv).lower()
    for banned in _FORBIDDEN_SPAWN:
        if banned in joined:
            return {
                "ok": False,
                "error": "refusing to spawn another computer",
                "argv": argv,
            }
    if _EXEC is not None:
        try:
            raw = _EXEC(
                inner,
                user=user,
                display=display,
                detach=detach,
                argv=argv,
                binary=binary,
            )
        except TypeError:
            raw = _EXEC(inner)
        if isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("argv", argv)
            out.setdefault("computer", JARVIS_COMPUTER)
            return out
        return {
            "ok": True,
            "stdout": raw if isinstance(raw, (bytes, str)) else "",
            "argv": argv,
            "computer": JARVIS_COMPUTER,
        }
    if not _real_computer_allowed():
        return {
            "ok": False,
            "error": "live jarvis-computer exec is off during tests",
            "argv": argv,
            "computer": JARVIS_COMPUTER,
        }
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            timeout=max(1.0, float(timeout)),
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "docker is not installed; start jarvis-computer with docker compose up",
            "argv": argv,
            "computer": JARVIS_COMPUTER,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "jarvis-computer exec timed out",
            "argv": argv,
            "computer": JARVIS_COMPUTER,
        }
    stdout: Any = completed.stdout if binary else (completed.stdout or b"").decode(
        "utf-8", errors="replace"
    )
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if completed.returncode != 0:
        err = (stderr or str(stdout) or "docker exec failed").strip()[:400]
        if "no such container" in err.lower():
            err = (
                "jarvis-computer is not running. "
                "Start the one existing container with docker compose up "
                "(do not create a second computer)."
            )
        return {
            "ok": False,
            "error": err,
            "exit_code": completed.returncode,
            "argv": argv,
            "computer": JARVIS_COMPUTER,
        }
    return {
        "ok": True,
        "stdout": stdout,
        "stderr": stderr[-2000:],
        "exit_code": 0,
        "argv": argv,
        "computer": JARVIS_COMPUTER,
    }


def screenshot_inner_argv() -> list[str]:
    """Grab DISPLAY=:1 to stdout as PNG. One container, no extra ports."""
    return [
        "sh",
        "-c",
        "scrot -o /tmp/jarvis-screen.png && cat /tmp/jarvis-screen.png",
    ]


def screenshot_png() -> dict[str, Any]:
    backend = _current_backend.get()
    if backend == JARVIS_ANDROID or (
        backend is None and selected_jarvis_box() == JARVIS_ANDROID
    ):
        from app.jarvis.android_computer import android_screenshot_png

        return android_screenshot_png()
    result = exec_in_computer(screenshot_inner_argv(), binary=True)
    if not result.get("ok"):
        return result
    raw = result.get("stdout") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", errors="replace")
    if not raw:
        return {
            "ok": False,
            "error": "jarvis-computer screenshot was empty",
            "computer": JARVIS_COMPUTER,
            "argv": result.get("argv"),
        }
    out = dict(result)
    out["png"] = bytes(raw)
    out["bytes"] = len(raw)
    out["display"] = DISPLAY
    return out


def public_computer_status() -> dict[str, Any]:
    """Safe health/Talk payload: which box is selected and whether it is live."""
    kind = "linux"
    try:
        from app.jarvis.settings_store import get_computer_kind

        kind = get_computer_kind()
    except Exception:
        kind = "linux"
    if kind not in {"linux", "android"}:
        kind = "linux"
    backend = JARVIS_ANDROID if kind == "android" else JARVIS_COMPUTER
    label = "Android" if kind == "android" else "Linux"
    container = JARVIS_ANDROID if kind == "android" else CONTAINER_NAME
    watch_path = "/jarvis/android/" if kind == "android" else "/jarvis/novnc/"
    live = False
    watch_url = ""
    try:
        from app.jarvis.screen_viewer import screen_status

        status = screen_status()
        live = bool(status.get("running"))
        watch_url = str(status.get("session_url") or status.get("url") or "")
        if status.get("container"):
            container = str(status.get("container"))
        if status.get("watch_path"):
            watch_path = str(status.get("watch_path"))
    except Exception:
        live = False
    return {
        "kind": kind,
        "label": label,
        "backend": backend,
        "container": container,
        "live": live,
        "watch_path": watch_path,
        "watch_url": watch_url,
        "play_store_client": False,
        "note": (
            "Android is a phone-shaped box Jarvis can tap. "
            "It is not the phone app in the store."
            if kind == "android"
            else "Linux is the usual desktop."
        ),
    }


def screenshot_image() -> Any:
    """PIL image of the selected box, or None."""
    grabbed = screenshot_png()
    if not grabbed.get("ok"):
        return None
    try:
        from PIL import Image
        import io

        return Image.open(io.BytesIO(grabbed["png"]))
    except Exception:
        return None


def click_inner_argv(*, x: int, y: int, button: str = "left") -> list[str]:
    btn = "3" if (button or "left").strip().lower() == "right" else "1"
    return ["xdotool", "mousemove", "--", str(int(x)), str(int(y)), "click", btn]


def linux_click(*, x: int, y: int, button: str = "left") -> dict[str, Any]:
    result = exec_in_computer(click_inner_argv(x=x, y=y, button=button))
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "x": int(x),
        "y": int(y),
        "button": button,
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
    }


def type_inner_argv(*, text: str) -> list[str]:
    return ["xdotool", "type", "--clearmodifiers", "--", str(text)]


def linux_type(*, text: str) -> dict[str, Any]:
    raw = str(text or "")
    result = exec_in_computer(type_inner_argv(text=raw))
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "typed": len(raw),
        "chars": len(raw),
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
    }


def xdotool_key_name(token: str) -> str | None:
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in {"ctrl", "control"}:
        return "ctrl"
    if t == "shift":
        return "shift"
    if t == "alt":
        return "alt"
    if t in {"win", "windows", "meta", "super"}:
        return "super"
    if t in _XDOTOOL_NAMED:
        return _XDOTOOL_NAMED[t]
    if len(t) == 1 and ("a" <= t <= "z" or "0" <= t <= "9"):
        return t
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 12:
            return f"F{n}"
    return None


def keys_inner_argv(*, combo: str) -> list[str]:
    from app.jarvis.desktop import parse_hotkey

    parsed = parse_hotkey(combo)
    if not parsed.get("ok"):
        return []
    parts = [*(parsed.get("modifiers") or []), str(parsed.get("key") or "")]
    names = [xdotool_key_name(p) for p in parts if p]
    if not names or any(n is None for n in names):
        return []
    return ["xdotool", "key", "--clearmodifiers", "+".join(names)]


def linux_keys(
    *,
    combo: str,
    events: list[tuple[int, int]] | None = None,
    vk: list[int] | None = None,
    modifiers: list[str] | None = None,
    key: str = "",
) -> dict[str, Any]:
    inner = keys_inner_argv(combo=combo)
    if not inner:
        return {"ok": False, "error": "unknown key combo", "combo": combo}
    result = exec_in_computer(inner)
    if not result.get("ok"):
        out = dict(result)
        out["combo"] = combo
        return out
    return {
        "ok": True,
        "combo": combo,
        "vk": list(vk or []),
        "modifiers": list(modifiers or []),
        "key": key,
        "events": list(events or []),
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
    }


def scroll_inner_argv(
    *,
    dx: int = 0,
    dy: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> list[str]:
    parts: list[str] = ["xdotool"]
    if x is not None and y is not None:
        parts.extend(["mousemove", "--", str(int(x)), str(int(y))])
    repeats: list[tuple[str, int]] = []
    if dy:
        repeats.append(("4" if int(dy) > 0 else "5", abs(int(dy))))
    if dx:
        repeats.append(("7" if int(dx) > 0 else "6", abs(int(dx))))
    if not repeats:
        return []
    for btn, n in repeats:
        parts.extend(["click", "--repeat", str(n), btn])
    return parts


def linux_scroll(
    *,
    dx: int = 0,
    dy: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, Any]:
    inner = scroll_inner_argv(dx=dx, dy=dy, x=x, y=y)
    if not inner:
        return {"ok": False, "error": "scroll needs dx or dy"}
    result = exec_in_computer(inner)
    if not result.get("ok"):
        return result
    out: dict[str, Any] = {
        "ok": True,
        "dx": int(dx),
        "dy": int(dy),
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
    }
    if x is not None and y is not None:
        out["x"] = int(x)
        out["y"] = int(y)
    return out


def focus_inner_argv(*, app: str) -> list[str]:
    needle = str(app or "").strip()
    lowered = needle.lower()
    if lowered in {"galculator", "calculator", "calc"}:
        # Title is often "Calculator"; leftover Mousepad stays focused
        # unless we raise the galculator class.
        return [
            "sh",
            "-c",
            (
                "xdotool search --onlyvisible --class galculator "
                "windowactivate --sync 2>/dev/null "
                "|| xdotool search --onlyvisible --name Calculator "
                "windowactivate --sync 2>/dev/null "
                "|| xdotool search --onlyvisible --name galculator "
                "windowactivate --sync"
            ),
        ]
    return [
        "xdotool",
        "search",
        "--onlyvisible",
        "--name",
        needle,
        "windowactivate",
        "--sync",
    ]


def linux_focus_app(*, app: str) -> dict[str, Any]:
    needle = str(app or "").strip()
    if recent_focus_fail(needle):
        return {
            "ok": False,
            "error": (
                f"focus_app already failed for {needle!r}; "
                "not retrying docker exec"
            ),
            "app": needle,
            "focused": False,
            "skipped": True,
            "computer": JARVIS_COMPUTER,
        }
    result = exec_in_computer(
        focus_inner_argv(app=needle),
        timeout=_FOCUS_EXEC_TIMEOUT_S,
    )
    if not result.get("ok"):
        err = str(result.get("error") or "")
        low = err.lower()
        result = dict(result)
        if (
            not err
            or "docker exec failed" in low
            or low in {"failed", "docker exec failed"}
            or "no such" in low
        ):
            result["error"] = (
                f"no visible window matching {needle!r} on jarvis-computer"
            )
        result["app"] = needle
        result["focused"] = False
        note_focus_fail(needle)
        return result
    return {
        "ok": True,
        "app": needle,
        "focused": True,
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
        "raise": "xdotool",
    }


def close_chrome_inner_argv() -> list[str]:
    """One exec: close every Chrome/Chromium window on DISPLAY=:1."""
    return ["sh", "-c", CLOSE_CHROME_SH]


def linux_close_chrome_windows(*, app: str = "chrome") -> dict[str, Any]:
    """Close Chrome, file managers, error dialogs, editors, and image viewers."""
    result = exec_in_computer(close_chrome_inner_argv(), timeout=6.0)
    out = dict(result) if isinstance(result, dict) else {"ok": False}
    out.setdefault("ok", False)
    out["app"] = str(app or "chrome")
    out["closed"] = "chrome"
    out["method"] = "close-all"
    out["computer"] = JARVIS_COMPUTER
    if out.get("ok"):
        out["error"] = ""
    return out


def list_windows_inner_argv() -> list[str]:
    return [
        "sh",
        "-c",
        "xdotool search --onlyvisible --name '.*' 2>/dev/null | while read -r id; do "
        "printf '%s\\t%s\\n' \"$id\" \"$(xdotool getwindowname \"$id\" 2>/dev/null)\"; "
        "done",
    ]


def linux_list_windows() -> list[tuple[int, str, str]]:
    result = exec_in_computer(list_windows_inner_argv())
    if not result.get("ok"):
        return []
    rows: list[tuple[int, str, str]] = []
    stdout = result.get("stdout") or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    for line in str(stdout).splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            hid, title = line.split("\t", 1)
        else:
            parts = line.split(None, 1)
            if not parts:
                continue
            hid = parts[0]
            title = parts[1] if len(parts) > 1 else ""
        try:
            hwnd = int(str(hid).strip())
        except ValueError:
            continue
        rows.append((hwnd, title.strip(), "x11"))
    return rows


def linux_has_visible_window(*, app: str) -> bool:
    needle = str(app or "").strip().lower()
    if not needle:
        return False
    for _hwnd, title, process in linux_list_windows():
        blob = f"{title} {process}".lower()
        if needle in blob:
            return True
        if needle in {"chrome", "chromium"} and (
            "chrome" in blob or "chromium" in blob
        ):
            return True
        if needle in {"notepad", "mousepad"} and (
            "notepad" in blob or "mousepad" in blob
        ):
            return True
    return False


def is_local_file_url(url: str) -> bool:
    """True for file:///abs/path. Rejects file://exports/… (hostname-shaped)."""
    raw = (url or "").strip()
    if not raw.lower().startswith("file:"):
        return False
    try:
        parts = urlparse(raw)
    except Exception:
        return False
    if (parts.scheme or "").lower() != "file":
        return False
    if parts.netloc and parts.netloc.lower() not in {"", "localhost"}:
        return False
    path = parts.path or ""
    return path.startswith("/")


def computer_html_file_url(name: str) -> str:
    """file:///home/jarvis/Exports/<safe>.html — never a bare Exports/ host."""
    safe = Path(str(name or "").replace("\\", "/")).name
    if not re.match(r"^[\w.-]+\.html?$", safe, re.I):
        safe = "page.html"
    return Path(f"{EXPORTS_DIR}/{safe}").as_uri()


def stage_file_on_computer(host_path: str, dest_abs: str) -> dict[str, Any]:
    """Copy a host file into jarvis-computer. Best-effort; Chrome uses dest URL."""
    dest = str(dest_abs or "").strip()
    src = Path(str(host_path or ""))
    if not dest.startswith("/") or not src.is_file():
        return {"ok": False, "error": "missing host file or dest"}
    mkdir = exec_in_computer(["mkdir", "-p", str(Path(dest).parent)])
    if _EXEC is not None:
        return {"ok": True, "dest": dest, "staged": True, "argv": mkdir.get("argv")}
    if not _real_computer_allowed():
        return {
            "ok": False,
            "error": "live jarvis-computer exec is off during tests",
            "dest": dest,
        }
    try:
        completed = subprocess.run(
            ["docker", "cp", str(src), f"{CONTAINER_NAME}:{dest}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "dest": dest}
    if completed.returncode != 0:
        err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()[:400]
        return {"ok": False, "error": err or "docker cp failed", "dest": dest}
    return {"ok": True, "dest": dest, "staged": True}


def plan_linux_run_app(args: dict[str, Any] | None) -> dict[str, Any]:
    """Map run_app args onto binaries that already ship in jarvis-computer."""
    args = args or {}
    target = str(args.get("target") or "").strip()
    extra = str(args.get("args") or "").strip()
    url = str(args.get("url") or "").strip()
    lowered = target.lower()
    if lowered.startswith("http://") or lowered.startswith("https://") or is_local_file_url(lowered):
        url = target
        target = "chrome"
    if url and not (
        url.startswith("http://")
        or url.startswith("https://")
        or is_local_file_url(url)
    ):
        return {"ok": False, "error": "url must be http://, https://, or file:///"}
    key = (target or ("chrome" if url else "")).strip().lower().replace("\\", "/")
    key = key.split("/")[-1].removesuffix(".exe")
    if "chrome" in key or key == "chromium":
        key = "chrome"
    if "notepad" in key:
        key = "notepad"
    if url and key not in _LINUX_APPS:
        key = "chrome"
    argv = list(_LINUX_APPS.get(key) or [])
    if not argv:
        return {"ok": False, "error": f"unknown app on jarvis-computer: {target or key}"}
    if extra:
        argv.append(extra)
    if url:
        argv.append(url)
    return {
        "ok": True,
        "kind": "url" if url else "app",
        "app": argv[0],
        "url": url,
        "argv": argv,
        "cmd": " ".join(argv),
        "computer": JARVIS_COMPUTER,
    }


def _linux_chrome_title_is_blank() -> bool:
    """True when Chromium is still about:blank / Untitled / empty."""
    try:
        from app.jarvis.desktop import is_placeholder_title
    except Exception:
        return False
    for _hwnd, title, process in linux_list_windows():
        blob = f"{title} {process}".lower()
        if "chrome" not in blob and "chromium" not in blob:
            continue
        if is_placeholder_title(title):
            return True
    return False


def linux_run_app(plan: dict[str, Any]) -> dict[str, Any]:
    argv = list(plan.get("argv") or [])
    if not argv:
        return {"ok": False, "error": "empty launch", "computer": JARVIS_COMPUTER}
    result = exec_in_computer(argv, detach=True)
    if not result.get("ok"):
        return result
    out: dict[str, Any] = {
        "ok": True,
        "started": plan.get("cmd") or " ".join(argv),
        "argv": argv,
        "computer": JARVIS_COMPUTER,
        "window": True,
    }
    if plan.get("url"):
        out["opened"] = plan["url"]
        out["page_ready"] = True
        # about:blank after open: wait, launch the same URL once more.
        # Tests mock this function; skip the pause under pytest.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            time.sleep(0.8)
            if _linux_chrome_title_is_blank():
                again = exec_in_computer(argv, detach=True)
                if again.get("ok"):
                    time.sleep(0.8)
                    out["retried"] = True
    return out


def map_apt_package(word: str) -> str:
    raw = (word or "").strip().lower()
    if not raw:
        return ""
    return _APT_ALIASES.get(raw, raw)


def is_listed_linux_package(word: str) -> bool:
    """True for a packaged app we will actually install. Never a random apt guess."""
    raw = (word or "").strip().lower()
    if not raw:
        return False
    mapped = _APT_ALIASES.get(raw, raw)
    return mapped in set(_APT_ALIASES.values())


def desktop_file_path(name: str) -> str:
    base = (name or "").strip().lstrip("/").replace("\\", "/")
    base = base.split("/")[-1]
    return f"{DESKTOP_DIR}/{base}"


def linux_install_package(pkg: str) -> dict[str, Any]:
    """apt-get install -y in the ONE existing jarvis-computer. Never docker run."""
    name = map_apt_package(pkg)
    if not name or not _SAFE_PKG_RE.match(name):
        return {"ok": False, "error": f"bad package name: {pkg or name}"}
    result = exec_in_computer(
        ["apt-get", "install", "-y", name],
        user="root",
        timeout=180,
    )
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "installed": name,
        "computer": JARVIS_COMPUTER,
        "argv": result.get("argv"),
    }


def children_do_not_spawn_computers() -> bool:
    """Product rule: one Jarvis computer. Documented for contract tests."""
    return True
