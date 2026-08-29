"""Host disk free space — the machine Jarvis is running on, not the Linux lookalike.

``get_disk_space`` must answer the Windows host (C: when that volume exists)
even if Docker / jarvis-computer failed to start. Opening the Linux desktop
is extra and must not swallow a storage question.
"""

from __future__ import annotations

import os
import shutil
import string
from typing import Any, Callable

ExistsFn = Callable[[str], bool]
UsageFn = Callable[[str], Any]


def windows_shaped(*, exists: ExistsFn | None = None, platform: str | None = None) -> bool:
    """True on Windows, or when a Windows-style C: volume is present (tests)."""
    plat = (platform if platform is not None else os.name).lower()
    if plat in {"nt", "win32", "windows"}:
        return True
    check = exists or os.path.exists
    try:
        return bool(check("C:\\") or check("C:/"))
    except OSError:
        return False


def _letter_roots(drive_arg: str) -> list[str]:
    letter = (drive_arg or "").strip().upper().replace("\\", "").replace("/", "")
    if letter.endswith(":"):
        letter = letter[:-1]
    if letter and len(letter) == 1 and letter in string.ascii_uppercase:
        return [f"{letter}:\\"]
    if drive_arg:
        return []
    return [f"{ch}:\\" for ch in string.ascii_uppercase]


def _posix_roots(drive_arg: str) -> list[str]:
    raw = (drive_arg or "").strip()
    if raw and raw not in {"C", "C:", "c", "c:"}:
        return [raw if raw.startswith("/") else "/"]
    return ["/"]


def _fmt_bytes(n: int) -> str:
    x = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(x)} {unit}"
            return f"{x:.2f} {unit}"
        x /= 1024.0
    return f"{x:.2f} TB"


def _usage_row(root: str, usage: Any, *, label: str) -> dict[str, Any]:
    total = int(getattr(usage, "total", 0) or 0)
    used = int(getattr(usage, "used", 0) or 0)
    free = int(getattr(usage, "free", 0) or 0)
    return {
        "drive": label,
        "root": root,
        "host": True,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "total": _fmt_bytes(total),
        "used": _fmt_bytes(used),
        "free": _fmt_bytes(free),
        "free_percent": round(100.0 * free / total, 1) if total else 0,
    }


def collect_host_drives(
    *,
    drive: str = "",
    exists: ExistsFn | None = None,
    disk_usage: UsageFn | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Read free/total space on the host. Never talks to Docker."""
    check = exists or os.path.exists
    usage_fn = disk_usage or shutil.disk_usage
    win = windows_shaped(exists=check, platform=platform)
    out: list[dict[str, Any]] = []

    if win:
        for root in _letter_roots(drive):
            try:
                if not check(root):
                    continue
                usage = usage_fn(root)
            except OSError:
                continue
            label = f"{root[0].upper()}:"
            out.append(_usage_row(root, usage, label=label))
        if out:
            return out

    for root in _posix_roots(drive):
        try:
            if win and not check(root):
                continue
            usage = usage_fn(root)
        except OSError:
            continue
        # On a Windows-shaped host the spoken label is still C:.
        label = "C:" if win else root
        out.append(_usage_row(root, usage, label=label))
        break
    return out


def host_disk_space(
    *,
    drive: str = "",
    exists: ExistsFn | None = None,
    disk_usage: UsageFn | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Host free-space payload for get_disk_space. Independent of jarvis-computer."""
    drives = collect_host_drives(
        drive=drive,
        exists=exists,
        disk_usage=disk_usage,
        platform=platform,
    )
    if not drives:
        return {"ok": False, "error": "no drives found", "host": True}
    parts = [
        f"You have {d['free']} free on {d['drive']} (of {d['total']} total)."
        for d in drives
    ]
    return {
        "ok": True,
        "host": True,
        "drives": drives,
        "summary": " ".join(parts),
    }
