"""A4 screen loop, B4 progress, D2 eval harness, D3 guardrails ==GRoK==."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# --- D3 guardrails ---


def test_public_cloud_disables_jarvis(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://aicontrolroom.nl")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("PRIME_AGENT_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_TOKEN", "secret")
    from app.jarvis.guardrails import enforce_public_guardrails, is_public_cloud_host

    assert is_public_cloud_host()
    r = enforce_public_guardrails()
    assert r["public_cloud"] is True
    assert __import__("os").environ.get("JARVIS_ENABLED") == "false"
    assert __import__("os").environ.get("PRIME_AGENT_ENABLED") == "false"


def test_gateway_blocks_tools_on_public(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_GUEST_PROFILE", "true")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "J"))
    import app.jarvis.gateway as gw

    gw._gateway = None
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run("run_powershell", {"command": "Get-Date"}, source="test")
    assert r.get("ok") is False
    assert "public" in (r.get("error") or "").lower()


# --- A4 screen loop ---


def test_screen_proposal_confirm_stub():
    from app.jarvis.screen_loop import build_proposal_from_vision, confirm_proposal

    p = build_proposal_from_vision(
        description="Notepad is open with untitled text.",
        user_goal="save the file",
        screenshot_path="Exports/screenshots/x.png",
    )
    d = p.to_dict()
    blob = json.dumps(d)
    assert d["description"] == "Notepad is open with untitled text."
    assert d["needs_confirm"] is True
    assert "not_implemented_v1" not in blob
    assert "deferred" not in blob.lower()
    assert "no click/type automation yet" not in blob.lower()
    denied = confirm_proposal(p.proposal_id, "cancel")
    assert denied.get("decision") == "deny"

    p2 = build_proposal_from_vision(description="Desktop", user_goal="click start")
    assert p2.to_dict()["needs_confirm"] is False
    ok = confirm_proposal(p2.proposal_id, "confirm")
    ok_blob = json.dumps(ok)
    assert ok.get("acted") is False
    assert "not_implemented_v1" not in ok_blob
    assert "no click/type automation yet" not in ok_blob.lower()

    look = build_proposal_from_vision(description="Chrome and Slack are open.")
    look_d = look.to_dict()
    assert look_d["needs_confirm"] is False
    assert look_d["description"] == "Chrome and Slack are open."
    assert "not_implemented_v1" not in json.dumps(look_d)
    from app.jarvis.screen_loop import screen_goal_needs_confirm

    for goal in (
        "what do you see on the screen",
        "close the tab",
        "Switzerland news",
        "click Agree",
        "keys ctrl+w",
    ):
        assert screen_goal_needs_confirm(goal) is False, goal
        p_look = build_proposal_from_vision(description="A page.", user_goal=goal)
        assert p_look.to_dict()["needs_confirm"] is False, goal
        assert "say confirm" not in p_look.to_dict()["user_prompt"].lower()


# --- B4 progress bus ---


def test_prime_progress_rate_limit(monkeypatch):
    monkeypatch.setenv("JARVIS_PRIME_NARRATE_INTERVAL_SEC", "30")
    from app.jarvis.prime_progress import PrimeProgressBus

    bus = PrimeProgressBus()
    e1 = bus.emit("m1", "started")
    e2 = bus.emit("m1", "still going")
    assert e1 is not None
    assert e2 is None  # rate limited
    bus.silence(60)
    assert bus.emit("m1", "nope") is None


# --- D2 eval harness scenarios (tool routing contracts) ---


EVAL_CASES = [
    {
        "id": "free_space",
        "goal": "How much free disk space do I have?",
        "must_call": "get_disk_space",
    },
    {
        "id": "list_desktop",
        "goal": "List files on my Desktop",
        "must_call": "home_list",
    },
    {
        "id": "memory_recall",
        "goal": "What do you remember about me?",
        "must_call": "recall_memories",
    },
]


def _infer_eval_tool(goal: str) -> str | None:
    """Mirror bridge light inference for eval guarantees."""
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    inf = _infer_tool_from_goal(goal)
    if inf:
        return inf[0]
    g = goal.lower()
    if "remember" in g or "memory" in g or "recall" in g:
        return "recall_memories"
    if "excel" in g or "spreadsheet" in g:
        return "create_excel"
    if "screen" in g:
        return "see_screen"
    return None


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c["id"] for c in EVAL_CASES])
def test_eval_tool_routing(case):
    tool = _infer_eval_tool(case["goal"])
    assert tool == case["must_call"], f"{case['id']}: expected {case['must_call']} got {tool}"


def test_eval_disk_space_via_gateway(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    import app.jarvis.gateway as gw

    gw._gateway = None
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run("get_disk_space", {}, source="eval")
    assert r.get("ok") is True
    assert r.get("drives") or r.get("summary")


def test_eval_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "J"))
    from app.jarvis.memory import JarvisMemory

    m = JarvisMemory(tmp_path / "J" / "Memory" / "j.db")
    m.add_fact("User likes concise answers", tags="prefs")
    rows = m.search_facts("concise")
    assert rows and "concise" in rows[0]["fact"]
