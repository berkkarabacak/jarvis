"""Proof script exists and uses look/click/type — not Playwright."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "proof_overlay_dismiss.py"
FIXTURE = ROOT / "scripts" / "fixtures" / "overlay_continue.html"


def _load():
    spec = importlib.util.spec_from_file_location("proof_overlay_dismiss", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_proof_script_uses_look_click_type_not_playwright():
    assert SCRIPT.is_file()
    assert FIXTURE.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    html = FIXTURE.read_text(encoding="utf-8")
    assert "dismiss_blocking_overlays" in text
    assert "look_has_blocking_overlay" in text
    assert "web_search_query" in text
    assert "playwright" not in text.lower()
    assert "selenium" not in text.lower()
    assert "webdriver" not in text.lower()
    assert "Sign in, save money" in html
    assert 'id="dismiss"' in html
    assert "Sign in" in html


def test_scripted_proof_dismisses_then_continues():
    proof = _load()
    out = proof.scripted_proof()
    assert out["ok"] is True
    assert out["dismissed"] is True
    assert out["continued"] is True
    assert out.get("signed_in") is False
    assert (920, 170) in out["clicks"]
    assert any("hotel" in t.lower() or "Rome" in t for t in out["typed"])


def test_proof_script_main_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dismissed" in proc.stdout
