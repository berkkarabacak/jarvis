"""ORCH-406 — proof script exists and refuses to invent a screen."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.jarvis.computer import (
    JARVIS_COMPUTER,
    WINDOWS,
    current_desktop_backend,
    reset_computer_state,
    resolve_desktop_backend,
    set_computer_exec,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "proof_jarvis_computer_notepad.py"

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _load_proof():
    spec = importlib.util.spec_from_file_location(
        "proof_jarvis_computer_notepad", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_computer():
    reset_computer_state()
    yield
    reset_computer_state()
    os.environ.pop("JARVIS_DESKTOP_BACKEND", None)


def test_proof_script_exists_and_uses_orch405_helpers():
    assert SCRIPT.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "ORCH-406" in text
    assert "jarvis-computer" in text
    assert "JARVIS_DESKTOP_BACKEND" in text
    assert "plan_linux_run_app" in text
    assert "linux_run_app" in text
    assert "linux_type" in text
    assert "linux_keys" in text
    assert "screenshot_png" in text
    assert "mousepad" in text
    assert "refusing to invent a screenshot" in text
    # Operator instructions may mention compose up. The script must not spawn.
    assert "subprocess" not in text
    assert "docker compose up" in text
    assert '["docker", "run"]' not in text
    assert "from app.jarvis.computer import" in text


def test_unique_proof_text_includes_date_and_ticket():
    proof = _load_proof()
    text = proof.unique_proof_text(when=date(2026, 8, 16), token="abcd1234")
    assert "ORCH-406" in text
    assert "2026-08-16" in text
    assert "abcd1234" in text
    other = proof.unique_proof_text(when=date(2026, 8, 16))
    assert "ORCH-406" in other
    assert "2026-08-16" in other
    assert other != text


def test_is_real_png_rejects_fakes():
    proof = _load_proof()
    assert proof.is_real_png(_PNG) is True
    assert proof.is_real_png(b"") is False
    assert proof.is_real_png(b"not a png") is False
    assert proof.is_real_png("\x89PNG fake") is False
    assert proof.is_real_png(b"\x89PNG\r\n\x1a\nshort") is False


def test_run_proof_refuses_to_invent_when_desktop_is_down(tmp_path):
    proof = _load_proof()

    def fake(_inner, **_kwargs):
        return {
            "ok": False,
            "error": "jarvis-computer is not running. Start the one existing container.",
        }

    set_computer_exec(fake)
    result = proof.run_proof(artifact_dir=tmp_path, settle_s=0, window_timeout_s=0)
    assert result["ok"] is False
    assert result["invented"] is False
    assert result["live"] is False
    assert "invent" in str(result["error"]).lower()
    assert result["screenshot"] is None
    assert list(tmp_path.glob("*.png")) == []
    assert list(tmp_path.glob("*.txt")) == []


def test_run_proof_refuses_without_exec_seam(tmp_path):
    """Pytest blocks live docker. The script must not write a fake screen."""
    proof = _load_proof()
    result = proof.run_proof(artifact_dir=tmp_path, settle_s=0, window_timeout_s=0)
    assert result["ok"] is False
    assert result["invented"] is False
    assert "invent" in str(result["error"]).lower()
    assert list(tmp_path.glob("*.png")) == []


def test_cli_refuses_to_invent_a_screen(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--artifact-dir", str(tmp_path), "--settle-seconds", "0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "JARVIS_DESKTOP_BACKEND": "jarvis-computer",
        },
    )
    assert result.returncode != 0
    blob = (result.stdout + result.stderr).lower()
    assert "invent" in blob
    assert list(tmp_path.glob("*.png")) == []


def test_run_proof_types_then_reads_file_and_saves_real_png(tmp_path):
    proof = _load_proof()
    typed_text = proof.unique_proof_text(when=date(2026, 8, 16), token="live01")
    state = {"typed": "", "saved": False}

    def fake(inner, **kwargs):
        cmd = " ".join(str(x) for x in inner)
        if "jarvis-computer-ready" in cmd:
            return {"ok": True, "stdout": "jarvis-computer-ready\n:1\n"}
        if "mkdir" in cmd or ": >" in cmd:
            return {"ok": True, "stdout": ""}
        if inner[:1] == ["mousepad"]:
            assert kwargs.get("detach") is True
            assert proof.PROOF_PATH in inner
            return {"ok": True}
        if inner[:2] == ["xdotool", "type"]:
            state["typed"] = inner[-1]
            return {"ok": True}
        if inner[:2] == ["xdotool", "key"]:
            if "ctrl+s" in cmd:
                state["saved"] = True
            return {"ok": True}
        if inner[:2] == ["xdotool", "search"] or "getwindowname" in cmd:
            return {"ok": True, "stdout": "42\tMousepad\n"}
        if inner[:1] == ["cat"]:
            assert inner[-1] == proof.PROOF_PATH
            if state["typed"] and state["saved"]:
                return {"ok": True, "stdout": state["typed"] + "\n"}
            return {"ok": True, "stdout": ""}
        if "scrot" in cmd:
            return {"ok": True, "stdout": _PNG}
        return {"ok": True, "stdout": ""}

    set_computer_exec(fake)
    result = proof.run_proof(
        artifact_dir=tmp_path,
        text=typed_text,
        settle_s=0,
        window_timeout_s=0,
        sleep_s=0,
    )
    assert result["ok"] is True
    assert result["live"] is True
    assert result["invented"] is False
    assert result["computer"] == JARVIS_COMPUTER
    assert result["typed"] == typed_text
    assert typed_text in result["recovered"]
    assert "ORCH-406" in result["recovered"]
    assert "2026-08-16" in result["recovered"]
    shot = Path(result["screenshot"])
    assert shot.is_file()
    assert shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    recovered = Path(result["recovered_file"])
    assert recovered.is_file()
    assert typed_text in recovered.read_text(encoding="utf-8")


def test_run_proof_does_not_write_png_when_scrot_is_empty(tmp_path):
    proof = _load_proof()
    typed_text = "ORCH-406 notepad proof 2026-08-16 token empty-shot"
    state = {"typed": "", "saved": False}

    def fake(inner, **_kwargs):
        cmd = " ".join(str(x) for x in inner)
        if "jarvis-computer-ready" in cmd:
            return {"ok": True, "stdout": "jarvis-computer-ready\n:1\n"}
        if inner[:1] == ["mousepad"]:
            return {"ok": True}
        if inner[:2] == ["xdotool", "type"]:
            state["typed"] = inner[-1]
            return {"ok": True}
        if inner[:2] == ["xdotool", "key"] and "ctrl+s" in cmd:
            state["saved"] = True
            return {"ok": True}
        if inner[:2] == ["xdotool", "search"] or "getwindowname" in cmd:
            return {"ok": True, "stdout": "9\tNotepad\n"}
        if inner[:1] == ["cat"] and state["typed"] and state["saved"]:
            return {"ok": True, "stdout": state["typed"]}
        if "scrot" in cmd:
            return {"ok": True, "stdout": b""}
        return {"ok": True, "stdout": ""}

    set_computer_exec(fake)
    result = proof.run_proof(
        artifact_dir=tmp_path,
        text=typed_text,
        settle_s=0,
        window_timeout_s=0,
        sleep_s=0,
    )
    assert result["ok"] is True
    assert result["screenshot"] is None
    assert list(tmp_path.glob("*.png")) == []
    assert typed_text in Path(result["recovered_file"]).read_text(encoding="utf-8")


def test_run_proof_fails_if_file_does_not_contain_typed_text(tmp_path):
    proof = _load_proof()

    def fake(inner, **_kwargs):
        cmd = " ".join(str(x) for x in inner)
        if "jarvis-computer-ready" in cmd:
            return {"ok": True, "stdout": "jarvis-computer-ready\n:1\n"}
        if inner[:1] == ["cat"]:
            return {"ok": True, "stdout": ""}
        if inner[:2] == ["xdotool", "search"] or "getwindowname" in cmd:
            return {"ok": True, "stdout": "1\tMousepad\n"}
        if "scrot" in cmd:
            return {"ok": True, "stdout": _PNG}
        return {"ok": True, "stdout": ""}

    set_computer_exec(fake)
    result = proof.run_proof(
        artifact_dir=tmp_path,
        text="ORCH-406 notepad proof 2026-08-16 token missing",
        settle_s=0,
        window_timeout_s=0,
        sleep_s=0,
    )
    assert result["ok"] is False
    assert result["invented"] is False
    assert "not in the mousepad file" in str(result["error"])


def test_run_proof_does_not_leave_windows_path_pinned(tmp_path, monkeypatch):
    """ORCH-365 must keep working after the proof script runs."""
    proof = _load_proof()
    monkeypatch.delenv("JARVIS_DESKTOP_BACKEND", raising=False)

    def fake(_inner, **_kwargs):
        return {"ok": False, "error": "jarvis-computer is not running"}

    set_computer_exec(fake)
    proof.run_proof(artifact_dir=tmp_path, settle_s=0, window_timeout_s=0)
    assert os.environ.get("JARVIS_DESKTOP_BACKEND") in {None, ""}
    assert current_desktop_backend() != JARVIS_COMPUTER
    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_desktop_backend(goal="click the red button") == WINDOWS
