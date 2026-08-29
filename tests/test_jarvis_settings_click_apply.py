"""Public Talk Settings click bugs: Cost paints, voice maps, Allowed is real."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.talk_allow import (
    ASK_FIRST,
    REFUSE,
    normalize_allowed,
    overlay_decision,
    talk_allow_mode,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
SECRET = "test-secret-at-least-32-chars-long!!"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _js() -> str:
    return _page().split("<script>")[-1].rsplit("</script>", 1)[0]


def _fn(src: str, name: str) -> str:
    token = f"function {name}("
    start = src.index(token)
    rest = src[start:]
    nxt = rest.find("\n      function ", 1)
    nxt2 = rest.find("\n      async function ", 1)
    cuts = [i for i in (nxt, nxt2) if i > 0]
    return rest if not cuts else rest[: min(cuts)]


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


@pytest.fixture
async def public_client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=("203.0.113.10", 443))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def test_open_settings_calls_full_health_and_paint_sheet():
    js = _js()
    open_fn = _fn(js, "openSettings")
    health_fn = _fn(js, "health")
    assert "void health()" in open_fn
    assert "void loadTalkSettings()" in open_fn
    assert "health(true)" not in open_fn
    assert "lite ? \"?lite=1\" : \"\"" in health_fn
    assert "paintSheet(h)" in health_fn
    click = js.split("settingsBtn.addEventListener(\"click\"", 1)[1].split("});", 1)[0]
    assert "openSettings()" in click
    assert "health(true)" not in click


def test_cost_paints_after_open_settings_full_health_not_lite():
    """openSettings → full health → paintSheet writes spent/left. Lite leaves dashes."""
    js = _js()
    money_fn = _fn(js, "money")
    as_money_fn = _fn(js, "asMoney")
    paint_fn = _fn(js, "paintSheet")
    script = f"""
    const spentToday = {{ textContent: "—" }};
    const spentTodayRow = {{ hidden: true }};
    const spentMonth = {{ textContent: "—" }};
    const spentMonthNote = {{ hidden: true, textContent: "" }};
    const spentLeft = {{ textContent: "—" }};
    const spendMeter = {{ hidden: true }};
    const spendMeterFill = {{ style: {{ width: "0" }} }};
    const modelEl = {{ textContent: "" }};
    const modelNameEl = {{ textContent: "Everyday" }};
    const modelPicksEl = null;
    const helperPicksEl = null;
    const qualityEl = null;
    const MODEL_NAMES = {{}};
    const prefs = {{ quality: "", helper: "", modelSpeed: "" }};
    function savePrefs() {{}}
    function paintPicks() {{}}
    function paintHelperPicks() {{}}
    function helperLabel() {{ return ""; }}
    {money_fn}
    {as_money_fn}
    {paint_fn}
    paintSheet({{ can_listen: true, realtime: true }});
    if (spentMonth.textContent !== "—" || spentLeft.textContent !== "—") process.exit(2);
    paintSheet({{
      spent_today_usd: 0.4,
      spent_month_usd: 1.25,
      remaining_budget_usd: 3.75,
      monthly_budget_usd: 5
    }});
    if (spentMonth.textContent !== "$1.25") process.exit(3);
    if (spentLeft.textContent !== "$3.75") process.exit(4);
    if (spentToday.textContent !== "$0.40") process.exit(5);
    process.stdout.write(JSON.stringify({{
      month: spentMonth.textContent,
      left: spentLeft.textContent,
      today: spentToday.textContent
    }}));
    """
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    painted = json.loads(result.stdout)
    assert painted["month"] == "$1.25"
    assert painted["left"] == "$3.75"
    assert painted["today"] == "$0.40"


def test_voice_click_maps_and_puts_realtime_voice():
    page = _page()
    js = _js()
    apply_fn = _fn(js, "applyLiveVoice")
    voice_fn = _fn(js, "realtimeVoice")
    click = js.split("voicePicksEl.querySelectorAll(\"[data-voice]\")", 1)[1]
    click = click.split("talkSpeedEl", 1)[0]
    assert "TALK_VOICES" in js
    assert "warm" in js and "clear" in js and "deep" in js
    assert "applyLiveVoice()" in click
    assert "saveTalkSettings({ realtime_voice: realtimeVoice() })" in click
    assert "session.update" in apply_fn
    assert "audio: { output: { voice: realtimeVoice() } }" in apply_fn
    assert "TALK_VOICES[prefs.voice]" in voice_fn
    assert "{ text: text, voice: prefs.voice }" in js
    assert "voice: prefs.voice" in js
    visible = page.split("<script>", 1)[0]
    assert "marin" not in visible.lower()
    script = """
    const TALK_VOICES = { warm: "marin", clear: "alloy", deep: "echo" };
    function realtimeVoice(voice) { return TALK_VOICES[voice] || TALK_VOICES.warm; }
    const sent = [];
    const dc = { readyState: "open", send: function (s) { sent.push(JSON.parse(s)); } };
    function applyLiveVoice(voice) {
      dc.send(JSON.stringify({
        type: "session.update",
        session: { type: "realtime", audio: { output: { voice: realtimeVoice(voice) } } }
      }));
    }
    applyLiveVoice("warm");
    applyLiveVoice("clear");
    applyLiveVoice("deep");
    if (sent[0].session.audio.output.voice !== "marin") process.exit(2);
    if (sent[1].session.audio.output.voice !== "alloy") process.exit(3);
    if (sent[2].session.audio.output.voice !== "echo") process.exit(4);
    process.stdout.write(JSON.stringify(sent.map((e) => e.session.audio.output.voice)));
    """
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == ["marin", "alloy", "echo"]


def test_allowed_is_enforced_or_not_shown():
    page = _page()
    js = _js()
    computer_html = page.split('id="tab-computer"', 1)[1].split('id="tab-about"', 1)[0]
    assert 'data-permission="locked"' in computer_html
    assert 'data-permission="personal"' in computer_html
    assert 'data-permission="power"' in computer_html
    assert "saveTalkSettings({ permission_profile: prefs.permissionProfile })" in js
    assert "function publicTalkAllowed" in js
    assert "allowed: publicTalkAllowed()" in js
    assert js.count("allowed: publicTalkAllowed()") >= 2
    assert "/api/jarvis/ask" in js
    assert "/api/jarvis/tools/run" in js
    assert 'data-allow="docs"' not in page
    assert 'data-allow="buy"' not in page


def test_talk_allow_mapping_and_overlay():
    from app.jarvis.gateway import GatewayDecision

    assert normalize_allowed({"apps": "NO", "docs": "yes", "buy": "ask"}) == {"apps": "no"}
    assert talk_allow_mode("run_app", {"apps": "no"}) == "no"
    assert talk_allow_mode("write_file", {"files": "ask"}) == "ask"
    assert talk_allow_mode("see_screen", {"apps": "no"}) is None
    yes = GatewayDecision(True, False, "L3", "ok")
    denied = overlay_decision("run_app", yes, allowed={"apps": "no"})
    assert denied.allowed is False
    assert denied.needs_confirm is False
    assert denied.reason == REFUSE
    ask = overlay_decision("run_app", yes, allowed={"apps": "ask"})
    assert ask.needs_confirm is True
    assert ask.reason == ASK_FIRST
    ok = overlay_decision("run_app", yes, allowed={"apps": "yes"})
    assert ok.allowed is True
    assert ok.needs_confirm is False


@pytest.mark.asyncio
async def test_tools_run_honors_public_allowed(public_client):
    blocked = await public_client.post(
        "/api/jarvis/tools/run",
        json={
            "name": "run_app",
            "arguments": {"target": "chrome", "url": "https://example.com"},
            "allowed": {"apps": "no"},
        },
    )
    assert blocked.status_code == 200
    body = blocked.json()
    result = body.get("result") or {}
    assert result.get("ok") is False
    assert REFUSE in (result.get("error") or result.get("message") or "")
    assert "Traceback" not in blocked.text
    assert SECRET not in blocked.text

    asked = await public_client.post(
        "/api/jarvis/tools/run",
        json={
            "name": "write_file",
            "arguments": {"path": "note.txt", "text": "hi"},
            "allowed": {"files": "ask"},
        },
    )
    assert asked.status_code == 200
    ask_body = asked.json().get("result") or {}
    assert ask_body.get("needs_confirm") is True
    assert "nonce_code" not in (asked.json().get("result") or {})

    prefixed = await public_client.post(
        "/jarvis/api/jarvis/ask",
        json={"text": "hello", "allowed": {"apps": "no", "files": "ask", "computer": "no"}},
    )
    assert prefixed.status_code == 200
    assert prefixed.json().get("reply")
    assert SECRET not in prefixed.text


def test_memory_tab_does_not_invent():
    js = _js()
    mem = _fn(js, "loadMemoryTab")
    show = _fn(js, "showSettingsTab")
    assert "/api/jarvis/talk/last" in mem
    assert "data.turns" in mem
    assert 'name === "about"' in show
    assert "14 Rose Lane" not in _page()
    assert "Dr Aydın" not in _page()
    assert "StreamBox" not in _page()
    assert "He has not saved anything here yet." in _page()
    assert 'id="tab-about"' in _page()
    assert 'id="memory-log"' in _page()


def test_computer_look_and_permission_put():
    js = _js()
    look_click = js.split("lookPicksEl.querySelectorAll(\"[data-look]\")", 1)[1]
    look_click = look_click.split("permissionPicksEl", 1)[0]
    assert "saveTalkSettings({ look_speed: look })" in look_click
    perm_click = js.split("permissionPicksEl.querySelectorAll(\"[data-permission]\")", 1)[1]
    assert "saveTalkSettings({ permission_profile: prefs.permissionProfile })" in perm_click
    assert "applyPicture()" in js
    assert "/screen?picture=" in js
