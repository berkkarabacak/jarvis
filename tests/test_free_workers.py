"""Free talk workers: Kimi first, Ox on 429/5xx. Mocked HTTP only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jarvis.model_router import (
    HELPER_DISPLAY_NAMES,
    KIMI_CODE_MODEL,
    KIMI_CODE_URL,
    OPENROUTER_CHAT_URL,
    OX_MODEL,
    chat,
    helper_display_name,
    list_free_workers,
    pick_free_worker,
    route_model,
    why_model_blob,
)
from app.jarvis.virtual_pc import goal_is_simple_talk, goal_is_virtual_pc_job


KIMI_TEST = "kimi-test-not-a-key"
OX_TEST = "or-test-not-a-key"


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
def no_worker_keys(monkeypatch):
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_pick_kimi_first_when_both_keys(no_worker_keys, monkeypatch):
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    first = pick_free_worker()
    assert first is not None
    assert first.key == "kimi"
    assert first.name == "Kimi"
    assert first.model == KIMI_CODE_MODEL
    assert first.url == KIMI_CODE_URL
    assert "moonshot" not in first.url
    names = [w.key for w in list_free_workers()]
    assert names == ["kimi", "ox"]
    assert helper_display_name() == "Quick"


def test_pick_ox_when_kimi_missing(no_worker_keys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    first = pick_free_worker()
    assert first is not None
    assert first.key == "ox"
    assert first.name == "Ox"
    assert first.model == OX_MODEL
    assert first.url == OPENROUTER_CHAT_URL
    assert helper_display_name() == "Ox"
    assert helper_display_name() in HELPER_DISPLAY_NAMES


def test_pick_kimi_alias_env(no_worker_keys, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", KIMI_TEST)
    first = pick_free_worker()
    assert first is not None
    assert first.key == "kimi"
    assert helper_display_name() == "Kimi"


def test_both_missing_is_none_and_catalog_ladder(no_worker_keys, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    monkeypatch.delenv("JARVIS_DISABLE_MODEL_ROUTER", raising=False)
    monkeypatch.delenv("JARVIS_MODEL_PREFERENCE", raising=False)
    from app.jarvis import settings_store
    from app.jarvis.model_router import reset_state_for_tests
    from app.jarvis.openrouter_leaders import cheap_catalog_ids, reset_leaders_cache_for_tests, snapshot_leaders

    settings_store.reset_cache()
    reset_state_for_tests(tmp_path)
    reset_leaders_cache_for_tests()
    assert pick_free_worker() is None
    assert list_free_workers() == []
    assert helper_display_name() is None
    choice = route_model(goal="How much free disk space do I have?", workspace_root=tmp_path)
    assert choice.task_class == "light"
    assert choice.model == cheap_catalog_ids(snapshot_leaders(), allow_free=True)[0]
    assert choice.metadata.get("free_worker") is None
    assert choice.metadata.get("helper_name") is None


def test_helper_name_never_raw_key_or_slug(no_worker_keys, monkeypatch):
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    name = helper_display_name()
    assert name in HELPER_DISPLAY_NAMES
    blob = json.dumps({"helper_name": name})
    assert KIMI_TEST not in blob
    assert OX_TEST not in blob
    assert "KIMI_CODE_API_KEY" not in blob
    assert "kimi-for-coding" not in blob
    assert "stealth/ox-alpha" not in blob
    assert "sk-" not in blob


@pytest.mark.asyncio
async def test_chat_uses_kimi_first(no_worker_keys, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)

    def handler(rec):
        assert "moonshot" not in rec["url"]
        assert "User-Agent" not in rec["headers"]
        assert "max_tokens" not in rec["json"]
        return _Res({"choices": [{"message": {"content": "Hello there"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    result = await chat([{"role": "user", "content": "hello"}])
    assert result.ok is True
    assert result.text == "Hello there"
    assert result.worker is not None
    assert result.worker.key == "kimi"
    assert len(posts) == 1
    assert posts[0]["url"] == KIMI_CODE_URL
    assert posts[0]["json"]["model"] == KIMI_CODE_MODEL
    assert "max_tokens" not in posts[0]["json"]
    assert "tools" not in posts[0]["json"]
    assert "User-Agent" not in posts[0]["headers"]
    assert KIMI_TEST not in json.dumps(posts[0]["json"])
    assert OX_TEST not in json.dumps(posts[0]["json"])


@pytest.mark.asyncio
async def test_chat_ox_on_kimi_429(no_worker_keys, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)

    def handler(rec):
        if "kimi.com" in rec["url"]:
            return _Res({"error": "busy"}, status_code=429)
        return _Res({"choices": [{"message": {"content": "4"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    result = await chat([{"role": "user", "content": "what is 2 plus 2"}])
    assert result.ok is True
    assert result.text == "4"
    assert result.worker is not None
    assert result.worker.key == "ox"
    assert [p["url"] for p in posts] == [KIMI_CODE_URL, OPENROUTER_CHAT_URL]
    assert posts[0]["json"]["model"] == KIMI_CODE_MODEL
    assert "max_tokens" not in posts[0]["json"]
    assert posts[1]["json"]["model"] == OX_MODEL
    assert posts[1]["json"]["reasoning"] == {"effort": "low", "exclude": True}
    assert all("moonshot" not in p["url"] for p in posts)
    assert all("User-Agent" not in p["headers"] for p in posts)
    bodies = json.dumps([p["json"] for p in posts])
    assert KIMI_TEST not in bodies
    assert OX_TEST not in bodies


@pytest.mark.asyncio
async def test_chat_ox_on_kimi_500(no_worker_keys, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("KIMI_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)

    def handler(rec):
        if "kimi.com" in rec["url"]:
            return _Res({"error": "down"}, status_code=503)
        return _Res({"choices": [{"message": {"content": "Paris"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    result = await chat([{"role": "user", "content": "capital of France"}])
    assert result.ok is True
    assert result.text == "Paris"
    assert result.worker is not None
    assert result.worker.key == "ox"
    assert len(posts) == 2
    assert posts[0]["url"] == KIMI_CODE_URL
    assert posts[1]["json"]["reasoning"]["exclude"] is True


@pytest.mark.asyncio
async def test_chat_does_not_fallback_on_401(no_worker_keys, monkeypatch):
    posts: list[dict] = []
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)

    def handler(rec):
        return _Res({"error": "no"}, status_code=401)

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    result = await chat([{"role": "user", "content": "hello"}])
    assert result.ok is False
    assert result.status == 401
    assert len(posts) == 1
    assert posts[0]["url"] == KIMI_CODE_URL


def test_kimi_only_talk_ready_is_browser_listen(no_worker_keys, monkeypatch):
    from app.jarvis.realtime import can_listen, listen_mode, realtime_available
    from app.jarvis.talk_auth import should_use_hosted_talk, talk_ready

    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    assert talk_ready() is True
    assert should_use_hosted_talk() is False
    assert realtime_available() is False
    assert can_listen() is True
    assert listen_mode() == "browser_speech"


def test_hello_math_fact_are_simple_talk_not_chrome():
    for phrase in ("hello", "what is 2 plus 2", "what is the capital of France"):
        assert goal_is_simple_talk(phrase), phrase
        assert not goal_is_virtual_pc_job(phrase), phrase


@pytest.mark.asyncio
async def test_typed_hello_math_fact_do_not_run_app(monkeypatch):
    launched: list[dict] = []
    planned: list[dict] = []

    class _Gw:
        def clear_taint(self, *args, **kwargs):
            return None

        def run(self, *args, **kwargs):
            raise AssertionError("tools must not run for typed hello/math/fact")

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _Gw())
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr("app.jarvis.voice_ask.sys.platform", "linux")

    async def stub_oneshot(asked: str) -> str:
        return {
            "hello": "Hello.",
            "what is 2 plus 2": "4",
            "what is the capital of France": "Paris",
        }.get(asked, "ok")

    from app.jarvis import computer as computer_mod

    monkeypatch.setattr("app.jarvis.voice_ask._simple_talk_oneshot", stub_oneshot)
    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True},
    )
    monkeypatch.setattr(
        computer_mod,
        "plan_linux_run_app",
        lambda args: planned.append(dict(args or {})) or {"ok": True, **dict(args or {})},
    )
    from app.jarvis.voice_ask import run_voice_ask

    hello = await run_voice_ask("hello")
    assert hello["ok"] is True
    assert hello["reply"] == "Hello."
    assert hello["tools_used"] == []

    math = await run_voice_ask("what is 2 plus 2")
    assert math["ok"] is True
    assert math["reply"] == "4"
    assert math["tools_used"] == []

    fact = await run_voice_ask("what is the capital of France")
    assert fact["ok"] is True
    assert fact["reply"] == "Paris"
    assert fact["tools_used"] == []

    assert launched == []
    assert planned == []


@pytest.mark.asyncio
async def test_oneshot_429_uses_second_worker_not_chrome(monkeypatch):
    posts: list[dict] = []
    launched: list[dict] = []

    class _Gw:
        def clear_taint(self, *args, **kwargs):
            return None

        def run(self, *args, **kwargs):
            raise AssertionError("tools must not run")

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _Gw())
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr("app.jarvis.voice_ask.sys.platform", "linux")

    def handler(rec):
        if "kimi.com" in rec["url"]:
            return _Res({"error": "busy"}, status_code=429)
        return _Res({"choices": [{"message": {"content": "Paris"}}]})

    monkeypatch.setattr(
        "app.jarvis.model_router.httpx.AsyncClient",
        lambda timeout=None: _Client(posts, handler, timeout=timeout),
    )
    from app.jarvis import computer as computer_mod

    monkeypatch.setattr(
        computer_mod,
        "linux_run_app",
        lambda plan: launched.append(plan) or {"ok": True},
    )
    from app.jarvis.voice_ask import run_voice_ask

    body = await run_voice_ask("what is the capital of France")
    assert launched == []
    assert body["ok"] is True
    assert body["reply"] == "Paris"
    assert body["tools_used"] == []
    assert [p["url"] for p in posts] == [KIMI_CODE_URL, OPENROUTER_CHAT_URL]
    assert all("moonshot" not in p["url"] for p in posts)
    assert KIMI_TEST not in json.dumps([p["json"] for p in posts])
    assert OX_TEST not in json.dumps([p["json"] for p in posts])


def test_settings_and_health_show_friendly_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("KIMI_CODE_API_KEY", KIMI_TEST)
    monkeypatch.setenv("OPENROUTER_API_KEY", OX_TEST)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app.jarvis import settings_store
    from app.jarvis.voice_ask import listen_health, public_talk_sheet

    settings_store.reset_cache()
    (tmp_path / "Memory").mkdir(parents=True, exist_ok=True)
    view = settings_store.public_view()
    sheet = public_talk_sheet()
    health = listen_health()
    assert view["helper_name"] == sheet["helper_name"] == health["helper_name"] == "Quick"
    assert health["talk_ready"] is True
    blob = json.dumps({"view": view, "sheet": sheet, "health": health})
    assert KIMI_TEST not in blob
    assert OX_TEST not in blob
    assert "kimi-for-coding-highspeed" not in blob
    assert view["helper_name"] in HELPER_DISPLAY_NAMES
    why = why_model_blob(
        route_model(goal="How much free disk space do I have?", workspace_root=tmp_path)
    )
    if "helper_name" in why:
        assert why["helper_name"] in HELPER_DISPLAY_NAMES


def test_choice_text_uses_content_not_reasoning_json():
    from app.jarvis.model_router import _choice_text

    assert _choice_text({"choices": [{"message": {"content": "Merhaba."}}]}) == "Merhaba."
    assert (
        _choice_text(
            {"choices": [{"message": {"content": "", "reasoning": "4"}}]}
        )
        == "4"
    )
    blob = _choice_text(
        {"choices": [{"message": {"content": "Paris", "reasoning": "think"}}]}
    )
    assert blob == "Paris"


def test_public_page_helper_label_is_friendly_word():
    page = (Path(__file__).resolve().parents[1] / "deploy" / "jarvis-public" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'friendly === "Quick"' in page
    assert 'friendly === "Kimi"' in page
    assert 'friendly === "Ox"' in page
    assert "moonshot" not in page.lower()
    assert "KIMI_CODE_API_KEY" not in page
    assert "KIMI_API_KEY" not in page
    assert "kimi-for-coding" not in page
