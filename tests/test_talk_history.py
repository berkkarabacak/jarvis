"""Public Talk oneshot + Realtime use last conversation, not a fresh ask."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "xN_hHhRHz0FjzHy2QdWwY4xK3aF3q1e8kYl2p0s9t1u"
)
LONG_B64 = "A" * 40 + "B" * 40 + "=="
OPENAI_KEY = "sk-proj-this-is-not-a-real-key-value-at-all"
OX_TEST = "or-test-not-a-key"
COOKIE = "session=abc123; Path=/"


class _Res:
    def __init__(self, payload: dict, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, posts: list, handler, timeout=None):
        self._posts = posts
        self._handler = handler
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        rec = {"url": url, "headers": headers or {}, "json": json or {}}
        self._posts.append(rec)
        return self._handler(rec)


@pytest.fixture
def talk_ws(tmp_path, monkeypatch):
    root = tmp_path / "Jarvis"
    root.mkdir(parents=True)
    (root / "Memory").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JARVIS_WORKSPACE", str(root))
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    return root


def _city_chat(root: Path) -> None:
    from app.jarvis.talk_log import append_turn

    append_turn(
        "you",
        "Tell me about Turkey",
        root=root,
        ts="2026-08-22T18:00:00Z",
    )
    append_turn(
        "jarvis",
        "Turkey sits between Europe and Asia. Many people visit Istanbul.",
        root=root,
        ts="2026-08-22T18:00:04Z",
    )


def test_recent_turns_same_session_and_skips_current_ask(talk_ws):
    from app.jarvis.talk_log import append_turn, recent_talk_turns, talk_messages_for_oneshot

    _city_chat(talk_ws)
    append_turn(
        "you",
        "and the capital?",
        root=talk_ws,
        ts="2026-08-22T18:00:20Z",
    )
    turns = recent_talk_turns("and the capital?", root=talk_ws)
    texts = [row["text"] for row in turns]
    assert "Tell me about Turkey" in texts
    assert "Istanbul" in texts[-1]
    assert "and the capital?" not in texts
    messages = talk_messages_for_oneshot("and the capital?", root=talk_ws)
    assert messages[0]["role"] == "user"
    assert "Turkey" in messages[0]["content"]
    assert messages[-1]["role"] == "assistant"
    assert all(m["role"] in {"user", "assistant"} for m in messages)


def test_thin_session_includes_last_conversation(talk_ws):
    from app.jarvis.talk_log import append_turn, recent_talk_turns

    _city_chat(talk_ws)
    append_turn(
        "you",
        "and the capital?",
        root=talk_ws,
        ts="2026-08-22T19:10:00Z",
    )
    turns = recent_talk_turns("and the capital?", root=talk_ws)
    texts = [row["text"] for row in turns]
    assert "Tell me about Turkey" in texts
    assert any("Istanbul" in t for t in texts)
    assert "and the capital?" not in texts


def test_empty_history_is_empty(talk_ws):
    from app.jarvis.talk_log import (
        has_talk_history,
        recent_talk_turns,
        talk_messages_for_oneshot,
        talk_recap_for_session,
    )

    assert recent_talk_turns("hello", root=talk_ws) == []
    assert talk_messages_for_oneshot("hello", root=talk_ws) == []
    assert talk_recap_for_session(root=talk_ws) == ""
    assert has_talk_history("hello", root=talk_ws) is False


def test_recap_and_messages_stay_redacted(talk_ws):
    from app.jarvis.talk_log import (
        append_turn,
        talk_messages_for_oneshot,
        talk_recap_for_session,
    )

    dirty = (
        f"Cookie: {COOKIE}; Authorization: Bearer {JWT}; "
        f"api_key={OPENAI_KEY}; shot={LONG_B64}"
    )
    append_turn("you", f"open the news {dirty}", root=talk_ws)
    append_turn("jarvis", f"Look at the screen. {dirty}", root=talk_ws)
    recap = talk_recap_for_session(root=talk_ws)
    blob = json.dumps(talk_messages_for_oneshot("and then?", root=talk_ws))
    for secret in (OPENAI_KEY, JWT, LONG_B64, COOKIE, "Bearer ", "session=abc123"):
        assert secret not in recap
        assert secret not in blob
    assert "[REDACTED]" in recap or "[REDACTED]" in blob
    assert "Last conversation" in recap
    assert "sk-" not in recap
    assert len(recap) <= 900


@pytest.mark.asyncio
async def test_oneshot_followup_uses_mocked_history(talk_ws, monkeypatch):
    posts: list[dict] = []
    _city_chat(talk_ws)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def handler(rec):
        messages = rec["json"].get("messages") or []
        blob = json.dumps(messages)
        assert "moonshot" not in rec["url"]
        assert rec["json"]["reasoning"] == {"effort": "low", "exclude": True}
        assert OX_TEST not in blob
        assert OPENAI_KEY not in blob
        if "Istanbul" in blob and "Turkey" in blob:
            return _Res({"choices": [{"message": {"content": "Ankara."}}]})
        return _Res({"choices": [{"message": {"content": "Which country?"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    from app.jarvis.voice_ask import _simple_talk_oneshot

    reply = await _simple_talk_oneshot("and the capital?")
    assert reply == "Ankara."
    assert reply != "What do you need?"
    assert len(posts) == 1
    messages = posts[0]["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Turkey" in messages[1]["content"]
    assert messages[2]["role"] == "assistant"
    assert "Istanbul" in messages[2]["content"]
    assert messages[-1] == {"role": "user", "content": "and the capital?"}
    assert "moonshot" not in posts[0]["url"]


@pytest.mark.asyncio
async def test_oneshot_empty_history_still_works(talk_ws, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def handler(rec):
        messages = rec["json"].get("messages") or []
        assert messages == [
            {"role": "system", "content": messages[0]["content"]},
            {"role": "user", "content": "and the capital?"},
        ]
        return _Res({"choices": [{"message": {"content": "Which country?"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    from app.jarvis.voice_ask import _simple_talk_oneshot

    reply = await _simple_talk_oneshot("and the capital?")
    assert reply == "Which country?"
    assert len(posts[0]["json"]["messages"]) == 2
    assert posts[0]["json"]["reasoning"] == {"effort": "low", "exclude": True}


def test_last_resort_uses_history_not_canned_need(talk_ws):
    from app.jarvis.voice_ask import _talk_last_resort

    assert _talk_last_resort("what's your name") == "What do you need?"
    assert _talk_last_resort("why") == "What do you need?"
    _city_chat(talk_ws)
    name = _talk_last_resort("what's your name")
    assert name != "Still here. Go on."
    assert name != "What do you need?"
    assert "Istanbul" in name or "Turkey" in name
    assert _talk_last_resort("say that again slower") == (
        "Turkey sits between Europe and Asia. Many people visit Istanbul."
    )
    assert _talk_last_resort("what did I just ask") == "Tell me about Turkey"


@pytest.mark.asyncio
async def test_this_chat_recall_uses_oneshot_not_empty_journal(talk_ws, monkeypatch):
    asked: list[str] = []

    async def stub_oneshot(text: str) -> str:
        asked.append(text)
        return "We were talking about Turkey and Istanbul."

    _city_chat(talk_ws)
    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what did we talk about")
    assert asked == ["what did we talk about"]
    assert "Turkey" in body["reply"]
    assert body["reply"] != "I do not have yesterday yet."
    assert body["reply"] != "What do you need?"


@pytest.mark.asyncio
async def test_yesterday_still_uses_journal_not_oneshot(talk_ws, monkeypatch):
    called: list[str] = []

    async def boom(text: str) -> str:
        called.append(text)
        raise AssertionError("oneshot must not run for yesterday")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what did we talk about yesterday")
    assert called == []
    assert body["reply"] == "I do not have yesterday yet."


def test_realtime_instructions_include_short_recap(talk_ws):
    from app.jarvis.realtime import build_instructions, build_realtime_session_config

    bare = build_instructions()
    assert "Tell me about Turkey" not in bare
    assert "Last conversation" not in bare
    _city_chat(talk_ws)
    text = build_instructions(locale="en-US")
    assert "Last conversation" in text
    assert "Turkey" in text
    assert "Istanbul" in text
    assert "do not greet as if new" in text.lower()
    assert OPENAI_KEY not in text
    assert "sk-" not in text
    cfg = build_realtime_session_config(locale="en-US")
    assert "Turkey" in str(cfg.get("instructions") or "")
    assert len(str(cfg.get("instructions") or "")) < 20000


@pytest.mark.asyncio
async def test_mint_session_includes_recap_not_keys(talk_ws, monkeypatch):
    import httpx
    from app.config import get_settings
    from app.jarvis import gateway as gw
    from app.jarvis import realtime_routes, settings_store
    from app.jarvis.talk_log import append_turn
    from app.main import create_app

    append_turn("you", f"Remember this {OPENAI_KEY}", root=talk_ws)
    append_turn("jarvis", "We were talking about the garden.", root=talk_ws)
    monkeypatch.setenv("DATABASE_PATH", str(talk_ws / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
    minted: list[dict] = []

    class _FakeRes:
        status_code = 200
        text = ""

        def json(self):
            return {"value": "eph-test-token"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            minted.append(json or {})
            return _FakeRes()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(realtime_routes.httpx, "AsyncClient", _FakeClient)
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/jarvis/realtime/session",
                json={"voice": "marin", "locale": "en-US"},
            )
            health = await ac.get("/api/jarvis/health")
            settings = await ac.get("/api/jarvis/settings")
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    payload = minted[0]
    session = payload.get("session") or {}
    instructions = str(session.get("instructions") or "")
    assert "Last conversation" in instructions
    assert "garden" in instructions
    assert OPENAI_KEY not in instructions
    assert "sk-proj-this-is-not-a-real-key-value-at-all" not in r.text
    assert "sk-test-openai-optional-upgrade" not in r.text
    assert r.json().get("value") == "eph-test-token"
    health_blob = health.text
    settings_blob = settings.text
    assert "garden" not in health_blob
    assert "Remember this" not in health_blob
    assert "Last conversation" not in health_blob
    assert "turns" not in health.json()
    assert OPENAI_KEY not in health_blob
    assert "sk-test-openai-optional-upgrade" not in health_blob
    assert OPENAI_KEY not in settings_blob
    assert "sk-test-openai-optional-upgrade" not in settings_blob
    assert "garden" not in settings_blob


def test_health_and_settings_omit_transcript(talk_ws, monkeypatch):
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import listen_health, public_talk_sheet

    _city_chat(talk_ws)
    settings_store.reset_cache()
    view = settings_store.public_view(talk_ws)
    sheet = public_talk_sheet()
    health = listen_health()
    blob = json.dumps({"view": view, "sheet": sheet, "health": health})
    assert "Turkey" not in blob
    assert "Istanbul" not in blob
    assert "Last conversation" not in blob
    assert "turns" not in health
    assert OPENAI_KEY not in blob
    assert "sk-" not in blob


SWISS_HEADLINES = (
    "• Glacier collapse in the Alps. "
    "• SNB holds rates. "
    "• Voters weigh a housing bill."
)
TURKEY_BROCHURE = (
    "Turkey is a transcontinental country that bridges Europe and Asia. "
    "Its rich heritage and tourism draw millions of visitors each year. "
    "Istanbul is famous for its historic mosques and bazaars."
)


def _switzerland_chat(root: Path) -> None:
    from app.jarvis.talk_log import append_turn

    append_turn(
        "you",
        "Tell me the latest news in Switzerland.",
        root=root,
        ts="2026-08-22T17:28:00Z",
    )
    append_turn(
        "jarvis",
        SWISS_HEADLINES,
        root=root,
        ts="2026-08-22T17:28:04Z",
    )


def test_followups_are_simple_talk_not_desktop():
    from app.jarvis.virtual_pc import (
        goal_is_simple_talk,
        goal_is_virtual_pc_job,
        wants_stop_talk,
        wants_talk_followup,
    )

    for phrase in (
        "What do you think about it?",
        "What do you think about that news?",
        "Really?",
        "Really.",
        "more on that",
        "Stop.",
        "What do you think about Turkey?",
        "What do you think about that?",
        "And plus 3?",
        "Tell me something interesting about Turkey",
        "Pasta or stir-fry tonight?",
        "I told you what do you think about it, like, math information.",
    ):
        assert goal_is_simple_talk(phrase), phrase
        assert not goal_is_virtual_pc_job(phrase), phrase
    assert wants_talk_followup("What do you think about that news?")
    assert wants_talk_followup("Really?")
    assert wants_talk_followup("more on that")
    assert wants_stop_talk("Stop.")
    assert wants_stop_talk("stop talking")
    assert not wants_stop_talk("stop the browser")
    assert not wants_talk_followup("open the news on the screen")
    assert not wants_talk_followup(
        "Close all the apps running, like these Explorer and Error, close them as well."
    )
    assert not wants_talk_followup("I can still see the file manager.")
    assert not goal_is_simple_talk(
        "Close all the apps running, like these Explorer and Error, close them as well."
    )
    assert not goal_is_simple_talk("I can still see the file manager.")


def test_friend_reply_kills_brochure_and_hedge(talk_ws):
    from app.jarvis.voice_ask import _TALK_SYSTEM, _friend_talk_reply, _talk_last_resort

    low = _TALK_SYSTEM.lower()
    assert "friend" in low
    assert "wikipedia" in low
    assert "last topic" in low
    assert "leftover" in low
    assert "do not repeat" in low or "not repeat" in low
    assert _friend_talk_reply("What do you think about Turkey?", TURKEY_BROCHURE) == (
        "It's a big, complicated country. What part do you care about?"
    )
    hedged = (
        "Trade tensions are rising with Canada and the US. "
        "If you'd like more details, I can go on."
    )
    clean = _friend_talk_reply("Really?", hedged)
    assert "more details" not in clean.lower()
    assert "Canada" in clean or "Trade" in clean
    assert len(clean.split(".")) <= 3
    assert _talk_last_resort("Stop.") == "OK."
    assert _talk_last_resort("Stop.") != "What do you need?"


@pytest.mark.asyncio
async def test_switzerland_think_and_really_stay_on_headlines(talk_ws, monkeypatch):
    posts: list[dict] = []
    _switzerland_chat(talk_ws)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def handler(rec):
        blob = json.dumps(rec["json"].get("messages") or [])
        assert "Switzerland" in blob or "Glacier" in blob or "SNB" in blob
        assert "Canada" not in blob
        assert "tariff" not in blob.lower()
        assert rec["json"]["reasoning"] == {"effort": "low", "exclude": True}
        asked = rec["json"]["messages"][-1]["content"]
        if "think" in asked.lower():
            return _Res(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "That glacier collapse is the one that matters."
                            }
                        }
                    ]
                }
            )
        if "really" in asked.lower():
            return _Res(
                {
                    "choices": [
                        {"message": {"content": "Yes — the Alps story is grim."}}
                    ]
                }
            )
        return _Res({"choices": [{"message": {"content": "Canada tariffs rose."}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    from app.jarvis.voice_ask import run_voice_ask

    think = await run_voice_ask("What do you think about that news?")
    assert think["ok"] is True
    assert think["tools_used"] == []
    assert "glacier" in think["reply"].lower()
    assert "canada" not in think["reply"].lower()
    assert "tariff" not in think["reply"].lower()

    really = await run_voice_ask("Really?")
    assert really["ok"] is True
    assert really["tools_used"] == []
    assert "alps" in really["reply"].lower() or "glacier" in really["reply"].lower()
    assert "canada" not in really["reply"].lower()
    assert "france" not in really["reply"].lower()
    assert "if you'd like more details" not in really["reply"].lower()


@pytest.mark.asyncio
async def test_turkey_opinion_is_not_a_brochure(talk_ws, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def handler(rec):
        system = rec["json"]["messages"][0]["content"].lower()
        assert "wikipedia" in system
        assert "brochure" in system
        return _Res({"choices": [{"message": {"content": TURKEY_BROCHURE}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("What do you think about Turkey?")
    assert body["ok"] is True
    assert body["tools_used"] == []
    reply = body["reply"]
    assert "bridges Europe and Asia" not in reply
    assert "rich heritage" not in reply.lower()
    assert len(re.findall(r"[.!?]", reply)) <= 3
    assert len(reply) < 200


@pytest.mark.asyncio
async def test_stop_just_stops(talk_ws, monkeypatch):
    async def boom(asked: str) -> str:
        raise AssertionError("stop must not call oneshot")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("Stop.")
    assert body["ok"] is True
    assert body["reply"] == "OK."
    assert body["tools_used"] == []
    assert "more details" not in body["reply"].lower()


def test_realtime_followup_skips_leftover_screen(talk_ws, monkeypatch):
    monkeypatch.setenv("JARVIS_HOST_OS", "linux")
    from app.jarvis.realtime import (
        build_instructions,
        prepare_realtime_tool_call,
    )

    _switzerland_chat(talk_ws)
    text = build_instructions()
    low = text.lower()
    assert "switzerland" in low or "glacier" in low or "snb" in low
    assert "really?" in low or "what do you think" in low
    assert "leftover" in low
    assert "wikipedia" in low
    assert "canada" not in low
    for goal in (
        "What do you think about that news?",
        "What do you think about that?",
        "Really?",
        "Stop.",
        "more on that",
        "Tell me something interesting about Turkey",
        "Pasta or stir-fry tonight?",
        "And plus 3?",
    ):
        name, _args, early = prepare_realtime_tool_call(
            "see_screen",
            {},
            user_goal=goal,
        )
        assert name == "see_screen", goal
        assert early is not None, goal
        assert early.get("skipped") is True, goal
        reason = str(early.get("reason") or "").lower()
        assert "last conversation" in reason or "spoken news" in reason, goal
    for goal in (
        "Close all the apps running, like these Explorer and Error, close them as well.",
        "close all apps",
        "I can still see the file manager.",
        "No, I can still see the file manager.",
        "what do you see on the screen",
        "What do you see on the screen?",
        "what do you see on your screen",
        "Can you... what do you see on your screen?",
    ):
        name, _args, early = prepare_realtime_tool_call(
            "see_screen",
            {},
            user_goal=goal,
        )
        assert name == "see_screen", goal
        assert early is None, goal
        assert not (early or {}).get("skipped"), goal
        name, args, early = prepare_realtime_tool_call(
            "keys",
            {"combo": "escape"},
            user_goal=goal,
        )
        assert early is None, goal
        if "close all" in goal.lower() or "close them" in goal.lower():
            assert args.get("combo") == "close-all", goal


@pytest.mark.asyncio
async def test_and_plus_3_after_56_is_59_no_stall(talk_ws, monkeypatch):
    from app.jarvis.talk_log import append_turn

    append_turn("you", "7 times 8", root=talk_ws, ts="2026-08-22T20:00:00Z")
    append_turn("jarvis", "56", root=talk_ws, ts="2026-08-22T20:00:01Z")

    async def boom(asked: str) -> str:
        raise AssertionError(f"math follow-up must not call oneshot: {asked}")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("And plus 3?")
    assert body["ok"] is True
    assert body["reply"] == "59"
    assert body["tools_used"] == []
    assert "Still here. Go on." not in body["reply"]


@pytest.mark.asyncio
async def test_interesting_turkey_is_two_sentences_not_stall(talk_ws, monkeypatch):
    async def boom(asked: str) -> str:
        raise AssertionError("interesting Turkey must not stall on oneshot")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("Tell me something interesting about Turkey")
    assert body["ok"] is True
    assert body["tools_used"] == []
    reply = body["reply"]
    assert "Still here. Go on." not in reply
    assert "What do you need?" not in reply
    assert "bridges Europe and Asia" not in reply
    assert "rich heritage" not in reply.lower()
    assert "turquoise" not in reply.lower()
    bits = [p for p in re.split(r"[.!?]+", reply) if p.strip()]
    assert 1 <= len(bits) <= 2


@pytest.mark.asyncio
async def test_think_and_really_never_describe_desktop(talk_ws, monkeypatch):
    from app.jarvis.talk_log import append_turn

    append_turn(
        "you",
        "Tell me something interesting about Turkey",
        root=talk_ws,
        ts="2026-08-22T20:01:00Z",
    )
    append_turn(
        "jarvis",
        "Istanbul cats treat the city like they own it.",
        root=talk_ws,
        ts="2026-08-22T20:01:02Z",
    )
    append_turn(
        "jarvis",
        "A turquoise desktop background fills the screenshot.",
        root=talk_ws,
        ts="2026-08-22T20:01:10Z",
    )

    async def boom(asked: str) -> str:
        raise AssertionError(f"follow-up must use last talk, not oneshot: {asked}")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    facts = "Istanbul cats treat the city like they own it."
    think = await run_voice_ask("What do you think about that?")
    assert think["tools_used"] == []
    assert think["reply"] != facts
    assert "treat the city like they own" not in think["reply"]
    assert "Still here. Go on." not in think["reply"]
    assert "turquoise" not in think["reply"].lower()
    assert "screenshot" not in think["reply"].lower()
    assert "desktop" not in think["reply"].lower()
    assert "cats" in think["reply"].lower() or "Istanbul" in think["reply"]

    really = await run_voice_ask("Really?")
    assert really["tools_used"] == []
    assert really["reply"] != facts
    assert "treat the city like they own" not in really["reply"]
    assert "Still here. Go on." not in really["reply"]
    assert "turquoise" not in really["reply"].lower()
    assert "screenshot" not in really["reply"].lower()
    assert "cats" in really["reply"].lower() or "Istanbul" in really["reply"]


@pytest.mark.asyncio
async def test_pasta_or_stir_fry_picks_one_no_stall(talk_ws, monkeypatch):
    async def boom(asked: str) -> str:
        raise AssertionError("or-choice must not call oneshot")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("Pasta or stir-fry tonight?")
    assert body["ok"] is True
    assert body["tools_used"] == []
    reply = body["reply"]
    assert "Still here. Go on." not in reply
    low = reply.lower()
    assert ("pasta" in low) ^ ("stir-fry" in low) or (
        "pasta" in low and "stir-fry" not in low
    )
    assert "pasta" in low
    assert "stir-fry" not in low
    assert reply.endswith(".")
    assert len(re.findall(r"[.!?]", reply)) == 1


def _assert_turkey_followup_is_opinion(reply: str, facts: str) -> None:
    assert reply != facts
    assert "treat the city like they own" not in reply
    assert "earthquake fault" not in reply
    assert "Still here. Go on." not in reply
    assert "What do you need?" not in reply
    assert "turquoise" not in reply.lower()
    assert len(reply.split()) <= 16
    bits = [p for p in re.split(r"[.!?]+", reply) if p.strip()]
    assert 1 <= len(bits) <= 2


@pytest.mark.asyncio
async def test_think_and_really_after_turkey_are_opinion_not_echo(
    talk_ws, monkeypatch
):
    from app.jarvis.talk_log import append_turn
    from app.jarvis.voice_ask import _TURKEY_INTERESTING, _talk_last_resort, run_voice_ask

    async def boom(asked: str) -> str:
        raise AssertionError(f"opinion follow-up must not call oneshot: {asked}")

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", boom)

    first = await run_voice_ask("Tell me something interesting about Turkey")
    facts = first["reply"]
    assert facts == _TURKEY_INTERESTING
    assert "Istanbul cats treat the city like they own it." in facts
    assert "earthquake fault" in facts
    append_turn(
        "you",
        "Tell me something interesting about Turkey",
        root=talk_ws,
        ts="2026-08-22T21:00:00Z",
    )
    append_turn("jarvis", facts, root=talk_ws, ts="2026-08-22T21:00:02Z")
    _assert_turkey_followup_is_opinion(
        _talk_last_resort("What do you think about that?"), facts
    )
    _assert_turkey_followup_is_opinion(_talk_last_resort("Really?"), facts)

    think = await run_voice_ask("What do you think about that?")
    assert think["ok"] is True
    assert think["tools_used"] == []
    _assert_turkey_followup_is_opinion(think["reply"], facts)

    really = await run_voice_ask("Really?")
    assert really["ok"] is True
    assert really["tools_used"] == []
    _assert_turkey_followup_is_opinion(really["reply"], facts)
    assert think["reply"] != really["reply"]


def test_close_all_and_still_see_are_not_chat_skip(talk_ws, monkeypatch):
    monkeypatch.setenv("JARVIS_HOST_OS", "linux")
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.virtual_pc import (
        after_see_allows_tool,
        after_see_must_act,
        goal_is_computer_job,
        wants_chat_only_desktop_skip,
        wants_close_all,
        wants_desktop_operate,
        wants_still_see,
    )

    close_all = (
        "Close all the apps running, like these Explorer and Error, close them as well."
    )
    still = "I can still see the file manager."
    click = "click OK"
    typed = "type hello"
    opened = "open the file manager"
    assert wants_close_all(close_all)
    assert wants_still_see(still)
    assert wants_still_see("No, I can still see the file manager.")
    assert wants_desktop_operate(close_all)
    assert wants_desktop_operate(still)
    assert wants_desktop_operate(click)
    assert wants_desktop_operate(typed)
    assert wants_desktop_operate(opened)
    assert after_see_must_act(close_all)
    assert after_see_must_act(still)
    assert after_see_must_act(click)
    assert after_see_must_act(typed)
    assert after_see_must_act(opened)
    assert not after_see_must_act("Really?")
    assert not wants_chat_only_desktop_skip(close_all)
    assert not wants_chat_only_desktop_skip(still)
    assert not wants_chat_only_desktop_skip(click)
    assert not wants_chat_only_desktop_skip(typed)
    assert not wants_chat_only_desktop_skip(opened)
    assert wants_chat_only_desktop_skip("Really?")
    assert wants_chat_only_desktop_skip("Pasta or stir-fry tonight?")
    assert wants_chat_only_desktop_skip("And plus 3?")
    for look in (
        "what do you see on the screen",
        "What do you see on the screen?",
        "what do you see on your screen",
        "Can you... what do you see on your screen?",
        "what do you see",
    ):
        assert not wants_chat_only_desktop_skip(look), look
        _n, _args, early = prepare_realtime_tool_call(
            "see_screen",
            {},
            user_goal=look,
        )
        assert early is None, look
    leftover, _args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "Really?"},
        user_goal="what do you see on the screen",
    )
    assert leftover == "see_screen"
    assert early is None
    assert goal_is_computer_job(close_all)
    assert goal_is_computer_job(still)
    for tool in ("see_screen", "keys"):
        _n, args, early = prepare_realtime_tool_call(tool, {}, user_goal=close_all)
        assert early is None, tool
        if tool == "see_screen":
            assert args.get("fresh") is True
            assert args.get("prefer_last") is False
        _n, _args, early = prepare_realtime_tool_call(tool, {}, user_goal=still)
        assert early is None, tool
        _n, _args, early = prepare_realtime_tool_call(tool, {}, user_goal="Really?")
        assert early is not None, tool
        assert early.get("skipped") is True, tool
        assert "last conversation" in str(early.get("reason") or "")
    for tool, goal in (
        ("click", click),
        ("type", typed),
        ("see_screen", opened),
        ("keys", still),
        ("click", still),
    ):
        _n, _args, early = prepare_realtime_tool_call(tool, {}, user_goal=goal)
        assert early is None, (tool, goal)
    assert after_see_allows_tool("click", close_all)
    assert after_see_allows_tool("keys", still)


def test_after_see_screen_click_keys_allowed(talk_ws, monkeypatch):
    monkeypatch.setenv("JARVIS_HOST_OS", "linux")
    from app.jarvis.capture import remember_last_look, reset_last_look
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.taint import ALLOW, gate
    from app.jarvis.tools import annotate_see_screen
    from app.jarvis.virtual_pc import after_see_allows_tool, after_see_must_act

    reset_last_look()
    remember_last_look(
        {
            "ok": True,
            "title": "Home - File Manager",
            "vision_description": "Thunar file manager is open. Recycle Bin icon.",
        }
    )
    goal = "click the Recycle Bin"
    assert after_see_must_act(goal)
    assert after_see_allows_tool("click", goal)
    assert after_see_allows_tool("keys", goal)
    looked = annotate_see_screen(
        {
            "ok": True,
            "vision_description": (
                "A turquoise desktop background fills the screenshot. "
                "Recycle Bin. Files. Chrome. Calculator."
            ),
        },
        goal,
    )
    assert looked.get("speak_now") is False
    assert looked.get("next_must") == ["click", "type", "keys"]
    assert "catalog" in str(looked.get("hint") or "").lower()
    name, args, early = prepare_realtime_tool_call(
        "click",
        {"x": 80, "y": 120},
        user_goal=goal,
    )
    assert name == "click"
    assert early is None
    name, args, early = prepare_realtime_tool_call(
        "keys",
        {"combo": "enter"},
        user_goal=goal,
    )
    assert name == "keys"
    assert early is None
    decision, _reason = gate("click", True, args={"x": 80, "y": 120}, user_goal=goal)
    assert decision == ALLOW
    decision, _reason = gate("keys", True, args={"combo": "enter"}, user_goal=goal)
    assert decision == ALLOW
    reset_last_look()


def test_spoken_computer_reply_is_one_short_line():
    from app.jarvis.voice_ask import spoken_job_line

    essay = (
        "A turquoise desktop background fills the screenshot. "
        "Recycle Bin. Files. Chrome. Calculator. Image Viewer. Terminal. "
        "Thunar file manager is still open on the left."
    )
    line = spoken_job_line(essay)
    low = line.lower()
    assert "turquoise" not in low
    assert "recycle" not in low
    assert "fills the screenshot" not in low
    assert "file manager" in low or "thunar" in low or line == "I looked."
    assert len(line.split()) <= 16
    assert len([p for p in re.split(r"[.!?]+", line) if p.strip()]) <= 1
    catalog = (
        "A turquoise desktop background fills the screenshot. "
        "Desktop icons: Recycle Bin, Files, Chrome."
    )
    empty = spoken_job_line(catalog)
    assert empty == "I looked."
    assert "desktop is clear" not in spoken_job_line(
        "The desktop is clear. All apps are now closed."
    ).lower()
