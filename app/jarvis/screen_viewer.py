"""ORCH-410 — on-demand viewer for Jarvis's one live desktop.

Opens the existing localhost noVNC session (ORCH-404) at
``http://127.0.0.1:6080``. Does not create a second computer, does not
publish the desktop on all interfaces, and never invents a screenshot.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "jarvis-computer"
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"
ANDROID_COMPOSE_DIR = ROOT / "deploy" / "jarvis-android"
ANDROID_COMPOSE_FILE = ANDROID_COMPOSE_DIR / "docker-compose.yml"

VIEWER_TITLE = "Jarvis's screen"
VIEWER_CONTROL = "Open Jarvis's screen"
VIEWER_PATH = "/ceo/jarvis-screen"
NOVNC_HOST = "127.0.0.1"
NOVNC_PORT = 6080
NOVNC_URL = f"http://{NOVNC_HOST}:{NOVNC_PORT}"
NOVNC_SESSION_URL = f"{NOVNC_URL}/vnc.html?autoconnect=1&resize=scale"
CONTAINER_NAME = "jarvis-computer"
IMAGE_NAME = "jarvis-computer:local"
VOLUME_NAME = "jarvis-computer-home"
ANDROID_CONTAINER = "jarvis-android"
ANDROID_WATCH_PORT = 6081
ANDROID_WATCH_URL = f"http://{NOVNC_HOST}:{ANDROID_WATCH_PORT}"
ANDROID_WATCH_PATH = "/jarvis/android/"
ANDROID_SESSION_URL = f"{ANDROID_WATCH_PATH}?autoconnect=1"
DOWN_MESSAGE = "Jarvis's computer is not running."
START_HINT = "docker start jarvis-computer (or docker compose up -d)"

# Test seams. Pytest never talks to Docker or 6080 unless a flag is set.
_PROBE: Callable[[], dict[str, Any]] | None = None
_START: Callable[[], dict[str, Any]] | None = None
_RUN_CMD: Callable[[list[str]], dict[str, Any]] | None = None


def set_screen_probe(fn: Callable[[], dict[str, Any]] | None) -> None:
    """Replace the 6080 probe (tests). Pass None to restore."""
    global _PROBE
    _PROBE = fn


def set_screen_start(fn: Callable[[], dict[str, Any]] | None) -> None:
    """Replace compose up (tests). Pass None to restore."""
    global _START
    _START = fn


def set_screen_run(fn: Callable[[list[str]], dict[str, Any]] | None) -> None:
    """Replace host docker argv (tests). Pass None to restore."""
    global _RUN_CMD
    _RUN_CMD = fn


def reset_screen_viewer_state() -> None:
    set_screen_probe(None)
    set_screen_start(None)
    set_screen_run(None)


def viewer_contract() -> dict[str, Any]:
    """Stable shape for the on-demand control and the live viewer."""
    return {
        "title": VIEWER_TITLE,
        "control": VIEWER_CONTROL,
        "path": VIEWER_PATH,
        "url": NOVNC_URL,
        "session_url": NOVNC_SESSION_URL,
        "host": NOVNC_HOST,
        "port": NOVNC_PORT,
        "bind": "127.0.0.1",
        "container": CONTAINER_NAME,
        "same_desktop": True,
        "recording": False,
        "public_bind": False,
        "start_hint": START_HINT,
        "down_message": DOWN_MESSAGE,
        "kind": "linux",
        "computer_kind": "linux",
        "watch_path": "/jarvis/novnc/",
    }


def android_viewer_contract() -> dict[str, Any]:
    """Watch path for the Android box. Same Talk iframe, different machine."""
    return {
        "title": VIEWER_TITLE,
        "control": VIEWER_CONTROL,
        "path": VIEWER_PATH,
        "url": ANDROID_WATCH_URL,
        "session_url": ANDROID_SESSION_URL,
        "host": NOVNC_HOST,
        "port": ANDROID_WATCH_PORT,
        "bind": "127.0.0.1",
        "container": ANDROID_CONTAINER,
        "same_desktop": True,
        "recording": False,
        "public_bind": False,
        "start_hint": "docker compose -f deploy/jarvis-android/docker-compose.yml up -d",
        "down_message": DOWN_MESSAGE,
        "kind": "android",
        "computer_kind": "android",
        "watch_path": ANDROID_WATCH_PATH,
        "play_store_client": False,
    }


def android_compose_up_argv() -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(ANDROID_COMPOSE_FILE),
        "--project-directory",
        str(ANDROID_COMPOSE_DIR),
        "up",
        "-d",
    ]


def compose_up_argv() -> list[str]:
    """Preferred start: existing jarvis-computer compose project. Do not rebuild."""
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "--project-directory",
        str(COMPOSE_DIR),
        "up",
        "-d",
    ]


def docker_inspect_argv() -> list[str]:
    return ["docker", "inspect", CONTAINER_NAME]


def docker_start_argv() -> list[str]:
    """Reuse the one existing container (XPS13 / no compose plugin)."""
    return ["docker", "start", CONTAINER_NAME]


def docker_run_argv() -> list[str]:
    """Same flags as deploy/jarvis-computer. Localhost 6080 only. One name."""
    return [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "--hostname",
        CONTAINER_NAME,
        "--restart",
        "unless-stopped",
        "--init",
        "--shm-size",
        "256m",
        "-e",
        "DISPLAY=:1",
        "-e",
        "HOME=/home/jarvis",
        "-e",
        "USER=jarvis",
        "-v",
        f"{VOLUME_NAME}:/home/jarvis",
        "-p",
        "127.0.0.1:6080:6080",
        IMAGE_NAME,
    ]


def compose_is_missing(stderr: str = "", stdout: str = "") -> bool:
    """True when this machine has no compose plugin (XPS13)."""
    blob = f"{stderr}\n{stdout}".lower()
    if "not a docker command" in blob:
        return True
    if "unknown command" in blob and "compose" in blob:
        return True
    if "compose" in blob and "plugin" in blob and (
        "not found" in blob or "not installed" in blob or "missing" in blob
    ):
        return True
    return False


def start_argv_after_compose(*, container_exists: bool) -> list[str]:
    """Fallback when compose is not a command. Same computer, not a second one."""
    if container_exists:
        return docker_start_argv()
    return docker_run_argv()


def _real_io_allowed() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = (os.environ.get("JARVIS_ALLOW_REAL_COMPUTER") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}
    return True


def _selected_kind() -> str:
    try:
        from app.jarvis.settings_store import get_computer_kind

        kind = get_computer_kind()
    except Exception:
        kind = "linux"
    return "android" if kind == "android" else "linux"


def probe_watch(*, timeout: float = 1.5, url: str | None = None) -> dict[str, Any]:
    """Is the selected localhost watch URL answering? No fake picture."""
    target = url or (ANDROID_WATCH_URL if _selected_kind() == "android" else NOVNC_URL)
    if _PROBE is not None:
        raw = _PROBE()
        out = dict(raw) if isinstance(raw, dict) else {"running": bool(raw)}
        out.setdefault("url", target)
        out.setdefault("title", VIEWER_TITLE)
        return out
    if not _real_io_allowed():
        return {
            "running": False,
            "url": target,
            "title": VIEWER_TITLE,
            "error": DOWN_MESSAGE,
            "reason": "live watch probe is off during tests",
        }
    try:
        req = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(req, timeout=max(0.2, float(timeout))) as resp:
            code = int(getattr(resp, "status", 200) or 200)
            running = 200 <= code < 500
            return {
                "running": running,
                "status_code": code,
                "url": target,
                "title": VIEWER_TITLE,
                "error": None if running else DOWN_MESSAGE,
            }
    except urllib.error.HTTPError as err:
        return {
            "running": True,
            "status_code": int(err.code),
            "url": target,
            "title": VIEWER_TITLE,
            "error": None,
        }
    except Exception:
        return {
            "running": False,
            "url": target,
            "title": VIEWER_TITLE,
            "error": DOWN_MESSAGE,
        }


def probe_novnc(*, timeout: float = 1.5) -> dict[str, Any]:
    """Linux noVNC on localhost:6080. Kept for ORCH-410 tests."""
    return probe_watch(timeout=timeout, url=NOVNC_URL)


def screen_status() -> dict[str, Any]:
    """Contract plus a live (or test-seamed) probe. Never a screenshot."""
    kind = _selected_kind()
    body = android_viewer_contract() if kind == "android" else viewer_contract()
    probe = probe_watch(url=str(body.get("url") or NOVNC_URL))
    body["running"] = bool(probe.get("running"))
    body["error"] = probe.get("error") if not body["running"] else None
    if probe.get("status_code") is not None:
        body["status_code"] = probe.get("status_code")
    if probe.get("reason"):
        body["reason"] = probe.get("reason")
    return body


class _CmdResult:
    def __init__(
        self,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
        argv: list[str] | None = None,
    ) -> None:
        self.returncode = int(returncode)
        self.stdout = stdout or ""
        self.stderr = stderr or ""
        self.argv = list(argv or [])


def _run_host(argv: list[str], *, timeout: float = 120) -> _CmdResult:
    if _RUN_CMD is not None:
        raw = _RUN_CMD(list(argv))
        if isinstance(raw, dict):
            return _CmdResult(
                int(raw.get("returncode", 0) or 0),
                str(raw.get("stdout") or ""),
                str(raw.get("stderr") or ""),
                argv,
            )
        return _CmdResult(0 if raw else 1, argv=argv)
    completed = subprocess.run(
        argv,
        cwd=str(COMPOSE_DIR),
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout)),
        check=False,
    )
    return _CmdResult(
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
        argv,
    )


def _fail_start(error: str, argv: list[str], *, reason: str | None = None) -> dict[str, Any]:
    body = {
        "ok": False,
        "started": False,
        "running": False,
        "title": VIEWER_TITLE,
        "url": NOVNC_URL,
        "error": error,
        "argv": argv,
    }
    if reason:
        body["reason"] = reason
    return body


def _wait_for_novnc(argv: list[str], wait_seconds: float) -> dict[str, Any]:
    deadline = time.time() + max(1.0, float(wait_seconds))
    probe = probe_novnc()
    while not probe.get("running") and time.time() < deadline:
        time.sleep(0.4)
        probe = probe_novnc()
    running = bool(probe.get("running"))
    return {
        "ok": running,
        "started": True,
        "running": running,
        "title": VIEWER_TITLE,
        "url": NOVNC_URL,
        "error": None if running else (
            "Jarvis's computer was started, but the live screen at "
            f"{NOVNC_URL} is not answering yet. Wait a few seconds and open "
            "Jarvis's screen again."
        ),
        "argv": argv,
    }


def _start_error_text(detail: str) -> str:
    low = (detail or "").lower()
    if "no such image" in low or "has to be built" in low or "unable to find image" in low:
        return (
            "Jarvis's computer image is not on this machine yet "
            f"({IMAGE_NAME}). Build that image once, then open Jarvis's "
            "screen again. This viewer will not invent a screen."
        )
    return (detail or "Could not start Jarvis's computer.").strip()[:600]


def _start_android(*, wait_seconds: float = 45) -> dict[str, Any]:
    """Start the Android box. Never docker exec into jarvis-computer."""
    argv = android_compose_up_argv()
    if not _real_io_allowed() and _RUN_CMD is None:
        return _fail_start(
            DOWN_MESSAGE,
            argv,
            reason="live compose up is off during tests",
        )
    if _RUN_CMD is None and shutil.which("docker") is None:
        return _fail_start(
            "Docker is not installed. Install Docker, then start Jarvis's "
            "Android computer with docker compose up.",
            argv,
        )
    try:
        result = _run_host(argv)
    except FileNotFoundError:
        return _fail_start(
            "Docker is not installed. Install Docker, then start Jarvis's "
            "Android computer with docker compose up.",
            argv,
        )
    except subprocess.TimeoutExpired:
        return _fail_start("Starting Jarvis's Android computer timed out.", argv)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Could not start Jarvis's Android computer.").strip()
        return _fail_start(_start_error_text(detail), argv)
    deadline = time.time() + max(1.0, float(wait_seconds))
    probe = probe_watch(url=ANDROID_WATCH_URL)
    while not probe.get("running") and time.time() < deadline:
        time.sleep(0.4)
        probe = probe_watch(url=ANDROID_WATCH_URL)
    running = bool(probe.get("running"))
    return {
        "ok": running,
        "started": True,
        "running": running,
        "title": VIEWER_TITLE,
        "url": ANDROID_WATCH_URL,
        "kind": "android",
        "computer_kind": "android",
        "container": ANDROID_CONTAINER,
        "error": None if running else (
            "Jarvis's Android computer was started, but the live screen is "
            "not answering yet. Wait a few seconds and open Jarvis's screen again."
        ),
        "argv": argv,
    }


def start_computer(*, wait_seconds: float = 45) -> dict[str, Any]:
    """Start the selected computer. Linux stays the default compose path."""
    if _START is not None:
        raw = _START()
        out = dict(raw) if isinstance(raw, dict) else {"ok": bool(raw)}
        out.setdefault("title", VIEWER_TITLE)
        out.setdefault("url", NOVNC_URL if _selected_kind() != "android" else ANDROID_WATCH_URL)
        return out

    if _selected_kind() == "android":
        return _start_android(wait_seconds=wait_seconds)

    argv = compose_up_argv()
    if not _real_io_allowed() and _RUN_CMD is None:
        return _fail_start(
            DOWN_MESSAGE,
            argv,
            reason="live compose up is off during tests",
        )

    if _RUN_CMD is None and shutil.which("docker") is None:
        return _fail_start(
            "Docker is not installed. Install Docker, then start Jarvis's "
            f"computer with `{START_HINT}`.",
            argv,
        )

    try:
        result = _run_host(argv)
    except FileNotFoundError:
        return _fail_start(
            "Docker is not installed. Install Docker, then start Jarvis's "
            f"computer with `{START_HINT}`.",
            argv,
        )
    except subprocess.TimeoutExpired:
        return _fail_start("Starting Jarvis's computer timed out.", argv)

    if result.returncode != 0 and compose_is_missing(result.stderr, result.stdout):
        try:
            inspect = _run_host(docker_inspect_argv(), timeout=8)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            inspect = _CmdResult(1, argv=docker_inspect_argv())
        argv = start_argv_after_compose(container_exists=inspect.returncode == 0)
        try:
            result = _run_host(argv)
        except FileNotFoundError:
            return _fail_start(
                "Docker is not installed. Install Docker, then start Jarvis's "
                f"computer with `{START_HINT}`.",
                argv,
            )
        except subprocess.TimeoutExpired:
            return _fail_start("Starting Jarvis's computer timed out.", argv)
        if (
            result.returncode != 0
            and argv[:2] == ["docker", "start"]
            and "no such container" in f"{result.stderr}\n{result.stdout}".lower()
        ):
            argv = docker_run_argv()
            try:
                result = _run_host(argv)
            except FileNotFoundError:
                return _fail_start(
                    "Docker is not installed. Install Docker, then start Jarvis's "
                    f"computer with `{START_HINT}`.",
                    argv,
                )
            except subprocess.TimeoutExpired:
                return _fail_start("Starting Jarvis's computer timed out.", argv)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Could not start Jarvis's computer.").strip()
        return _fail_start(_start_error_text(detail), argv)

    return _wait_for_novnc(argv, wait_seconds)
