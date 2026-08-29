"""Public Talk last-conversation log — durable You/Jarvis/tool turns."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "xN_hHhRHz0FjzHy2QdWwY4xK3aF3q1e8kYl2p0s9t1u"
)
LONG_B64 = "A" * 40 + "B" * 40 + "=="
OPENAI_KEY = "sk-proj-this-is-not-a-real-key-value-at-all"
COOKIE = "session=abc123; Path=/"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)

    from app.config import get_settings
    from app.jarvis import settings_store, talk_log
    import app.jarvis.gateway as gw

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    talk_log.reset_rate_limits()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    talk_log.reset_rate_limits()


def test_sanitize_strips_keys_cookies_auth_and_long_b64():
    from app.jarvis.talk_log import sanitize_talk_text

    dirty = (
        f"open the news Cookie: {COOKIE} "
        f"Authorization: Bearer {JWT} "
        f"api_key={OPENAI_KEY} "
        f"shot={LONG_B64}"
    )
    clean = sanitize_talk_text(dirty)
    assert OPENAI_KEY not in clean
    assert JWT not in clean
    assert COOKIE not in clean
    assert "Bearer " not in clean
    assert LONG_B64 not in clean
    assert "session=abc123" not in clean
    assert "[REDACTED]" in clean


def test_append_then_last_is_newest_last(tmp_path):
    from app.jarvis.talk_log import append_turn, last_conversation

    root = tmp_path / "ws"
    append_turn("you", "open the news", root=root)
    append_turn("jarvis", "Opening the news.", root=root)
    append_turn("tool", "opened", tool="open_site", result="ok", root=root)
    convo = last_conversation(root=root)
    assert convo["started_at"]
    roles = [row["role"] for row in convo["turns"]]
    assert roles == ["you", "jarvis", "tool"]
    assert convo["turns"][0]["text"] == "open the news"
    assert convo["turns"][1]["text"] == "Opening the news."
    assert convo["turns"][2]["tool"] == "open_site"


def test_caps_at_last_eighty_turns(tmp_path):
    from app.jarvis.talk_log import MAX_TURNS, append_turn, last_conversation

    root = tmp_path / "ws"
    for i in range(MAX_TURNS + 7):
        append_turn(
            "you",
            f"line {i}",
            root=root,
            ts=f"2026-08-22T17:{i // 60:02d}:{i % 60:02d}Z",
        )
    convo = last_conversation(root=root)
    assert len(convo["turns"]) == MAX_TURNS
    assert convo["turns"][0]["text"] == "line 7"
    assert convo["turns"][-1]["text"] == f"line {MAX_TURNS + 6}"


def test_public_page_posts_on_bubble_add_and_loads_memory():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    assert "function postTalkLog" in page
    assert "/api/jarvis/talk/log" in page
    assert "/api/jarvis/talk/last" in page
    add_fn = page.split("function add(who, text, live)", 1)[1].split(
        "function setLiveYou", 1
    )[0]
    assert 'postTalkLog(who, text)' in add_fn
    assert "if (!live && (who === \"you\" || who === \"jarvis\"))" in add_fn
    finish_you = page.split("function finishLiveYou()", 1)[1].split(
        "function setLiveJarvis", 1
    )[0]
    assert 'postTalkLog("you"' in finish_you
    finish_him = page.split("function finishLiveJarvis()", 1)[1].split(
        "function talkPathFromHealth", 1
    )[0]
    assert 'postTalkLog("jarvis"' in finish_him
    run = page.split("async function runTool(name, args)", 1)[1].split(
        "function sendToolResult", 1
    )[0]
    assert 'postTalkLog("tool"' in run
    assert "function loadMemoryTab" in page
    assert 'if (name === "memory") void loadMemoryTab()' in page
    assert 'id="memory-log"' in page
    assert "He has not saved anything here yet." in page
    assert "14 Rose Lane" not in page
    assert "innerHTML" not in page
    assert "sk-" not in page
    assert "api key" not in low
    assert "OPENAI_API_KEY" not in page
    assert "Who does the extra work" in page
    assert "helper-picks" in page


@pytest.mark.asyncio
async def test_post_then_get_last_talk(client, tmp_path):
    posted = await client.post(
        "/api/jarvis/talk/log",
        json={"role": "you", "text": "open the news"},
    )
    assert posted.status_code == 200
    assert posted.json()["ok"] is True
    him = await client.post(
        "/jarvis/api/jarvis/talk/log",
        json={"role": "jarvis", "text": "Look at the screen."},
    )
    assert him.status_code == 200

    got = await client.get("/api/jarvis/talk/last")
    assert got.status_code == 200
    body = got.json()
    assert body["ok"] is True
    assert body["started_at"]
    roles = [row["role"] for row in body["turns"]]
    assert roles[-2:] == ["you", "jarvis"]
    texts = [row["text"] for row in body["turns"]]
    assert "open the news" in texts
    assert "Look at the screen." in texts
    assert texts.index("open the news") < texts.index("Look at the screen.")

    hosted = await client.get("/jarvis/api/jarvis/talk/last")
    assert hosted.status_code == 200
    assert hosted.json()["turns"][-1]["role"] == "jarvis"
    assert "test-secret-at-least-32-chars-long!!" not in got.text
    assert "sk-" not in got.text


@pytest.mark.asyncio
async def test_talk_log_strips_secrets_and_needs_no_api_key(client):
    dirty = (
        f"Cookie: {COOKIE}; Authorization: Bearer {JWT}; "
        f"x-api-key: {OPENAI_KEY}; blob={LONG_B64}"
    )
    r = await client.post(
        "/api/jarvis/talk/log",
        json={"role": "you", "text": dirty},
    )
    assert r.status_code == 200
    stored = r.json()["turn"]["text"]
    assert OPENAI_KEY not in stored
    assert JWT not in stored
    assert LONG_B64 not in stored
    assert "session=abc123" not in stored
    assert "Bearer " not in stored

    got = await client.get("/api/jarvis/talk/last")
    blob = got.text
    assert OPENAI_KEY not in blob
    assert JWT not in blob
    assert LONG_B64 not in blob
    assert "test-secret-at-least-32-chars-long!!" not in blob
    assert "xai-test-key" not in blob


@pytest.mark.asyncio
async def test_ask_persists_you_and_jarvis(client):
    ask = await client.post("/jarvis/api/jarvis/ask", json={"text": "hello"})
    assert ask.status_code == 200
    assert ask.json()["reply"] == "Hello."

    got = await client.get("/jarvis/api/jarvis/talk/last")
    assert got.status_code == 200
    turns = got.json()["turns"]
    roles = [row["role"] for row in turns]
    texts = [row["text"] for row in turns]
    assert "you" in roles
    assert "jarvis" in roles
    assert "hello" in texts
    assert "Hello." in texts


@pytest.mark.asyncio
async def test_talk_log_rate_limit(client, monkeypatch):
    from app.jarvis import talk_log

    monkeypatch.setenv("JARVIS_TALK_LOG_RATE_PER_MIN", "2")
    talk_log.reset_rate_limits()
    ok1 = await client.post("/api/jarvis/talk/log", json={"role": "you", "text": "one"})
    ok2 = await client.post("/api/jarvis/talk/log", json={"role": "you", "text": "two"})
    blocked = await client.post(
        "/api/jarvis/talk/log", json={"role": "you", "text": "three"}
    )
    assert ok1.status_code == 200
    assert ok2.status_code == 200
    assert blocked.status_code == 429
