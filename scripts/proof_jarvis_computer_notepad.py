#!/usr/bin/env python3
"""ORCH-406 live proof: open notepad on Jarvis's computer and write X.

Uses the ORCH-405 helpers (computer=jarvis-computer / JARVIS_DESKTOP_BACKEND).
Talks to the one existing container. Does not docker run / compose up.
Does not invent a screenshot if the desktop is not running.

Usage (after the one container is up):

  cd deploy/jarvis-computer && docker compose up -d --build
  python scripts/proof_jarvis_computer_notepad.py

Open http://127.0.0.1:6080 to watch the same desktop.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.jarvis.computer import (  # noqa: E402
    JARVIS_COMPUTER,
    bind_desktop_backend,
    bind_job_desktop,
    exec_in_computer,
    linux_focus_app,
    linux_has_visible_window,
    linux_keys,
    linux_list_windows,
    linux_run_app,
    linux_type,
    plan_linux_run_app,
    reset_desktop_backend,
    screenshot_png,
)

TICKET = "ORCH-406"
PROOF_PATH = "/home/jarvis/Documents/orch-406-notepad-proof.txt"
INVENT_REFUSAL = "refusing to invent a screenshot"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CURSOR_ARTIFACTS = Path("/opt/cursor/artifacts")


def unique_proof_text(*, when: date | None = None, token: str | None = None) -> str:
    """Unique string that must appear in notepad. Includes the date and ORCH-406."""
    day = (when or date.today()).isoformat()
    nonce = token if token is not None else secrets.token_hex(4)
    return f"{TICKET} notepad proof {day} token {nonce}"


def is_real_png(data: object) -> bool:
    """True only for bytes that look like a real PNG. Never treat empty/text as a screen."""
    if not isinstance(data, (bytes, bytearray)):
        return False
    raw = bytes(data)
    return raw.startswith(PNG_MAGIC) and len(raw) > 32


def default_artifact_dir() -> Path:
    if CURSOR_ARTIFACTS.is_dir() and os.access(CURSOR_ARTIFACTS, os.W_OK):
        return CURSOR_ARTIFACTS
    return Path.cwd() / "artifacts"


def refuse(reason: str) -> dict[str, Any]:
    err = f"{INVENT_REFUSAL}: {reason}"
    return {
        "ok": False,
        "live": False,
        "invented": False,
        "error": err,
        "computer": JARVIS_COMPUTER,
        "screenshot": None,
        "recovered": "",
    }


def probe_computer() -> dict[str, Any]:
    """Ask the existing container if DISPLAY=:1 is there. Do not start it."""
    return exec_in_computer(
        ["sh", "-c", "echo jarvis-computer-ready && printf '%s\\n' \"$DISPLAY\""]
    )


def prepare_empty_note() -> dict[str, Any]:
    return exec_in_computer(
        [
            "sh",
            "-c",
            f"mkdir -p /home/jarvis/Documents && : > {PROOF_PATH}",
        ]
    )


def read_note_file() -> dict[str, Any]:
    return exec_in_computer(["cat", PROOF_PATH])


def wait_for_notepad(*, timeout_s: float, sleep_s: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        if linux_has_visible_window(app="mousepad") or linux_has_visible_window(
            app="notepad"
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.0, float(sleep_s)))


def _stdout_text(result: dict[str, Any]) -> str:
    raw = result.get("stdout") or ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def save_real_screenshot(png: bytes, dest: Path) -> Path | None:
    """Write scrot bytes only. Never generate or copy a placeholder image."""
    if not is_real_png(png):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(png))
    return dest


def run_proof(
    *,
    artifact_dir: Path,
    text: str | None = None,
    settle_s: float = 1.0,
    window_timeout_s: float = 20.0,
    sleep_s: float = 0.4,
) -> dict[str, Any]:
    """Open notepad, type a unique string, read it back, maybe save a real screenshot."""
    prev_backend = os.environ.get("JARVIS_DESKTOP_BACKEND")
    os.environ["JARVIS_DESKTOP_BACKEND"] = JARVIS_COMPUTER
    token = bind_desktop_backend(JARVIS_COMPUTER)
    bind_job_desktop(
        goal="open notepad and write X on your computer",
        computer=JARVIS_COMPUTER,
    )
    try:
        return _run_proof_on_pinned_computer(
            artifact_dir=artifact_dir,
            text=text,
            settle_s=settle_s,
            window_timeout_s=window_timeout_s,
            sleep_s=sleep_s,
        )
    finally:
        reset_desktop_backend(token)
        if prev_backend is None:
            os.environ.pop("JARVIS_DESKTOP_BACKEND", None)
        else:
            os.environ["JARVIS_DESKTOP_BACKEND"] = prev_backend


def _run_proof_on_pinned_computer(
    *,
    artifact_dir: Path,
    text: str | None,
    settle_s: float,
    window_timeout_s: float,
    sleep_s: float,
) -> dict[str, Any]:
    proof = text or unique_proof_text()
    shot_path = artifact_dir / "orch_406_notepad_proof.png"
    recovered_path = artifact_dir / "orch_406_notepad_recovered.txt"

    probe = probe_computer()
    if not probe.get("ok"):
        err = str(probe.get("error") or "jarvis-computer is not reachable")
        return refuse(
            f"{err}. Start the one existing container with "
            "`cd deploy/jarvis-computer && docker compose up -d --build` "
            "(do not create a second computer)."
        )
    if "jarvis-computer-ready" not in _stdout_text(probe):
        return refuse("probe did not confirm the existing jarvis-computer display")

    prepared = prepare_empty_note()
    if not prepared.get("ok"):
        return refuse(str(prepared.get("error") or "could not prepare the notepad file"))

    plan = plan_linux_run_app({"target": "notepad", "args": PROOF_PATH})
    if not plan.get("ok"):
        return refuse(str(plan.get("error") or "could not plan notepad"))
    launched = linux_run_app(plan)
    if not launched.get("ok"):
        return refuse(str(launched.get("error") or "mousepad did not start"))

    if settle_s > 0:
        time.sleep(settle_s)
    if not wait_for_notepad(timeout_s=window_timeout_s, sleep_s=sleep_s):
        return refuse("notepad/mousepad window never appeared on DISPLAY=:1")

    focused = linux_focus_app(app="Mousepad")
    if not focused.get("ok"):
        focused = linux_focus_app(app="notepad")
    if not focused.get("ok"):
        return refuse(str(focused.get("error") or "could not focus notepad"))

    typed = linux_type(text=proof)
    if not typed.get("ok"):
        return refuse(str(typed.get("error") or "type failed"))
    if settle_s > 0:
        time.sleep(min(settle_s, 0.5))

    saved = linux_keys(combo="ctrl+s")
    if not saved.get("ok"):
        return refuse(str(saved.get("error") or "ctrl+s failed"))
    if settle_s > 0:
        time.sleep(min(settle_s, 0.8))

    note = read_note_file()
    recovered = _stdout_text(note).replace("\r\n", "\n").strip()
    windows = linux_list_windows()
    titles = [title for _hwnd, title, _proc in windows]

    grabbed = screenshot_png()
    screenshot: Path | None = None
    if grabbed.get("ok") and is_real_png(grabbed.get("png")):
        screenshot = save_real_screenshot(bytes(grabbed["png"]), shot_path)

    if proof not in recovered:
        out = refuse(
            "typed characters were not in the mousepad file; "
            "not treating the desktop as proven"
        )
        out["typed"] = proof
        out["recovered"] = recovered
        out["windows"] = titles
        out["screenshot"] = str(screenshot) if screenshot else None
        return out

    artifact_dir.mkdir(parents=True, exist_ok=True)
    recovered_path.write_text(recovered + "\n", encoding="utf-8")
    return {
        "ok": True,
        "live": True,
        "invented": False,
        "computer": JARVIS_COMPUTER,
        "typed": proof,
        "recovered": recovered,
        "path": PROOF_PATH,
        "windows": titles,
        "screenshot": str(screenshot) if screenshot else None,
        "recovered_file": str(recovered_path),
        "novnc": "http://127.0.0.1:6080",
        "display": ":1",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ORCH-406: open notepad on Jarvis's computer and write a unique string"
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(default_artifact_dir()),
        help="Where to write a real DISPLAY=:1 screenshot if the container is up",
    )
    parser.add_argument(
        "--text",
        default="",
        help="Override the unique proof string (still must be typed, not invented)",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        help="Pause after launch/type/save so mousepad can keep up",
    )
    args = parser.parse_args(argv)

    result = run_proof(
        artifact_dir=Path(args.artifact_dir),
        text=args.text or None,
        settle_s=float(args.settle_seconds),
    )
    if result.get("ok"):
        print("ORCH-406 live notepad proof: OK")
        print(f"computer={result['computer']} display={result['display']}")
        print(f"typed: {result['typed']}")
        print(f"recovered: {result['recovered']}")
        print(f"file: {result['path']}")
        if result.get("screenshot"):
            print(f"screenshot: {result['screenshot']}")
        else:
            print("screenshot: container was up but scrot did not return a real PNG")
        print(f"watch: {result['novnc']}")
        return 0

    print(result.get("error") or INVENT_REFUSAL, file=sys.stderr)
    if result.get("typed"):
        print(f"typed: {result['typed']}", file=sys.stderr)
    if result.get("recovered"):
        print(f"recovered: {result['recovered']}", file=sys.stderr)
    if result.get("screenshot"):
        print(f"screenshot: {result['screenshot']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
