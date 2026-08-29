"""Windows mouse, keyboard, and window focus for Jarvis (ORCH-368 / ORCH-372 / ORCH-379 / ORCH-391).

click / type / scroll / focus_app / keys are ordinary tools. No confirm, nonce, or
needs_confirm in v1. Real pointer/keyboard/focus I/O is Windows-first and
swappable so tests never move the user's cursor or windows.

type sends Unicode text only. keys sends real Win32 shortcuts (Ctrl+Tab, not
the letters "ctrl+tab").

ORCH-379: SetForegroundWindow often fails from a background Jarvis process.
raise_hwnd tries AttachThreadInput and a brief Alt pulse. focused=false is
never reported as ok=true.
"""

from __future__ import annotations

import os
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# Test seam. When set, click/type/scroll/focus_app/keys call these instead of user32.
_BACKEND: dict[str, Callable[..., dict[str, Any]]] | None = None

_MAX_TYPE_CHARS = 4000
_MAX_COMBO_CHARS = 40

# Win32 virtual-key codes and SendInput flags. type uses UNICODE; keys uses these.
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21  # PageUp
VK_NEXT = 0x22  # PageDown
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_LWIN = 0x5B

_MODIFIER_NAMES = {
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "shift": VK_SHIFT,
    "alt": VK_MENU,
    "win": VK_LWIN,
    "windows": VK_LWIN,
    "meta": VK_LWIN,
}

_NAMED_KEYS = {
    "tab": VK_TAB,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "space": VK_SPACE,
    "backspace": VK_BACK,
    "delete": VK_DELETE,
    "del": VK_DELETE,
    "home": VK_HOME,
    "end": VK_END,
    "left": VK_LEFT,
    "right": VK_RIGHT,
    "up": VK_UP,
    "down": VK_DOWN,
    "pageup": VK_PRIOR,
    "pagedown": VK_NEXT,
    "pgup": VK_PRIOR,
    "pgdn": VK_NEXT,
}


def set_input_backend(
    backend: dict[str, Callable[..., dict[str, Any]]] | None,
) -> None:
    """Replace the OS input backend (tests). Pass None to restore Windows I/O."""
    global _BACKEND
    _BACKEND = backend


def reset_input_backend() -> None:
    set_input_backend(None)
    try:
        from app.jarvis.computer import reset_computer_state

        reset_computer_state()
    except Exception:
        pass


def _real_input_allowed() -> bool:
    """Refuse live mouse/keyboard while pytest is running unless explicitly on."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = (os.environ.get("JARVIS_ALLOW_REAL_INPUT") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}
    return True


def _dispatch(name: str, **kwargs: Any) -> dict[str, Any]:
    fn = (_BACKEND or {}).get(name)
    if fn is not None:
        return fn(**kwargs)
    from app.jarvis.computer import (
        JARVIS_ANDROID,
        JARVIS_COMPUTER,
        current_desktop_backend,
    )

    # Jarvis's machine has its own exec seam; do not treat it as live Windows I/O.
    backend = current_desktop_backend()
    if backend == JARVIS_ANDROID:
        from app.jarvis.android_computer import (
            android_click,
            android_close_windows,
            android_focus_app,
            android_keys,
            android_scroll,
            android_type,
        )

        if name == "click":
            return android_click(**kwargs)
        if name == "type":
            return android_type(**kwargs)
        if name == "scroll":
            return android_scroll(**kwargs)
        if name == "focus_app":
            return android_focus_app(**kwargs)
        if name == "keys":
            return android_keys(**kwargs)
        if name == "close_windows":
            return android_close_windows(app=str(kwargs.get("app") or "chrome"))
        return {"ok": False, "error": f"unknown input: {name}"}
    if backend == JARVIS_COMPUTER:
        from app.jarvis.computer import (
            linux_click,
            linux_close_chrome_windows,
            linux_focus_app,
            linux_keys,
            linux_scroll,
            linux_type,
        )

        if name == "click":
            return linux_click(**kwargs)
        if name == "type":
            return linux_type(**kwargs)
        if name == "scroll":
            return linux_scroll(**kwargs)
        if name == "focus_app":
            return linux_focus_app(**kwargs)
        if name == "keys":
            return linux_keys(**kwargs)
        if name == "close_windows":
            return linux_close_chrome_windows(app=str(kwargs.get("app") or "chrome"))
        return {"ok": False, "error": f"unknown input: {name}"}
    if not _real_input_allowed():
        return {
            "ok": False,
            "error": "live mouse, keyboard, and window focus are off during tests",
            "tool": name,
        }
    if name == "click":
        return _win_click(**kwargs)
    if name == "type":
        return _win_type(**kwargs)
    if name == "scroll":
        return _win_scroll(**kwargs)
    if name == "focus_app":
        return _win_focus_app(**kwargs)
    if name == "keys":
        return _win_keys(**kwargs)
    return {"ok": False, "error": f"unknown input: {name}"}


CLICK_GAP_S = 0.1  # ~10 clicks/sec between points in a batch
_MAX_BATCH_CLICKS = 20


def _click_points(
    x: Any = None,
    y: Any = None,
    clicks: Any = None,
) -> list[tuple[int, int]]:
    """One or more (x, y) points. ``clicks`` is [{x, y}, ...] or [[x, y], ...]."""
    points: list[tuple[int, int]] = []
    if isinstance(clicks, list):
        for pt in clicks[:_MAX_BATCH_CLICKS]:
            if isinstance(pt, dict):
                try:
                    points.append((int(pt["x"]), int(pt["y"])))
                except (KeyError, TypeError, ValueError):
                    continue
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    points.append((int(pt[0]), int(pt[1])))
                except (TypeError, ValueError):
                    continue
    if not points:
        try:
            points.append((int(x), int(y)))
        except (TypeError, ValueError):
            return []
    return points


def click(
    *,
    x: Any = None,
    y: Any = None,
    button: str = "left",
    clicks: Any = None,
) -> dict[str, Any]:
    btn = (button or "left").strip().lower()
    if btn not in {"left", "right"}:
        return {"ok": False, "error": "button must be left or right"}
    points = _click_points(x, y, clicks)
    if not points:
        return {"ok": False, "error": "x and y must be numbers"}
    results: list[dict[str, Any]] = []
    for i, (xi, yi) in enumerate(points):
        if i and not os.environ.get("PYTEST_CURRENT_TEST"):
            time.sleep(CLICK_GAP_S)
        results.append(_dispatch("click", x=xi, y=yi, button=btn))
    if len(results) == 1:
        return results[0]
    return {
        "ok": all(bool(r.get("ok")) for r in results),
        "clicks": results,
        "n": len(results),
        "button": btn,
    }


def type_text(*, text: str) -> dict[str, Any]:
    raw = str(text or "")
    if not raw:
        return {"ok": False, "error": "nothing to type"}
    if len(raw) > _MAX_TYPE_CHARS:
        raw = raw[:_MAX_TYPE_CHARS]
    return _dispatch("type", text=raw)


def _token_vk(token: str) -> tuple[int, bool] | None:
    """Map one combo token to (vk, is_modifier). None if unknown."""
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in _MODIFIER_NAMES:
        return _MODIFIER_NAMES[t], True
    if t in _NAMED_KEYS:
        return _NAMED_KEYS[t], False
    if len(t) == 1 and "a" <= t <= "z":
        return ord(t.upper()), False
    if len(t) == 1 and "0" <= t <= "9":
        return ord(t), False
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 12:
            return 0x70 + (n - 1), False
    return None


def parse_hotkey(combo: str) -> dict[str, Any]:
    """Parse 'ctrl+tab' into modifier vk codes plus one key vk.

    type cannot do this — it only sends Unicode characters.
    """
    raw = str(combo or "").strip()
    if not raw:
        return {"ok": False, "error": "combo required"}
    if len(raw) > _MAX_COMBO_CHARS:
        return {"ok": False, "error": "combo is too long"}
    parts = [p.strip().lower() for p in raw.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return {"ok": False, "error": "combo required"}

    modifiers: list[int] = []
    modifier_names: list[str] = []
    key_vk: int | None = None
    key_name = ""
    for part in parts:
        mapped = _token_vk(part)
        if mapped is None:
            return {"ok": False, "error": f"unknown key {part!r}"}
        vk, is_mod = mapped
        if is_mod:
            if vk in modifiers:
                return {"ok": False, "error": f"duplicate modifier {part}"}
            modifiers.append(vk)
            # Canonical names so ctrl and control look the same.
            name = {
                VK_CONTROL: "ctrl",
                VK_SHIFT: "shift",
                VK_MENU: "alt",
                VK_LWIN: "win",
            }[vk]
            modifier_names.append(name)
            continue
        if key_vk is not None:
            return {"ok": False, "error": "only one non-modifier key is allowed"}
        key_vk = vk
        key_name = part

    if key_vk is None:
        return {"ok": False, "error": "combo needs a key after the modifiers"}

    # Down modifiers, down key, up key, up modifiers (reverse).
    events: list[tuple[int, int]] = [(vk, 0) for vk in modifiers]
    events.append((key_vk, 0))
    events.append((key_vk, KEYEVENTF_KEYUP))
    events.extend((vk, KEYEVENTF_KEYUP) for vk in reversed(modifiers))

    normalized = "+".join([*modifier_names, key_name])
    return {
        "ok": True,
        "combo": normalized,
        "modifiers": modifier_names,
        "key": key_name,
        "vk": [*modifiers, key_vk],
        "events": events,
    }


# Tab / reopen-tab shortcuts. After these, Chrome's title may still be
# about:blank until the destination tab paints.
_TAB_SWITCH_KEYS = frozenset(
    {
        "tab",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "t",
        "w",
        "prior",
        "next",
        "pgup",
        "pgdn",
        "pageup",
        "pagedown",
    }
)

_LOADED_PAGE_WAIT_S = 8.0


def is_chrome_tab_combo(combo: str) -> bool:
    """True for Ctrl+Tab / Ctrl+1..9 / Ctrl+Shift+T (not Alt+Tab or Ctrl+L)."""
    parsed = parse_hotkey(combo)
    if not parsed.get("ok"):
        return False
    mods = set(parsed.get("modifiers") or [])
    key = str(parsed.get("key") or "")
    return "ctrl" in mods and key in _TAB_SWITCH_KEYS


def is_close_all_combo(combo: str) -> bool:
    """True for the one-shot close-all shortcut (not ctrl+w, not escape)."""
    raw = str(combo or "").strip().lower().replace(" ", "").replace("_", "-")
    return raw in {"close-all", "closeall", "close-windows", "closewindows"}


def close_windows(*, app: str = "chrome") -> dict[str, Any]:
    """Close every Chrome/Chromium window on Jarvis's computer."""
    needle = str(app or "chrome").strip() or "chrome"
    fn = (_BACKEND or {}).get("close_windows")
    if fn is not None:
        return fn(app=needle)
    from app.jarvis.computer import (
        JARVIS_COMPUTER,
        current_desktop_backend,
        linux_close_chrome_windows,
    )
    from app.jarvis.virtual_pc import hosted_linux_talk

    if current_desktop_backend() == JARVIS_COMPUTER or hosted_linux_talk():
        return linux_close_chrome_windows(app=needle)
    return {
        "ok": False,
        "error": "close_windows is for jarvis-computer",
        "app": needle,
    }


def keys(*, combo: str = "") -> dict[str, Any]:
    """Send a real shortcut. combo is like ctrl+tab or ctrl+shift+t."""
    needle = str(combo or "").strip()
    if is_close_all_combo(needle):
        return close_windows(app="chrome")
    parsed = parse_hotkey(needle)
    if not parsed.get("ok"):
        return parsed
    result = _dispatch(
        "keys",
        combo=str(parsed["combo"]),
        events=list(parsed["events"]),
        vk=list(parsed["vk"]),
        modifiers=list(parsed["modifiers"]),
        key=str(parsed["key"]),
    )
    if not isinstance(result, dict):
        return {"ok": False, "error": "keys returned no result", "combo": parsed["combo"]}
    out = dict(result)
    out.setdefault("combo", parsed["combo"])
    out.setdefault("vk", parsed["vk"])
    out.setdefault("modifiers", parsed["modifiers"])
    out.setdefault("key", parsed["key"])
    out.setdefault("events", parsed["events"])
    return out


def unicode_type_events(text: str) -> list[tuple[int, int, int]]:
    """What type() would send: (wVk, wScan, flags). wVk is always 0.

    This cannot press Ctrl or Tab as keys — only Unicode characters.
    """
    events: list[tuple[int, int, int]] = []
    for ch in str(text or ""):
        code = ord(ch)
        events.append((0, code, KEYEVENTF_UNICODE))
        events.append((0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return events


def scroll(*, dx: int = 0, dy: int = 0, x: int | None = None, y: int | None = None) -> dict[str, Any]:
    try:
        dxi, dyi = int(dx or 0), int(dy or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "dx and dy must be numbers"}
    if dxi == 0 and dyi == 0:
        return {"ok": False, "error": "scroll needs dx or dy"}
    xi = yi = None
    if x is not None and y is not None:
        try:
            xi, yi = int(x), int(y)
        except (TypeError, ValueError):
            return {"ok": False, "error": "x and y must be numbers"}
    return _dispatch("scroll", dx=dxi, dy=dyi, x=xi, y=yi)


_FOCUS_FAILED = (
    "window matched but was not brought to the front "
    "(SetForegroundWindow failed; AttachThreadInput and Alt also failed)"
)


def focus_app(*, app: str = "", title: str = "") -> dict[str, Any]:
    """Bring a visible top-level window to the front (process or title match)."""
    needle = str(app or title or "").strip()
    if not needle:
        return {"ok": False, "error": "app or title required"}
    if len(needle) > 200:
        needle = needle[:200]
    try:
        from app.jarvis.computer import recent_focus_fail

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
            }
    except Exception:
        pass
    result = _dispatch("focus_app", app=needle)
    if not isinstance(result, dict):
        return {"ok": False, "error": "focus_app returned no result", "app": needle}
    result = dict(result)
    if result.get("ok") and result.get("focused") is False:
        result["ok"] = False
        result.setdefault("error", _FOCUS_FAILED)
    if not result.get("ok") and "chrome" in needle.lower():
        err = str(result.get("error") or "")
        low = err.lower()
        if "no visible window" in low and "retry run_app" not in low:
            result["error"] = (
                err.rstrip(".")
                + ". Retry run_app to open Chrome — do not ask the user to click Chrome."
            )
        elif "do not ask the user to click chrome" not in low:
            result["error"] = (
                err.rstrip(".")
                + ". Do not ask the user to click Chrome."
            )
    return result


def has_visible_window(*, app: str = "") -> bool:
    """True when a visible top-level window matches app/title (ORCH-377)."""
    needle = str(app or "").strip()
    if not needle:
        return False
    fn = (_BACKEND or {}).get("has_visible_window")
    if fn is not None:
        raw = fn(app=needle)
        if isinstance(raw, dict):
            return bool(raw.get("ok") or raw.get("visible"))
        return bool(raw)
    from app.jarvis.computer import JARVIS_COMPUTER, current_desktop_backend

    if current_desktop_backend() == JARVIS_COMPUTER:
        from app.jarvis.computer import linux_has_visible_window

        return linux_has_visible_window(app=needle)
    if not _real_input_allowed():
        return False
    if sys.platform != "win32":
        return False
    return bool(_win_matching_windows(needle))


def _win_click(*, x: int, y: int, button: str = "left") -> dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "click is Windows-only"}
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    down, up = (0x0008, 0x0010) if button == "right" else (0x0002, 0x0004)
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)
    return {"ok": True, "x": int(x), "y": int(y), "button": button}


def _win_scroll(
    *,
    dx: int = 0,
    dy: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "scroll is Windows-only"}
    import ctypes

    user32 = ctypes.windll.user32
    if x is not None and y is not None:
        user32.SetCursorPos(int(x), int(y))
    wheel_delta = 120
    if dy:
        user32.mouse_event(0x0800, 0, 0, int(dy) * wheel_delta, 0)
    if dx:
        user32.mouse_event(0x1000, 0, 0, int(dx) * wheel_delta, 0)
    out: dict[str, Any] = {"ok": True, "dx": int(dx), "dy": int(dy)}
    if x is not None and y is not None:
        out["x"] = int(x)
        out["y"] = int(y)
    return out


def _win_send_key_events(events: list[tuple[int, int, int]]) -> dict[str, Any]:
    """Send (wVk, wScan, flags) rows through SendInput. Windows only."""
    if sys.platform != "win32":
        return {"ok": False, "error": "keyboard input is Windows-only", "sent": 0}
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("ki", KEYBDINPUT),
            ("padding", ctypes.c_ubyte * 8),
        ]

    extra = ctypes.c_ulong(0)
    user32 = ctypes.windll.user32
    sent = 0
    for w_vk, w_scan, flags in events:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki = KEYBDINPUT(
            int(w_vk),
            int(w_scan),
            int(flags),
            0,
            ctypes.cast(ctypes.pointer(extra), ctypes.c_void_p),
        )
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            return {"ok": False, "error": "SendInput failed", "sent": sent}
        sent += 1
    return {"ok": True, "sent": sent}


def _win_type(*, text: str) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "type is Windows-only"}
    events = unicode_type_events(text)
    result = _win_send_key_events(events)
    if not result.get("ok"):
        typed = int(result.get("sent") or 0) // 2
        return {"ok": False, "error": result.get("error") or "SendInput failed", "typed": typed}
    return {"ok": True, "typed": len(text), "chars": len(text)}


def _win_keys(
    *,
    combo: str,
    events: list[tuple[int, int]] | None = None,
    vk: list[int] | None = None,
    modifiers: list[str] | None = None,
    key: str = "",
) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "keys is Windows-only"}
    rows = list(events or [])
    if not rows:
        parsed = parse_hotkey(combo)
        if not parsed.get("ok"):
            return parsed
        rows = list(parsed["events"])
        vk = list(parsed["vk"])
        modifiers = list(parsed["modifiers"])
        key = str(parsed["key"])
        combo = str(parsed["combo"])
    # Real vk down/up. No KEYEVENTF_UNICODE — that is type's path.
    win_events = [(int(code), 0, int(flags)) for code, flags in rows]
    result = _win_send_key_events(win_events)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error") or "SendInput failed",
            "combo": combo,
            "vk": list(vk or []),
        }
    return {
        "ok": True,
        "combo": combo,
        "vk": list(vk or []),
        "modifiers": list(modifiers or []),
        "key": key,
        "events": rows,
    }



_PROCESS_ALIASES = {
    "chrome": ("chrome",),
    "msedge": ("msedge",),
    "edge": ("msedge",),
    "firefox": ("firefox",),
    "notepad": ("notepad",),
    "excel": ("excel",),
    "calc": ("calculatorapp", "calc", "calculator"),
    "calculator": ("calculatorapp", "calc", "calculator"),
    "explorer": ("explorer",),
}


def _norm_proc(name: str) -> str:
    return (name or "").strip().lower().removesuffix(".exe")


def _window_matches(needle: str, title: str, process: str) -> bool:
    n = _norm_proc(needle)
    t = (title or "").lower()
    p = _norm_proc(process)
    if not n:
        return False
    if n in t:
        return True
    if p and n == p:
        return True
    aliases = _PROCESS_ALIASES.get(n, ())
    if p and p in {_norm_proc(a) for a in aliases}:
        return True
    return False


def _process_image_stem(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(32768)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            path = buf.value or ""
            return _norm_proc(path.rsplit("\\", 1)[-1])
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _win_matching_windows(app: str) -> list[tuple[int, str, str]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    needle = str(app or "").strip()
    matches: list[tuple[int, str, str]] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @WNDENUMPROC
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = _process_image_stem(int(pid.value))
        if _window_matches(needle, title, process):
            matches.append((int(hwnd), title, process))
        return True

    user32.EnumWindows(_enum, 0)
    return matches


# Exact folded title heads (before " - Google Chrome").
# about:blank is the same URL in every Chrome language.
_PLACEHOLDER_HEADS = frozenset(
    {
        "untitled",
        "new tab",
        "about:blank",
        "adsiz",
        "cevrildi",  # Chrome "Translated" leftover, not a page
        "translated",
    }
)

# Folded needles matched inside the title head. ASCII + live mojibake.
# Do not use these on a long vision essay — only the HWND title head.
_PLACEHOLDER_NEEDLES = (
    "ayrilsin",
    "aevrilsin",  # live audit-log mangling of ayrılsın
    "leave this page",
    "adsiz",
    "cevrildi",
    "yuklensin",  # Sayfalar geri yüklensin mi?
    "restore pages",
    "cevrilsin",  # Bu sayfa çevrilsin mi? (not the leftover "Çevrildi")
    "translate this page",
)

# Restore-pages / translate-this-page overlays. Escape closes them so the
# real tab title can appear. Leave-page is placeholder-only (do not Escape).
_DISMISS_DIALOG_NEEDLES = (
    "yuklensin",
    "restore pages",
    "cevrilsin",
    "translate this page",
)

# UTF-8 of Turkish letters read as cp1252, then lowercased.
# ı C4 B1 → Ä± → ä±; ş C5 9F → ÅŸ → åÿ.
_UTF8_AS_LATIN1 = (
    ("ä±", "i"),  # ı
    ("åÿ", "s"),  # ş
    ("äÿ", "g"),  # ğ
    ("ã§", "c"),  # ç
    ("ã¼", "u"),  # ü
    ("ã¶", "o"),  # ö
)

# Turkish + cp1254-read-as-cp1252 leftovers (ı/ş/ğ → ý/þ/ð).
_TITLE_FOLD = str.maketrans(
    {
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
        "ý": "i",
        "þ": "s",
        "ð": "g",
    }
)

# A Chrome HWND whose title is still about:blank is not the page the user asked for.
BLANK_PAGE_ERROR = (
    "Chrome window title is about:blank / empty / Untitled — "
    "that is not a loaded page. Wait or run_app the URL again, "
    "then see_screen. Do not invent page text. "
    "Do not tell the user to refresh or check their internet."
)


def _fold_window_title(title: str) -> str:
    """Lowercase and fold Turkish / mojibake so ı/ş match i/s."""
    # Rewrite UTF-8-as-cp1252 pairs before NFKC. NFKC compatibility-decomposes
    # ¼ (ü mojibake) into 1⁄4, which would miss the ã¼ → u map.
    t = (title or "").strip().lower()
    for src, dst in _UTF8_AS_LATIN1:
        t = t.replace(src, dst)
    t = unicodedata.normalize("NFKC", t)
    t = t.translate(_TITLE_FOLD)
    t = "".join(
        c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)
    )
    return t


def is_placeholder_title(title: str) -> bool:
    """True for empty / Untitled / New Tab / about:blank / leave-page / Chrome dialogs."""
    raw = (title or "").strip()
    if not raw:
        return True
    folded = _fold_window_title(raw)
    if not folded:
        return True
    if "about:blank" in folded:
        return True
    head = folded.split(" - ", 1)[0].strip()
    if head in _PLACEHOLDER_HEADS or folded in _PLACEHOLDER_HEADS:
        return True
    return any(needle in head for needle in _PLACEHOLDER_NEEDLES)


def is_dismissible_chrome_dialog(title: str) -> bool:
    """True for Restore pages? / Translate this page? (TR+EN). Not leave-page."""
    raw = (title or "").strip()
    if not raw:
        return False
    folded = _fold_window_title(raw)
    if not folded:
        return False
    head = folded.split(" - ", 1)[0].strip()
    return any(needle in head for needle in _DISMISS_DIALOG_NEEDLES)


# Older tests / callers.
_is_placeholder_title = is_placeholder_title


def _normalize_window_rows(raw: Any) -> list[tuple[int, str, str]]:
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


def list_matching_windows(*, app: str = "") -> list[tuple[int, str, str]]:
    """Visible top-level windows matching app/title. Tests inject list_windows."""
    needle = str(app or "").strip()
    if not needle:
        return []
    fn = (_BACKEND or {}).get("list_windows")
    if fn is not None:
        try:
            raw = fn(app=needle)
        except TypeError:
            raw = fn()
        return _normalize_window_rows(raw)
    from app.jarvis.computer import JARVIS_COMPUTER, current_desktop_backend

    if current_desktop_backend() == JARVIS_COMPUTER:
        from app.jarvis.computer import linux_list_windows

        return linux_list_windows()
    if not _real_input_allowed():
        return []
    if sys.platform != "win32":
        return []
    return _win_matching_windows(needle)


def has_loaded_page_window(*, app: str = "") -> bool:
    """True when a matching visible window title is not about:blank / empty / Untitled."""
    needle = str(app or "").strip()
    if not needle:
        return False
    fn = (_BACKEND or {}).get("has_loaded_page_window")
    if fn is not None:
        try:
            raw = fn(app=needle)
        except TypeError:
            raw = fn()
        if isinstance(raw, dict):
            return bool(raw.get("ok") or raw.get("loaded") or raw.get("visible"))
        return bool(raw)
    for _hwnd, title, _process in list_matching_windows(app=needle):
        if not is_placeholder_title(title):
            return True
    return False


def wait_for_loaded_page(app: str, *, timeout_s: float | None = None) -> dict[str, Any]:
    """Wait until a matching window title is not about:blank / empty / Untitled.

    Restore-pages / translate-this-page Chrome dialogs are not a loaded page.
    Send Escape once (existing keys path) so the real tab title can appear.
    """
    needle = str(app or "").strip()
    limit = _LOADED_PAGE_WAIT_S if timeout_s is None else timeout_s
    last_title = ""
    saw_window = False
    dismissed = False

    def _scan() -> str | None:
        nonlocal last_title, saw_window, dismissed
        rows = list_matching_windows(app=needle) if needle else []
        if not rows:
            return None
        saw_window = True
        for _hwnd, title, _process in rows:
            if not is_placeholder_title(title):
                return title
            last_title = title
            if not dismissed and is_dismissible_chrome_dialog(title):
                keys(combo="escape")
                dismissed = True
        return None

    ready = _scan()
    if ready:
        return {"ok": True, "window": True, "title": ready, "page_ready": True}
    if not saw_window and not _real_input_allowed() and not (_BACKEND or {}).get(
        "list_windows"
    ):
        # Pytest with no injected windows: nothing will appear. Do not sleep.
        return {"ok": False, "window": False, "title": "", "page_ready": False}

    deadline = time.monotonic() + max(0.0, float(limit))
    while time.monotonic() < deadline:
        time.sleep(0.25)
        ready = _scan()
        if ready:
            return {"ok": True, "window": True, "title": ready, "page_ready": True}
    return {
        "ok": False,
        "window": saw_window,
        "title": last_title,
        "page_ready": False,
    }


def _pick_focus_window(
    matches: list[tuple[int, str, str]],
) -> tuple[int, str, str] | None:
    """Prefer a titled page window over Untitled / New Tab helper HWNDs."""
    if not matches:
        return None
    titled = [m for m in matches if (m[1] or "").strip()]
    real = [m for m in titled if not is_placeholder_title(m[1])]
    if real:
        return real[0]
    if titled:
        return titled[0]
    return matches[0]


class RaiseApi(Protocol):
    """OS calls used to raise a HWND. Tests inject a fake; live uses user32."""

    def show_window(self, hwnd: int, cmd: int) -> Any: ...
    def set_foreground(self, hwnd: int) -> bool: ...
    def get_foreground(self) -> int: ...
    def window_thread(self, hwnd: int) -> int: ...
    def current_thread(self) -> int: ...
    def attach_thread_input(self, a: int, b: int, attach: bool) -> bool: ...
    def bring_to_top(self, hwnd: int) -> Any: ...
    def alt_pulse(self) -> None: ...
    def ancestor_root(self, hwnd: int) -> int: ...


SW_RESTORE = 9


def _is_raised(hwnd: int, api: RaiseApi) -> bool:
    fg = int(api.get_foreground() or 0)
    if not fg:
        return False
    if fg == int(hwnd):
        return True
    root = int(api.ancestor_root(fg) or 0)
    return root == int(hwnd)


def raise_hwnd(hwnd: int, api: RaiseApi) -> dict[str, Any]:
    """Bring hwnd to the front. focused=True only if it actually became foreground.

    Order: ShowWindow(SW_RESTORE) + SetForegroundWindow, then AttachThreadInput,
    then a brief Alt key pulse. Tests pass a fake api so pytest never hits user32.
    """
    target = int(hwnd)
    attempts: list[str] = []
    api.show_window(target, SW_RESTORE)
    if api.set_foreground(target) and _is_raised(target, api):
        return {"focused": True, "raise": "SetForegroundWindow", "attempts": attempts}
    attempts.append("SetForegroundWindow")

    attached: list[tuple[int, int]] = []
    try:
        fg = int(api.get_foreground() or 0)
        cur = int(api.current_thread() or 0)
        fg_tid = int(api.window_thread(fg) or 0) if fg else 0
        tgt_tid = int(api.window_thread(target) or 0)
        if cur and fg_tid and fg_tid != cur:
            if api.attach_thread_input(cur, fg_tid, True):
                attached.append((cur, fg_tid))
        if cur and tgt_tid and tgt_tid != cur and tgt_tid != fg_tid:
            if api.attach_thread_input(cur, tgt_tid, True):
                attached.append((cur, tgt_tid))
        api.bring_to_top(target)
        api.show_window(target, SW_RESTORE)
        if api.set_foreground(target) and _is_raised(target, api):
            return {
                "focused": True,
                "raise": "AttachThreadInput",
                "attempts": attempts,
            }
        attempts.append("AttachThreadInput")
    except Exception as exc:
        attempts.append(f"AttachThreadInput:{exc}")
    finally:
        for a, b in attached:
            try:
                api.attach_thread_input(a, b, False)
            except Exception:
                pass

    try:
        api.alt_pulse()
        api.bring_to_top(target)
        api.show_window(target, SW_RESTORE)
        if api.set_foreground(target) and _is_raised(target, api):
            return {"focused": True, "raise": "alt", "attempts": attempts}
        attempts.append("alt")
    except Exception as exc:
        attempts.append(f"alt:{exc}")

    if _is_raised(target, api):
        return {"focused": True, "raise": "already", "attempts": attempts}
    return {
        "focused": False,
        "raise": "",
        "attempts": attempts,
        "error": _FOCUS_FAILED,
    }


@dataclass
class FakeRaiseApi:
    """In-memory RaiseApi for pytest. No user32, no key events."""

    foreground: int = 1
    set_fg_ok: bool = False
    attach_makes_fg: bool = False
    alt_makes_fg: bool = False
    threads: dict[int, int] = field(default_factory=dict)
    current: int = 99
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    attached: set[tuple[int, int]] = field(default_factory=set)

    def show_window(self, hwnd: int, cmd: int) -> None:
        self.calls.append(("show_window", int(hwnd), int(cmd)))

    def set_foreground(self, hwnd: int) -> bool:
        self.calls.append(("set_foreground", int(hwnd)))
        if self.set_fg_ok:
            self.foreground = int(hwnd)
            return True
        if self.attach_makes_fg and self.attached:
            self.foreground = int(hwnd)
            return True
        if self.alt_makes_fg and any(c[0] == "alt_pulse" for c in self.calls):
            self.foreground = int(hwnd)
            return True
        return False

    def get_foreground(self) -> int:
        return int(self.foreground)

    def window_thread(self, hwnd: int) -> int:
        return int(self.threads.get(int(hwnd), int(hwnd) + 1000))

    def current_thread(self) -> int:
        return int(self.current)

    def attach_thread_input(self, a: int, b: int, attach: bool) -> bool:
        pair = (int(a), int(b))
        self.calls.append(("attach_thread_input", pair[0], pair[1], bool(attach)))
        if attach:
            self.attached.add(pair)
        else:
            self.attached.discard(pair)
        return True

    def bring_to_top(self, hwnd: int) -> None:
        self.calls.append(("bring_to_top", int(hwnd)))

    def alt_pulse(self) -> None:
        self.calls.append(("alt_pulse",))

    def ancestor_root(self, hwnd: int) -> int:
        return int(hwnd)


class _Win32RaiseApi:
    def show_window(self, hwnd: int, cmd: int) -> Any:
        import ctypes

        return ctypes.windll.user32.ShowWindow(int(hwnd), int(cmd))

    def set_foreground(self, hwnd: int) -> bool:
        import ctypes

        return bool(ctypes.windll.user32.SetForegroundWindow(int(hwnd)))

    def get_foreground(self) -> int:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)

    def window_thread(self, hwnd: int) -> int:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD(0)
        tid = ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(tid or 0)

    def current_thread(self) -> int:
        import ctypes

        return int(ctypes.windll.kernel32.GetCurrentThreadId() or 0)

    def attach_thread_input(self, a: int, b: int, attach: bool) -> bool:
        import ctypes

        return bool(ctypes.windll.user32.AttachThreadInput(int(a), int(b), bool(attach)))

    def bring_to_top(self, hwnd: int) -> Any:
        import ctypes

        return ctypes.windll.user32.BringWindowToTop(int(hwnd))

    def alt_pulse(self) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        vk_menu = 0x12
        extended = 0x0001
        keyup = 0x0002
        user32.keybd_event(vk_menu, 0x45, extended, 0)
        user32.keybd_event(vk_menu, 0x45, extended | keyup, 0)

    def ancestor_root(self, hwnd: int) -> int:
        import ctypes

        ga_root = 2
        return int(ctypes.windll.user32.GetAncestor(int(hwnd), ga_root) or hwnd)


def _win_focus_app(*, app: str) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "focus_app is Windows-only"}
    needle = str(app or "").strip()
    matches = _win_matching_windows(needle)
    chosen = _pick_focus_window(matches)
    if chosen is None:
        return {"ok": False, "error": f"no visible window matching {needle!r}", "app": needle}

    hwnd, title, process = chosen
    raised = raise_hwnd(hwnd, _Win32RaiseApi())
    focused = bool(raised.get("focused"))
    out: dict[str, Any] = {
        "ok": focused,
        "app": needle,
        "title": title,
        "process": process,
        "focused": focused,
        "raise": raised.get("raise") or "",
        "attempts": raised.get("attempts") or [],
    }
    if not focused:
        out["error"] = str(raised.get("error") or _FOCUS_FAILED)
    return out
