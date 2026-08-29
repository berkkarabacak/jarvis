"""ORCH-352: parent prompts name helper tools without ordering a hire."""

from __future__ import annotations

from app.jarvis.agent import SYSTEM_PROMPT
from app.jarvis.realtime import (
    JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
    JARVIS_REALTIME_INSTRUCTIONS,
    tools_for_realtime,
)

HELPER_TOOLS = ("spawn_child", "message_child", "wait_child")

# Berk: Jarvis decides when a job needs help. No auto-spawn / must-hire language.
MUST_HIRE_ORDERS = (
    "must hire",
    "always spawn",
    "follow the org plan",
    "you have to",
    "follow pick_org",
    "required",
)


def test_parent_prompts_name_helpers_without_must_hire():
    for text in (
        SYSTEM_PROMPT,
        JARVIS_REALTIME_INSTRUCTIONS,
        JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
    ):
        low = text.lower()
        for name in HELPER_TOOLS:
            assert name in text
        for phrase in MUST_HIRE_ORDERS:
            assert phrase not in low


def test_realtime_exposes_spawn_child_wait_child_message_child():
    names = {t["name"] for t in tools_for_realtime()}
    for name in HELPER_TOOLS:
        assert name in names
    spawn = next(t for t in tools_for_realtime() if t["name"] == "spawn_child")
    low = str(spawn.get("description") or "").lower()
    assert "openrouter" in low
    assert "grok" in low
    assert "not grok" in low
