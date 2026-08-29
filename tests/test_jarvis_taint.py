"""ORCH-297 — taint tracking. A poisoned file must not drive tools. ==CLAUDE=="""

from __future__ import annotations

import pytest

from app.jarvis.permissions import Tier
from app.jarvis.taint import (
    ALLOW,
    BLOCK,
    CHILD_TAINT_SOURCE,
    CHILD_UNTRUSTED,
    CHILD_UNTRUSTED_PREFIX,
    CONFIRM,
    TaintTracker,
    gate,
    returns_untrusted,
    taint_decision,
    url_in_user_goal,
)


# ---------------------------------------------------------- returns_untrusted

@pytest.mark.parametrize("tool", ["read_file", "home_read", "screenshot", "see_screen", "download_fetch"])
def test_content_from_outside_is_untrusted(tool):
    assert returns_untrusted(tool) is True


@pytest.mark.parametrize("tool", ["disk_space", "list_github_repos", "system_info", "create_excel", "organize_folder", "remember"])
def test_the_machines_own_state_is_not_untrusted(tool):
    assert returns_untrusted(tool) is False


# -------------------------------------------------------------- state machine

def test_reading_a_file_taints_the_turn():
    t = TaintTracker()
    assert t.tainted is False
    t.observe("read_file")
    assert t.tainted is True and t.source == "read_file"


def test_reading_only_the_machine_state_does_not_taint():
    t = TaintTracker()
    t.observe("disk_space")
    t.observe("system_info")
    assert t.tainted is False


def test_a_new_utterance_clears_the_taint():
    t = TaintTracker()
    t.observe("screenshot")
    assert t.tainted is True
    t.clear()
    assert t.tainted is False and t.source == ""


# ------------------------------------------------------------------- policy

def test_untainted_turn_imposes_nothing():
    for tier in Tier:
        decision, _ = taint_decision(tier, tainted=False)
        assert decision == ALLOW


def test_tainted_turn_blocks_l3_and_above():
    for tier in (Tier.L3, Tier.L4, Tier.L5):
        decision, reason = taint_decision(tier, tainted=True)
        assert decision == BLOCK
        assert "untrusted" in reason


def test_tainted_turn_confirms_l1_and_l2():
    for tier in (Tier.L1, Tier.L2):
        decision, reason = taint_decision(tier, tainted=True)
        assert decision == CONFIRM
        assert "confirm" in reason


def test_tainted_turn_still_allows_l0_reads():
    decision, _ = taint_decision(Tier.L0, tainted=True)
    assert decision == ALLOW


# --------------------------------------------------- the scenario that matters

def test_a_poisoned_read_cannot_reach_a_shell_call():
    """The confused-deputy path: the user asks to read a file; its contents
    tell the model to run a shell command. That shell call must not run."""
    t = TaintTracker()

    # Before any read, running a shell tool is a normal (tier/confirm) decision.
    assert gate("run_powershell", t.tainted)[0] == ALLOW

    # The user legitimately reads a file — its bytes are now in context.
    t.observe("read_file")

    # A shell call proposed off the back of that read is blocked outright...
    decision, reason = gate("run_powershell", t.tainted)
    assert decision == BLOCK, reason

    # ...a workspace write is downgraded to needing confirmation...
    assert gate("write_file", t.tainted)[0] == CONFIRM

    # ...but asking the machine's own disk space is still fine.
    assert gate("disk_space", t.tainted)[0] == ALLOW

    # The user speaks again: fresh intent, taint cleared, shell allowed to be
    # decided normally once more.
    t.clear()
    assert gate("run_powershell", t.tainted)[0] == ALLOW


def test_unknown_tool_is_treated_as_highest_risk_while_tainted():
    """permissions.tool_tier defaults unknown tools to L5, so taint blocks
    them — fail closed, not open."""
    t = TaintTracker()
    t.observe("home_read")
    assert gate("some_tool_that_does_not_exist", t.tainted)[0] == BLOCK


def test_tainted_run_app_of_goal_url_is_not_a_confused_deputy():
    """ORCH-376: opening the URL the user already asked for is their intent."""
    t = TaintTracker()
    t.observe("screenshot")
    goal = "Open https://www.ntv.com.tr and name headlines"
    assert url_in_user_goal("https://www.ntv.com.tr", goal)
    assert (
        gate(
            "run_app",
            t.tainted,
            args={"target": "chrome", "url": "https://www.ntv.com.tr"},
            user_goal=goal,
        )[0]
        == ALLOW
    )
    assert (
        gate(
            "run_app",
            t.tainted,
            args={"target": "chrome", "url": "https://evil.example"},
            user_goal=goal,
        )[0]
        == BLOCK
    )
    assert gate("run_powershell", t.tainted)[0] == BLOCK


# ---------------------------------------------------------------- ORCH-324 MCP

@pytest.mark.parametrize(
    "tool",
    [
        "mcp.demo.echo",
        "mcp.github.create_issue",
        "mcp.anything.at.all",
    ],
)
def test_mcp_prefix_is_untrusted_without_opt_in(tool):
    """Every mcp.* name taints — no registry opt-in required (ORCH-324)."""
    assert returns_untrusted(tool) is True


def test_child_api_names_are_locked_untrusted():
    """ORCH-338: spawn/message/wait taint like MCP; loop is ORCH-339."""
    assert CHILD_UNTRUSTED == frozenset({"spawn_child", "message_child", "wait_child"})
    assert CHILD_TAINT_SOURCE == "child"
    for name in CHILD_UNTRUSTED:
        assert returns_untrusted(name) is True


def test_child_prefix_is_untrusted_like_mcp():
    """ORCH-343: child.* mirrors mcp.* without changing locked v1 names."""
    assert CHILD_UNTRUSTED_PREFIX == "child."
    assert returns_untrusted("child.anything") is True
    t = TaintTracker()
    t.observe("child.anything")
    assert t.tainted is True
    assert t.source == CHILD_TAINT_SOURCE


def test_mcp_untrusted_tool_names_also_taint(monkeypatch):
    """Live registry names taint even if somehow missing the mcp. prefix."""
    import app.jarvis.taint as taint_mod

    monkeypatch.setattr(
        taint_mod,
        "mcp_untrusted_tool_names",
        lambda: frozenset({"connector.legacy.read"}),
    )
    assert returns_untrusted("connector.legacy.read") is True
    assert returns_untrusted("not_in_set") is False


# ---------------------------------------------------------------- ORCH-340 children

def test_child_observe_reports_taint_source_child_not_tool():
    """ORCH-340: taint_source is CHILD_TAINT_SOURCE, not the tool name."""
    t = TaintTracker()
    t.observe("wait_child")
    assert t.tainted is True
    assert t.source == CHILD_TAINT_SOURCE
    t.clear()
    t.observe("message_child")
    assert t.source == CHILD_TAINT_SOURCE
    t.clear()
    t.observe("spawn_child")
    assert t.source == CHILD_TAINT_SOURCE


def test_poisoned_child_result_cannot_reach_shell():
    """Confused deputy via child wait_child: output must not auto-drive shell."""
    t = TaintTracker()
    assert gate("run_powershell", t.tainted)[0] == ALLOW

    t.observe("wait_child")
    assert t.tainted is True and t.source == CHILD_TAINT_SOURCE

    decision, reason = gate("run_powershell", t.tainted)
    assert decision == BLOCK, reason
    assert "untrusted" in reason
    assert gate("write_file", t.tainted)[0] == CONFIRM
    assert gate("disk_space", t.tainted)[0] == ALLOW

    t.clear()
    assert gate("run_powershell", t.tainted)[0] == ALLOW


def test_poisoned_inter_agent_message_cannot_reach_shell():
    t = TaintTracker()
    t.observe("message_child")
    assert t.tainted is True
    assert t.source == CHILD_TAINT_SOURCE
    assert gate("run_powershell", t.tainted)[0] == BLOCK


def test_poisoned_mcp_output_cannot_reach_shell():
    """Confused deputy via connector/MCP: poisoned tool output must not
    auto-drive run_powershell."""
    t = TaintTracker()
    assert gate("run_powershell", t.tainted)[0] == ALLOW

    t.observe("mcp.docs.fetch")
    assert t.tainted is True and t.source == "mcp.docs.fetch"

    decision, reason = gate("run_powershell", t.tainted)
    assert decision == BLOCK, reason
    assert "untrusted" in reason

    assert gate("write_file", t.tainted)[0] == CONFIRM
    assert gate("disk_space", t.tainted)[0] == ALLOW

    t.clear()
    assert t.tainted is False
    assert gate("run_powershell", t.tainted)[0] == ALLOW

