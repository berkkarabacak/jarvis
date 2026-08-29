"""Jarvis's Android computer backend (ORCH-461).

A second machine class — not the Play Store phone app under ``android/``.
Same Jarvis, same memory, different box. Look / tap / type / open talk to
the existing ``jarvis-android`` container via ``docker exec`` of Android
toolbox (``screencap``, ``input``, ``am``). They never exec into
``jarvis-computer``.

Live I/O is docker exec. Tests inject ``set_android_exec`` so pytest never
needs a running phone.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

JARVIS_ANDROID = "jarvis-android"
ANDROID_CONTAINER = "jarvis-android"
WATCH_HOST = "127.0.0.1"
WATCH_PORT = 6081
WATCH_URL = f"http://{WATCH_HOST}:{WATCH_PORT}"
WATCH_PATH = "/android/"

# One Android box. Helpers only exec into this name. Never docker run / compose up.
# Never the Linux desktop container.
_FORBIDDEN = (
    "docker run",
    "docker compose up",
    "docker-compose up",
    "podman run",
    "jarvis-computer",
)

_SAFE_PKG_RE = re.compile(r"^[A-Za-z0-9._]+$")

# Spoken names → package or VIEW intent already on a stock Android image.
_ANDROID_APPS = {
    "chrome": "com.android.chrome",
    "chromium": "com.android.chrome",
    "browser": "com.android.browser",
    "settings": "com.android.settings",
    "files": "com.android.documentsui",
    "documents": "com.android.documentsui",
    "camera": "com.android.camera",
    "photos": "com.android.gallery3d",
    "gallery": "com.android.gallery3d",
    "clock": "com.android.deskclock",
    "calculator": "com.android.calculator2",
    "calc": "com.android.calculator2",
}

_KEYCODES = {
    "enter": "KEYCODE_ENTER",
    "return": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "esc": "KEYCODE_BACK",
    "escape": "KEYCODE_BACK",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "space": "KEYCODE_SPACE",
    "backspace": "KEYCODE_DEL",
    "delete": "KEYCODE_FORWARD_DEL",
    "del": "KEYCODE_FORWARD_DEL",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
}

# Test seam. When set, docker exec is replaced (pytest never talks to Docker).
_EXEC: Callable[..., dict[str, Any]] | None = None


def set_android_exec(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Replace docker exec (tests). Pass None to restore."""
    global _EXEC
    _EXEC = fn


def reset_android_state() -> None:
    global _EXEC
    _EXEC = None


def docker_exec_argv(
    inner: list[str],
    *,
    detach: bool = False,
) -> list[str]:
    """Host argv that execs into the one jarvis-android container."""
    cmd = ["docker", "exec"]
    if detach:
        cmd.append("-d")
    cmd.append(ANDROID_CONTAINER)
    cmd.extend(inner)
    return cmd


def _real_android_allowed() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = (os.environ.get("JARVIS_ALLOW_REAL_COMPUTER") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}
    return True


def exec_in_android(
    inner: list[str],
    *,
    detach: bool = False,
    timeout: float = 20,
    binary: bool = False,
) -> dict[str, Any]:
    """Run a command on Jarvis's Android box. Never docker run. Never Linux."""
    argv = docker_exec_argv(inner, detach=detach)
    joined = " ".join(argv).lower()
    for banned in _FORBIDDEN:
        if banned in joined:
            return {
                "ok": False,
                "error": "refusing to touch the Linux computer or spawn another box",
                "argv": argv,
                "computer": JARVIS_ANDROID,
            }
    if ANDROID_CONTAINER not in argv:
        return {
            "ok": False,
            "error": "android exec must name jarvis-android",
            "argv": argv,
            "computer": JARVIS_ANDROID,
        }
    if _EXEC is not None:
        try:
            raw = _EXEC(
                inner,
                detach=detach,
                argv=argv,
                binary=binary,
            )
        except TypeError:
            raw = _EXEC(inner)
        if isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("argv", argv)
            out["computer"] = JARVIS_ANDROID
            return out
        return {
            "ok": True,
            "stdout": raw if isinstance(raw, (bytes, str)) else "",
            "argv": argv,
            "computer": JARVIS_ANDROID,
        }
    if not _real_android_allowed():
        return {
            "ok": False,
            "error": "live jarvis-android exec is off during tests",
            "argv": argv,
            "computer": JARVIS_ANDROID,
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
            "error": "docker is not installed; start jarvis-android with docker compose up",
            "argv": argv,
            "computer": JARVIS_ANDROID,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "jarvis-android exec timed out",
            "argv": argv,
            "computer": JARVIS_ANDROID,
        }
    stdout: Any = completed.stdout if binary else (completed.stdout or b"").decode(
        "utf-8", errors="replace"
    )
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if completed.returncode != 0:
        err = (stderr or str(stdout) or "docker exec failed").strip()[:400]
        if "no such container" in err.lower():
            err = (
                "jarvis-android is not running. "
                "Start the Android computer with docker compose up "
                "(do not use the Linux jarvis-computer box)."
            )
        return {
            "ok": False,
            "error": err,
            "exit_code": completed.returncode,
            "argv": argv,
            "computer": JARVIS_ANDROID,
        }
    return {
        "ok": True,
        "stdout": stdout,
        "stderr": stderr[-2000:],
        "exit_code": 0,
        "argv": argv,
        "computer": JARVIS_ANDROID,
    }


def screenshot_inner_argv() -> list[str]:
    """PNG of the Android framebuffer to stdout. One container, no extra ports."""
    return ["screencap", "-p"]


def android_screenshot_png() -> dict[str, Any]:
    result = exec_in_android(screenshot_inner_argv(), binary=True)
    if not result.get("ok"):
        return result
    raw = result.get("stdout") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", errors="replace")
    if not raw:
        return {
            "ok": False,
            "error": "jarvis-android screenshot was empty",
            "computer": JARVIS_ANDROID,
            "argv": result.get("argv"),
        }
    out = dict(result)
    out["png"] = bytes(raw)
    out["bytes"] = len(raw)
    out["display"] = "android"
    return out


def android_screenshot_image() -> Any:
    grabbed = android_screenshot_png()
    if not grabbed.get("ok"):
        return None
    try:
        from PIL import Image
        import io

        return Image.open(io.BytesIO(grabbed["png"]))
    except Exception:
        return None


def tap_inner_argv(*, x: int, y: int) -> list[str]:
    return ["input", "tap", str(int(x)), str(int(y))]


def android_click(*, x: int, y: int, button: str = "left") -> dict[str, Any]:
    del button  # Android tap is one finger. Right-click is not a thing here.
    result = exec_in_android(tap_inner_argv(x=x, y=y))
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "x": int(x),
        "y": int(y),
        "button": "tap",
        "computer": JARVIS_ANDROID,
        "argv": result.get("argv"),
    }


def _adb_type_text(text: str) -> str:
    """Android ``input text`` uses %s for space. No newlines."""
    raw = str(text or "").replace("\r", " ").replace("\n", " ")
    return raw.replace(" ", "%s")


def type_inner_argv(*, text: str) -> list[str]:
    return ["input", "text", _adb_type_text(text)]


def android_type(*, text: str) -> dict[str, Any]:
    raw = str(text or "")
    result = exec_in_android(type_inner_argv(text=raw))
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "typed": len(raw),
        "chars": len(raw),
        "computer": JARVIS_ANDROID,
        "argv": result.get("argv"),
    }


def keyevent_name(token: str) -> str | None:
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in _KEYCODES:
        return _KEYCODES[t]
    if len(t) == 1 and "a" <= t <= "z":
        return f"KEYCODE_{t.upper()}"
    if t.isdigit() and len(t) == 1:
        return f"KEYCODE_{t}"
    return None


def keys_inner_argv(*, combo: str) -> list[str]:
    parts = [p.strip() for p in str(combo or "").replace("+", " ").split() if p.strip()]
    if not parts:
        return []
    # One key at a time. Android input keyevent does not take ctrl+ combos well.
    code = keyevent_name(parts[-1])
    if not code:
        return []
    return ["input", "keyevent", code]


def android_keys(
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
    result = exec_in_android(inner)
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
        "computer": JARVIS_ANDROID,
        "argv": result.get("argv"),
    }


def swipe_inner_argv(
    *,
    dx: int = 0,
    dy: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> list[str]:
    x0 = 360 if x is None else int(x)
    y0 = 640 if y is None else int(y)
    x1 = x0 + int(dx)
    y1 = y0 + int(dy)
    if dx == 0 and dy == 0:
        return []
    return ["input", "swipe", str(x0), str(y0), str(x1), str(y1)]


def android_scroll(
    *,
    dx: int = 0,
    dy: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, Any]:
    inner = swipe_inner_argv(dx=dx, dy=dy, x=x, y=y)
    if not inner:
        return {"ok": False, "error": "scroll needs dx or dy"}
    result = exec_in_android(inner)
    if not result.get("ok"):
        return result
    out: dict[str, Any] = {
        "ok": True,
        "dx": int(dx),
        "dy": int(dy),
        "computer": JARVIS_ANDROID,
        "argv": result.get("argv"),
    }
    if x is not None and y is not None:
        out["x"] = int(x)
        out["y"] = int(y)
    return out


def focus_inner_argv(*, app: str) -> list[str]:
    pkg = _ANDROID_APPS.get(str(app or "").strip().lower(), str(app or "").strip())
    if not pkg or not _SAFE_PKG_RE.match(pkg):
        return []
    return [
        "am",
        "start",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        pkg,
    ]


def android_focus_app(*, app: str) -> dict[str, Any]:
    needle = str(app or "").strip()
    inner = focus_inner_argv(app=needle)
    if not inner:
        return {
            "ok": False,
            "error": f"unknown app on jarvis-android: {needle}",
            "app": needle,
            "focused": False,
            "computer": JARVIS_ANDROID,
        }
    result = exec_in_android(inner)
    if not result.get("ok"):
        out = dict(result)
        out["app"] = needle
        out["focused"] = False
        return out
    return {
        "ok": True,
        "app": needle,
        "focused": True,
        "computer": JARVIS_ANDROID,
        "argv": result.get("argv"),
        "raise": "am",
    }


def android_close_windows(*, app: str = "chrome") -> dict[str, Any]:
    """Home key — Android has no window-close the way Linux does."""
    result = exec_in_android(["input", "keyevent", "KEYCODE_HOME"])
    out = dict(result) if isinstance(result, dict) else {"ok": False}
    out.setdefault("ok", False)
    out["app"] = str(app or "chrome")
    out["closed"] = "home"
    out["method"] = "home"
    out["computer"] = JARVIS_ANDROID
    if out.get("ok"):
        out["error"] = ""
    return out


def android_list_windows() -> list[tuple[int, str, str]]:
    result = exec_in_android(["dumpsys", "activity", "activities"])
    if not result.get("ok"):
        return []
    rows: list[tuple[int, str, str]] = []
    stdout = result.get("stdout") or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    for i, line in enumerate(str(stdout).splitlines()):
        line = line.strip()
        if not line:
            continue
        if "ActivityRecord" in line or line.startswith("package:"):
            rows.append((i + 1, line[:120], "android"))
    return rows


def is_http_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    try:
        parts = urlparse(raw)
    except Exception:
        return False
    return (parts.scheme or "").lower() in {"http", "https"} and bool(parts.netloc)


def plan_android_run_app(args: dict[str, Any] | None) -> dict[str, Any]:
    """Map run_app args onto Android intents / packages."""
    args = args or {}
    target = str(args.get("target") or "").strip()
    url = str(args.get("url") or "").strip()
    lowered = target.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        url = target
        target = "chrome"
    if url and not is_http_url(url):
        return {"ok": False, "error": "url must be http:// or https://"}
    key = (target or ("chrome" if url else "")).strip().lower().replace("\\", "/")
    key = key.split("/")[-1].removesuffix(".exe")
    if url:
        argv = [
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
        ]
        return {
            "ok": True,
            "kind": "url",
            "app": "browser",
            "url": url,
            "argv": argv,
            "cmd": " ".join(argv),
            "computer": JARVIS_ANDROID,
        }
    pkg = _ANDROID_APPS.get(key, key if "." in key else "")
    if not pkg or not _SAFE_PKG_RE.match(pkg):
        return {"ok": False, "error": f"unknown app on jarvis-android: {target or key}"}
    argv = [
        "monkey",
        "-p",
        pkg,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
    ]
    return {
        "ok": True,
        "kind": "app",
        "app": pkg,
        "url": "",
        "argv": argv,
        "cmd": " ".join(argv),
        "computer": JARVIS_ANDROID,
    }


def android_run_app(plan: dict[str, Any]) -> dict[str, Any]:
    argv = list(plan.get("argv") or [])
    if not argv:
        return {"ok": False, "error": "empty launch", "computer": JARVIS_ANDROID}
    result = exec_in_android(argv, detach=True)
    if not result.get("ok"):
        return result
    out: dict[str, Any] = {
        "ok": True,
        "started": plan.get("cmd") or " ".join(argv),
        "argv": argv,
        "computer": JARVIS_ANDROID,
        "window": True,
    }
    if plan.get("url"):
        out["opened"] = plan["url"]
        out["page_ready"] = True
    return out


def is_play_store_client() -> bool:
    """Product rule: this box is not the phone app under android/."""
    return False
