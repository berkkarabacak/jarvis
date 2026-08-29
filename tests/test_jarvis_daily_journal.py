"""ORCH-329 daily journal digests ==DAILYMEMORY==."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def test_day_key_berlin(monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.daily_journal import day_key

    # 2026-08-12 23:30 UTC == 2026-08-13 01:30 Berlin (CEST UTC+2)
    dt = datetime(2026, 8, 12, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert day_key(dt) == "day:2026-08-13"


def test_trivial_session_skipped():
    from app.jarvis.daily_journal import is_trivial_session

    assert is_trivial_session([])
    assert is_trivial_session([{"role": "user", "content": "hi"}])
    assert is_trivial_session(
        [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "Hey!"}]
    )
    assert not is_trivial_session(
        [
            {"role": "user", "content": "Let's ship ORCH-329 daily journal digests today"},
            {"role": "assistant", "content": "On it — implementing memory day keys."},
        ]
    )


def test_redact_secrets_in_journal():
    from app.jarvis.daily_journal import digest_turns, format_journal_fact

    turns = [
        {
            "role": "user",
            "content": "Ship ORCH-329 and rotate token ghp_ABCDEFGHIJKLMNOPQRSTUVWX please",
        }
    ]
    dig = digest_turns(turns, source="agent")
    fact = format_journal_fact("day:2026-08-12", dig)
    assert "ghp_" not in fact
    assert "ABCDEFGHIJKLMNOPQRSTUVWX" not in fact
    # redaction surfaces in notes and/or [REDACTED] marker
    assert "[REDACTED]" in fact or any("[REDACTED]" in n for n in (dig.get("notes") or []))


def test_upsert_and_recall_yesterday(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import (
        day_key,
        digest_turns,
        recall_day,
        upsert_day_journal,
    )

    mem = JarvisMemory(tmp_path / "j.db")
    ykey = day_key(datetime.now(tz=ZoneInfo("Europe/Berlin")) - timedelta(days=1))
    dig = digest_turns(
        [
            {"role": "user", "content": "We decided to use mini for builds yesterday"},
            {"role": "assistant", "content": "Noted. Opened PR #42 on orch-329-daily-memory"},
        ],
        source="agent",
    )
    fid = upsert_day_journal(mem, ykey, dig, source="agent")
    assert fid
    got = recall_day(mem, "what did we talk about yesterday?")
    assert got["ok"] is True
    assert got.get("empty") is False
    body = (got.get("fact") or "").lower()
    assert "mini" in body or "pr" in body or "builds" in body


def test_empty_day_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import recall_day

    mem = JarvisMemory(tmp_path / "j.db")
    got = recall_day(mem, "yesterday")
    assert got["ok"] is True
    assert got.get("empty") is True
    assert "No journal" in (got.get("message") or "") or "no" in (got.get("message") or "").lower()


def test_context_blob_includes_journal(tmp_path):
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import upsert_day_journal, digest_turns

    mem = JarvisMemory(tmp_path / "j.db")
    upsert_day_journal(
        mem,
        "day:2026-08-11",
        digest_turns(
            [{"role": "user", "content": "Discussed Bridge write path and memory hooks for ORCH-329"}],
            source="bridge",
        ),
        source="bridge",
    )
    blob = mem.context_blob(max_chars=2000)
    assert "Daily journals:" in blob
    low = blob.lower()
    assert "bridge" in low or "orch-329" in low or "memory" in low


def test_auto_remember_decision(tmp_path):
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import maybe_auto_remember_decision

    mem = JarvisMemory(tmp_path / "j.db")
    assert maybe_auto_remember_decision(mem, "hi") is None
    mid = maybe_auto_remember_decision(
        mem, "We decided to use mini for builds from now on", source="agent"
    )
    assert mid
    rows = mem.search_facts("mini")
    assert any("auto-decision" in (r.get("tags") or "") for r in rows)


def test_note_session_skips_trivial(tmp_path):
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import note_session_activity

    mem = JarvisMemory(tmp_path / "j.db")
    mem.add_turn("s1", "user", "hi")
    assert note_session_activity(mem, "s1", source="agent") is None
    mem.add_turn("s2", "user", "Please implement daily journal recall for yesterday questions")
    mem.add_turn("s2", "assistant", "Done — stored day keys in memory DB.")
    assert note_session_activity(mem, "s2", source="bridge")


def test_recall_tool_day_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.daily_journal import day_key, digest_turns, upsert_day_journal

    ws = Workspace(tmp_path / "Jarvis")
    mem = JarvisMemory(ws.root / "Memory" / "j.db")
    ykey = day_key(datetime.now(tz=ZoneInfo("Europe/Berlin")) - timedelta(days=1))
    upsert_day_journal(
        mem,
        ykey,
        digest_turns(
            [{"role": "user", "content": "Talked about ORCH-329 acceptance criteria"}],
            source="agent",
        ),
        source="agent",
    )
    ctx = ToolContext(ws, mem)
    raw = run_tool(ctx, "recall_memories", {"query": "yesterday"})
    assert "ORCH-329" in raw or "day_journal" in raw or "Daily journal" in raw or "acceptance" in raw


def test_parse_last_n_days_does_not_steal_days_ago():
    from app.jarvis.daily_journal import parse_last_n_days_query, resolve_day_key

    assert parse_last_n_days_query("2 days ago") is None
    assert resolve_day_key("2 days ago") is not None
    assert parse_last_n_days_query("how many agents each of the last 6 days") == 6
    assert parse_last_n_days_query("last 3 days") == 3
    assert parse_last_n_days_query("yesterday") is None


def test_agents_created_zero_when_none(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import (
        digest_turns,
        recall_day,
        recall_last_n_days,
        upsert_day_journal,
    )

    mem = JarvisMemory(tmp_path / "zero.db")
    from app.jarvis.daily_journal import day_key

    today = day_key()
    fid = upsert_day_journal(
        mem,
        today,
        digest_turns(
            [{"role": "user", "content": "Talked about shipping the daily journal count"}],
            source="agent",
        ),
        source="agent",
    )
    assert fid
    got = recall_day(mem, "today")
    assert got["ok"] is True
    assert got.get("empty") is False
    assert got.get("agents_created") == 0
    assert "Agents created: 0" in (got.get("fact") or "")

    recap = recall_last_n_days(mem, 6)
    stored = [d for d in recap["days"] if d["day_key"] == today]
    assert stored
    assert stored[0]["agents_created"] == 0


def test_last_n_days_does_not_invent_missing_days(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.daily_journal import (
        day_key,
        digest_turns,
        recall_last_n_days,
        upsert_day_journal,
    )

    mem = JarvisMemory(tmp_path / "gap.db")
    today = day_key()
    two_ago = day_key(datetime.now(tz=ZoneInfo("Europe/Berlin")) - timedelta(days=2))
    yesterday = day_key(datetime.now(tz=ZoneInfo("Europe/Berlin")) - timedelta(days=1))
    dig = digest_turns(
        [{"role": "user", "content": "Noted a gap day for journal recap tests"}],
        source="agent",
    )
    upsert_day_journal(mem, today, dig, source="agent")
    upsert_day_journal(mem, two_ago, dig, source="agent")

    recap = recall_last_n_days(mem, 6)
    keys = [d["day_key"] for d in recap["days"]]
    assert today in keys
    assert two_ago in keys
    assert yesterday not in keys
    assert all(d["agents_created"] == 0 for d in recap["days"])
    assert "Not stored before" in (recap.get("message") or "")


def test_recall_tool_last_n_days_recap(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("JARVIS_MEMORY_TZ", "Europe/Berlin")
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.daily_journal import day_key, digest_turns, upsert_day_journal

    ws = Workspace(tmp_path / "Jarvis")
    mem = JarvisMemory(ws.root / "Memory" / "j.db")
    upsert_day_journal(
        mem,
        day_key(),
        digest_turns(
            [{"role": "user", "content": "Recap path should return agents created counts"}],
            source="agent",
        ),
        source="agent",
    )
    ctx = ToolContext(ws, mem)
    raw = run_tool(
        ctx,
        "recall_memories",
        {"query": "how many agents each of the last 6 days"},
    )
    assert "agents created" in raw.lower()
    assert "day_journals" in raw or "Stored days" in raw
