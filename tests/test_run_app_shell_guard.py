from __future__ import annotations

from app.jarvis.tools import _has_unquoted_shell_metachars, _launch_planned


def test_metachars_detected_unquoted():
    assert _has_unquoted_shell_metachars("notepad & calc")
    assert _has_unquoted_shell_metachars("foo | bar")
    assert _has_unquoted_shell_metachars("echo a > b")
    assert _has_unquoted_shell_metachars("cmd ^ x")


def test_quoted_metachars_allowed():
    """URLs and paths with & inside quotes stay launchable."""
    assert not _has_unquoted_shell_metachars('"https://x.com/?a=1&b=2"')
    assert not _has_unquoted_shell_metachars('"C:\\Program Files\\App\\app.exe" /flag')
    assert not _has_unquoted_shell_metachars("notepad.exe")


def test_launch_planned_refuses_metachar_injection(monkeypatch):
    """A plan whose cmd smuggles shell syntax is refused before Popen."""
    import app.jarvis.tools as tools

    monkeypatch.setenv("JARVIS_ALLOW_REAL_LAUNCH", "1")
    launched = {}
    monkeypatch.setattr(
        tools.subprocess,
        "Popen",
        lambda *a, **k: launched.setdefault("called", True),
    )
    plan = {"cmd": "calc.exe & del C:\\x", "argv": [], "url": "", "kind": "win"}
    out = _launch_planned(plan, cwd=".")
    assert out["ok"] is False
    assert "metacharacters" in out["error"]
    assert "called" not in launched


def test_launch_planned_still_runs_clean_cmd(monkeypatch):
    import app.jarvis.tools as tools

    monkeypatch.setenv("JARVIS_ALLOW_REAL_LAUNCH", "1")
    launched = {}
    monkeypatch.setattr(
        tools.subprocess,
        "Popen",
        lambda *a, **k: launched.setdefault("called", True),
    )
    plan = {"cmd": "notepad.exe", "argv": [], "url": "", "kind": "win"}
    out = _launch_planned(plan, cwd=".")
    assert out["ok"] is True
    assert launched.get("called") is True
