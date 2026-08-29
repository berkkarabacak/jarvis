"""Public /jarvis/ is a live chat page, not a download-only stub."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
NGINX = ROOT / "deploy" / "nginx-jarvis-public.fragment"

def _assert_no_secret_values(text: str) -> None:
    assert "sk-or-" not in text
    assert "sk-proj-" not in text
    assert "test-secret-at-least-32-chars-long!!" not in text
    assert "xai-test-key" not in text
    assert "operator-test-key" not in text
    assert "OPENAI_API_KEY" not in text
    assert "OPENROUTER_API_KEY" not in text
    assert "API_SECRET" not in text


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
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
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.delenv("JARVIS_SETUP_EXE_PATH", raising=False)

    from app.config import get_settings
    from app.jarvis import settings_store
    import app.jarvis.gateway as gw

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()


def test_public_page_source_is_chat_and_talk():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    assert "<title>Jarvis</title>" in page
    assert 'aria-label="Jarvis"' not in page
    assert ">Jarvis</h1>" not in page
    assert 'id="wall"' not in page
    assert 'id="pc"' in page
    assert "/jarvis/screen" in page
    assert 'aria-label="Screen"' in page
    assert "@keyframes drift" not in page
    assert "@keyframes hue" not in page
    assert "@keyframes listen-pulse" in page
    assert "@keyframes voice-breathe" not in page
    assert 'class="voice-bar"' not in page
    assert 'id="orb"' in page
    assert "/jarvis/voice-orb.js" in page
    assert "JarvisVoiceOrb" in page
    assert "requestAnimationFrame" in (ROOT / "deploy" / "jarvis-public" / "voice-orb.js").read_text(encoding="utf-8")
    assert 'id="log"' in page
    assert 'id="box"' in page
    assert 'id="mic"' in page
    assert 'id="more"' in page
    assert 'aria-label="Talk"' not in page
    assert 'id="go"' in page
    assert 'id="mute-me"' in page
    assert 'id="mute-him"' in page
    assert 'aria-label="Mute me"' in page
    assert 'aria-label="Mute him"' in page
    assert "if (muteMe) return" in page
    assert "if (muteHim) return" in page
    assert "stopListen" in page
    assert "stopVoice" in page
    assert 'href="/jarvis/download/Jarvis-Setup.exe"' in page
    assert 'aria-label="Get app"' in page
    assert "Get app" in page
    assert "Talk" in page
    assert "Send" in page
    assert "Settings" in page
    assert "Mute me" in page
    assert "Mute him" in page
    assert "Screen" in page
    assert 'id="settings"' in page
    assert 'id="settings-btn"' in page
    assert "Spent today" in page
    assert "Spent this month" in page
    assert 'id="model"' in page
    assert "Fast" in page
    assert "Normal" in page
    assert "Careful" in page
    assert "Quick" in page
    assert "Everyday" in page
    assert "Deep" in page
    assert 'content: "You"' not in page
    assert 'content: "Jarvis"' not in page
    assert 'interimResults = true' in page
    assert "rec.continuous = true" in page
    assert "rec.continuous = false" not in page
    assert "startListen" in page
    assert "rec.onend" in page
    assert "if (!muteMe) startListen()" in page
    assert "if (muteMe) stopListen()" in page
    assert "/api/jarvis/ask" in page
    assert "/api/jarvis/speak" in page
    assert "/jarvis/hello/en.mp3" not in page
    assert "/jarvis/hello/tr.mp3" not in page
    assert 'id="hello-en"' not in page
    assert 'id="hello-tr"' not in page
    assert "speakFirstHello" not in page
    assert "/api/jarvis/health" in page
    assert "/api/jarvis/realtime/session" in page
    assert "function startTalk" in page
    assert "function startBrowserTalk" in page
    assert "RTCPeerConnection" in page
    assert "/api/jarvis/settings" in page
    assert "Who does the extra work" in page
    assert "helper_models" in page
    assert "helper-picks" in page
    assert "model_lock" in page
    assert "Can't talk right now" in page
    assert "Can't hear you. Type here instead." in page
    assert "SpeechRecognition" in page
    assert "new Audio(" in page
    assert "speechSynthesis" not in page
    assert "Open it. Talk." not in page
    assert "api key" not in low
    assert "openrouter" not in low
    assert "OPENAI_API_KEY" not in page
    assert "sk-or-" not in page
    assert "sk-" not in page
    assert "play.google.com" not in page
    assert "App Store" not in page
    assert "iOS" not in page
    assert "innerHTML" not in page
    assert "AbortController" in page
    assert "12000" in page
    assert "30000" in page
    assert "askAbortMs" in page
    assert "Look at the screen." in page
    abort_fn = page.split("function askAbortMs", 1)[1].split("async function ask", 1)[0]
    assert "tell" in abort_fn or "what do you see" in abort_fn
    assert "read" in abort_fn
    assert "click" in abort_fn
    assert "type" in abort_fn
    assert "what do you see" in abort_fn
    assert "30000" in abort_fn
    assert "12000" in abort_fn
    assert "180000" in abort_fn
    assert "spawn_child" in abort_fn
    assert "what's on" in abort_fn or "what'?s on" in abort_fn
    assert "function askTextMax" in page
    assert "return 2000" in page.split("function askTextMax", 1)[1].split("function askAbortMs", 1)[0]
    assert 'maxlength="2000"' in page
    send_user = page.split("function sendUserText", 1)[1].split("\n      function ", 1)[0]
    assert "slice(0, 400)" in send_user
    _assert_no_secret_values(page)


def test_public_talk_two_button_idle_chrome():
    page = PAGE.read_text(encoding="utf-8")
    chrome = page.split("<body>", 1)[1].split('<div id="stage">', 1)[0]
    assert 'id="top"' not in page
    assert 'class="word"' not in page
    assert 'aria-label="Jarvis"' not in page
    assert "Jarvis" not in chrome
    assert "LIVE" not in chrome
    assert ">Listening<" not in chrome.split('id="sr-status"', 1)[0]
    assert 'id="mic"' in chrome
    assert 'id="more"' in chrome
    assert 'class="voice-bar"' not in chrome
    assert 'class="voice-bars"' not in chrome
    assert 'id="orb"' in chrome
    assert "/jarvis/voice-orb.js" in page
    assert "JarvisVoiceOrb.mount" in page
    assert 'id="more-cluster" hidden' in chrome
    assert 'id="mute-him"' in chrome
    assert 'id="chat-btn"' in chrome
    assert 'id="settings-btn"' in chrome
    assert 'id="mute-me"' in chrome
    assert 'data-mute="me" hidden' in chrome
    idle_buttons = [part.split(">", 1)[0] for part in chrome.split("<button")[1:]]
    visible = [btn for btn in idle_buttons if "hidden" not in btn and 'id="mute-him"' not in btn and 'id="chat-btn"' not in btn and 'id="settings-btn"' not in btn]
    assert len(visible) == 2
    assert any('id="mic"' in btn for btn in visible)
    assert any('id="more"' in btn for btn in visible)
    assert 'aria-label="Mute me"' in chrome
    assert 'aria-label="More"' in chrome
    assert 'aria-label="Talk"' not in page
    assert "@keyframes voice-breathe" not in page
    assert "function bindChromeDrag" in page
    assert "prefs.orbPos" in page
    assert "prefs.morePos" in page
    assert "onMuteMe()" in page
    assert "function orbTalkState" in page
    assert 'return "idle"' in page
    assert 'return "speaking"' in page
    assert 'return "processing"' in page
    assert 'return "listening"' in page


def test_public_talk_aura_orb_sources_and_script():
    page = PAGE.read_text(encoding="utf-8")
    orb_js = ROOT / "deploy" / "jarvis-public" / "voice-orb.js"
    orb_dir = ROOT / "deploy" / "jarvis-public" / "voice-orb"
    js = orb_js.read_text(encoding="utf-8")
    assert orb_js.is_file()
    assert (orb_dir / "LICENSE").is_file()
    assert (orb_dir / "NOTICE").is_file()
    assert (orb_dir / "types.ts").is_file()
    assert (orb_dir / "constants.ts").is_file()
    assert (orb_dir / "components" / "VoiceOrb.tsx").is_file()
    assert (orb_dir / "components" / "Canvas2DOrb.tsx").is_file()
    assert (orb_dir / "components" / "OrbShaders.ts").is_file()
    license_text = (orb_dir / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    for rel in (
        "types.ts",
        "constants.ts",
        "components/VoiceOrb.tsx",
        "components/Canvas2DOrb.tsx",
        "components/OrbShaders.ts",
    ):
        text = (orb_dir / rel).read_text(encoding="utf-8")
        assert "Apache License, Version 2.0" in text
        assert "Ashish-Soni08/aura" in text
    assert "Apache License 2.0" in js
    assert "Ashish-Soni08/aura" in js
    assert "JarvisVoiceOrb" in js
    assert "startWebGL" in js
    assert "startCanvas2D" in js
    assert "isWebGLAvailable" in js
    assert "convai" not in js.lower()
    assert "unpkg.com" not in js
    assert "elevenlabs.io" not in js.lower()
    assert 'id="orb"' in page
    assert 'src="/jarvis/voice-orb.js"' in page
    assert 'class="voice-bar"' not in page
    assert "function simplex3" in js
    assert "function fbm3" in js
    assert "paintAuraSphere" in js
    _assert_no_secret_values(js)
    _assert_no_secret_values(page)


def test_public_talk_orb_is_aura_sphere_not_stain():
    page = PAGE.read_text(encoding="utf-8")
    js = (ROOT / "deploy" / "jarvis-public" / "voice-orb.js").read_text(encoding="utf-8")
    mic_css = page.split("#mic {", 1)[1].split("}", 1)[0]
    assert "radial-gradient" not in mic_css
    assert "rgba(8, 10, 16" not in page
    assert "background: transparent" in mic_css
    assert "box-shadow: none" in mic_css
    assert '#mic[data-voice="idle"]' not in page
    orb_css = page.split("#orb {", 1)[1].split("}", 1)[0]
    assert "width: 72px" in orb_css
    assert "height: 72px" in orb_css
    assert "function simplex3" in js
    assert "function fbm3" in js
    sphere = js.split("function paintAuraSphere", 1)[1].split("function startCanvas2D", 1)[0]
    assert "simplex" in js.lower()
    assert "fbm3(" in sphere
    assert "nx * cur.intensity * 1.5" in sphere
    two_d = js.split("function startCanvas2D", 1)[1].split("function mount", 1)[0]
    assert "paintAuraSphere" in two_d
    assert "destination-over" in two_d
    assert 'globalCompositeOperation = "lighter"' not in two_d
    assert "keepTinted" in js
    assert "liftColor" not in js
    assert 'rgba(" + gR + "," + gG + "," + gB + ",0.15)"' not in js
    assert "wide &&" not in js
    assert ">= 140" not in js
    assert "CANVAS2D_MAX_HOST_PX = 96" in js
    mount = js.split("function mount", 1)[1]
    assert "hostPx <= CANVAS2D_MAX_HOST_PX" in mount
    assert "isWebGLAvailable()" in mount
    assert 'renderer: "canvas2d"' in page
    assert "float: 2.35" not in js
    assert "float: 1.8" in js
    assert "0.34 / max(luma" not in js
    assert "luma < 0.34" not in js
    assert "#431407" not in js
    assert "#064E3B" not in js
    assert "#38BDF8" in js
    assert "#818CF8" in js
    assert "#8B5CF6" in js
    assert "#C084FC" in js
    assert "#312E81" in js


def test_public_talk_his_computer_v2_chrome_slice():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    assert 'id="top"' not in page
    assert 'id="mic"' in page
    assert 'id="more"' in page
    assert "border-bottom: 1px solid var(--border)" in page
    assert "--ink: #201e1d" in page
    assert "--page: #f8f7f7" in page
    assert "--border: #d7d3d3" in page
    assert "--muted: #605d5d" in page
    assert "--accent: #ec3013" in page
    assert "--live-bg: #fff2ef" in page
    assert "--listen-bg: #f0f6f0" in page
    assert "font-size: 17px" in page
    assert 'id="listen-chip"' in page
    assert 'id="sr-status" hidden' in page
    assert "Listening" in page
    assert "Paused" in page
    assert "Mic off" in page
    assert 'id="live-chip"' not in page
    assert "LIVE" not in page
    assert 'id="doing"' in page
    assert "Ready" in page
    assert "@keyframes pulseRing" in page
    assert "@keyframes voice-breathe" not in page
    assert 'id="orb"' in page
    assert "prefers-reduced-motion" in page
    cluster = page.split('id="more-cluster"', 1)[1].split("</div>", 1)[0]
    assert ">Talk<" not in cluster
    assert ">Mute me<" not in cluster
    assert ">Chat<" not in cluster
    assert ">Settings<" not in cluster
    assert 'title="Mute him"' in cluster
    assert 'aria-label="Mute him"' in cluster
    assert 'title="Chat"' in cluster
    assert 'aria-label="Chat"' in cluster
    assert 'title="Settings"' in cluster
    assert 'aria-label="Settings"' in cluster
    assert 'class="bar-div"' not in page
    assert "width: 44px" in page
    assert "width: 36px" in page
    assert 'id="stage"' in page
    assert 'id="pc"' in page
    assert 'id="chat"' in page
    assert 'id="chat" hidden' in page
    assert 'id="chat-hide"' in page
    assert 'aria-label="Hide"' in page
    stage = page.split('<div id="stage">', 1)[1].split('<div id="settings"', 1)[0]
    assert 'id="pc"' in stage
    assert 'id="chat"' in stage
    assert stage.find('id="pc"') < stage.find('id="chat"')
    chat_css = page[page.find("#chat {") : page.find("#chat[hidden]")]
    assert "position: fixed" in chat_css
    assert "z-index: 5" in chat_css
    assert 'content: "You"' not in page
    assert 'content: "Jarvis"' not in page
    assert "font-size: 17px" in page
    assert "16px 16px 4px 16px" in page
    assert "16px 16px 16px 4px" in page
    assert "pinLog" in page
    assert 'id="drawer-mic"' not in page
    assert 'id="box"' in page
    assert 'id="go"' in page
    assert 'aria-label="Screen"' in page
    assert "/jarvis/screen" in page
    assert "height: 62px" in page
    assert 'id="settings-back"' in page
    assert "Back" in page
    assert "font: 700 17px/1" in page
    assert "font-size: 19px" in page
    assert "width: 46px" in page
    assert 'id="settings-rail"' in page
    assert "flex: 0 0 228px" in page
    assert "SETTINGS_TABS" in page
    assert '{ id: "cost", label: "Cost" }' in page
    assert '{ id: "model", label: "Model" }' in page
    assert '{ id: "speed", label: "Speed" }' in page
    assert '{ id: "voice", label: "Voice" }' in page
    assert '{ id: "allowed", label: "Allowed" }' in page
    assert '{ id: "memory", label: "Memory" }' in page
    assert '{ id: "screen", label: "Screen" }' in page
    assert '{ id: "about", label: "About" }' in page
    assert "What he has cost you this month." in page
    assert "Which brain he uses. No codes, no keys." in page
    assert "How fast he works and when he checks with you." in page
    assert "Quick" in page
    assert "Everyday" in page
    assert "Deep" in page
    assert "Fast" in page
    assert "Normal" in page
    assert "Careful" in page
    assert "In use now" in page
    assert "font-size: 40px" in page
    assert "Spent this month" in page
    assert "Spent today" in page
    assert "Left" in page
    assert "$2.40" not in page
    assert "Talking / Watching" not in page
    assert "Where it went" not in page
    assert 'id="spent-today">—</span>' in page
    assert 'id="spent-month">—</span>' in page
    assert 'id="spent-left">—</span>' in page
    assert "spent_today_usd" in page
    assert "spent_month_usd" in page
    assert "remaining_budget_usd" in page
    assert "monthly_budget_usd" in page
    assert "quality_vs_price" in page
    assert "model_speed" in page
    assert "/api/jarvis/settings" in page
    assert "Who does the extra work" in page
    assert "helper_models" in page
    assert "helper-picks" in page
    assert "deepseek/" not in low
    assert "sk-" not in page
    assert "api key" not in low
    assert "OPENAI_API_KEY" not in page
    assert "support.js" not in page
    assert "_ds" not in page
    assert "ceo.html" not in page
    assert "jarvis-screen.html" not in low
    script = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    assert "const payload =" in script
    assert script.count("const payload =") == 1
    _assert_no_secret_values(page)


def test_public_talk_settings_remaining_tabs():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    tabs = page.split("SETTINGS_TABS", 1)[1].split("];", 1)[0]
    assert "Cost" in tabs
    assert "Model" in tabs
    assert "Speed" in tabs
    assert "Voice" in tabs
    assert "Allowed" in tabs
    assert "Memory" in tabs
    assert "Screen" in tabs
    assert "About" in tabs
    assert "How he sounds and how he hears you." in page
    assert "Soft and friendly." in page
    assert "Plain and even." in page
    assert "Low and calm." in page
    assert "Talking speed" in page
    assert 'data-talk-speed="slow"' in page
    assert 'data-talk-speed="normal"' in page
    assert 'data-talk-speed="quick"' in page
    assert "Jarvis…" in page
    assert "Keeps listening after you speak" in page
    assert "What he may do on his own computer." in page
    assert "Open apps and websites" in page
    assert "Browser, mail, photos" in page
    assert "Read your documents" in page
    assert "Only the folder you share" in page
    assert "Save and change files" in page
    assert "Lists, letters, forms" in page
    assert "Buy things or send messages" in page
    assert "He always says the amount first" in page
    assert "Change the computer itself" in page
    assert "Installing, deleting, settings" in page
    assert 'data-val="yes"' in page
    assert 'data-val="ask"' in page
    assert 'data-val="no"' in page
    assert "--no: #ae1800" in page
    assert "What he remembers about you." in page
    assert "He has not saved anything here yet." in page
    assert "14 Rose Lane" not in page
    assert "Dr Aydın" not in page
    assert "Dr Aydin" not in page
    assert "StreamBox" not in page
    assert "Forget everything" not in page
    assert "How his computer looks to you." in page
    assert "Text size everywhere" in page
    assert "text-size-val" in page
    assert "0.9" in page
    assert "Math.min(1.4" in page
    assert "jarvis.talk.prefs" in page
    assert "--type-scale" in page
    assert "Sharp costs a little more." in page
    assert 'data-picture="clear"' in page
    assert 'data-picture="smooth"' in page
    assert "Show what he types on screen" not in page
    assert "Dim his screen in the evening" not in page
    assert "This app and where to get help." in page
    assert "His computer" in page
    assert "Linux" in page
    assert "Windows" not in page
    assert "Keys or codes needed" in page
    assert "None</span>" in page
    about = page.split("This app and where to get help.", 1)[1].split("<script>", 1)[0]
    assert "Version" not in about
    assert "1.4" not in about
    assert "Call for help" not in page
    assert 'href="/jarvis/download/Jarvis-Setup.exe"' in page
    assert "$2.40" not in page
    assert "/api/jarvis/settings" in page
    assert "Who does the extra work" in page
    assert "spent_today_usd" in page
    assert "spent_month_usd" in page
    assert "{ text: text, voice: prefs.voice }" in page
    assert "voice: prefs.voice" in page
    assert "locale: TEST_FORCE_ENGLISH ? \"en\" : (navigator.language || \"\").trim()" in page
    assert "const TEST_FORCE_ENGLISH = true" in page
    assert "timeZone" in page
    visible = page.split("<script>", 1)[0].lower()
    assert "marin" not in visible
    assert "scottish" not in low
    assert "deepseek/" not in low
    assert "sk-" not in page
    assert "api key" not in low
    assert "OPENAI_API_KEY" not in page
    assert "innerHTML" not in page
    _assert_no_secret_values(page)


def test_public_page_always_on_listen_session():
    page = PAGE.read_text(encoding="utf-8")
    assert "rec.continuous = true" in page or "continuous = true" in page
    assert "rec.continuous = false" not in page
    assert "startListen" in page
    assert "rec.onend" in page
    onend = page[page.find("rec.onend") : page.find("rec.onend") + 280]
    assert "startListen()" in onend
    assert "muteMe" in onend
    ended = page[page.find("audio.onended") : page.find("audio.onended") + 220]
    assert "startListen()" in ended or "if (!muteMe) startListen()" in page
    assert "if (!muteMe) startListen()" in page
    assert "if (muteMe) stopListen()" in page
    stop_line = next(ln for ln in page.splitlines() if "if (muteMe) stopListen()" in ln)
    assert "startListen" not in stop_line
    tail = page.rsplit("paintMute();", 1)[-1]
    assert "startListen()" not in tail
    assert "void bootTalk()" in tail
    assert "Can't hear you. Type here instead." in page
    assert "if (!Rec())" in page
    assert "hearFail()" in page
    assert "canListen = false" in page
    assert "setLiveYou" in page
    assert "interimResults = true" in page
    assert "12000" in page
    _assert_no_secret_values(page)


def test_public_page_auto_starts_talk_and_first_click_anywhere():
    page = PAGE.read_text(encoding="utf-8")
    assert 'const MIC_OK_KEY = "jarvis.talk.micOk"' in page
    assert "function rememberMicGranted" in page
    assert "function rememberedMicGranted" in page
    assert "function micAlreadyAllowed" in page
    assert "function bootTalk" in page
    assert "function armFirstClickTalk" in page
    assert "function isTalkExemptTarget" in page
    assert 'navigator.permissions.query({ name: "microphone" })' in page
    assert 'st.state === "granted"' in page
    assert "localStorage.setItem(MIC_OK_KEY, \"1\")" in page
    assert "localStorage.getItem(MIC_OK_KEY)" in page
    assert "void startTalk()" in page
    assert "armFirstClickTalk()" in page
    assert "void bootTalk()" in page
    assert "document.addEventListener(\"click\", firstClickTalk, true)" in page
    assert 'el.closest("#settings, #settings-btn")' in page
    assert 'el.closest("a[href]")' in page
    assert 'el.closest("input, textarea, select, option, label")' in page
    assert 'el.closest("[data-mute=\\"me\\"]")' in page or "data-mute=\"me\"" in page
    assert 'id="talk-catch"' in page
    assert "if (muteMe) stopListen()" in page
    start_talk = page.split("async function startTalk()", 1)[1].split("function askAbortMs", 1)[0]
    assert "if (duplexLive)" in start_talk
    assert "return;" in start_talk
    assert "startListen()" in start_talk
    assert "prefetchSession()" in start_talk
    assert "void connectRealtime()" in start_talk
    assert "speakFirstHello" not in start_talk
    assert "/jarvis/hello/" not in start_talk
    assert "/api/jarvis/health" not in start_talk
    assert start_talk.index("prefetchSession()") < start_talk.index("connectRealtime")
    assert start_talk.index("connectRealtime") < start_talk.index("startListen()")
    assert 'rec.lang = "es-ES"' not in page
    assert "es-ES" not in page
    _assert_no_secret_values(page)
    low = page.lower()
    assert "api key" not in low
    assert "openrouter" not in low
    assert "OPENAI_API_KEY" not in page


def test_site_nginx_keeps_download_and_proxies_chat():
    text = NGINX.read_text(encoding="utf-8")
    assert "location ^~ /jarvis/download/" in text
    assert "alias /var/www/jarvis/download/;" in text
    assert "location /jarvis/" in text
    assert "proxy_pass http://127.0.0.1:8895/jarvis/;" in text
    assert "location ^~ /jarvis/novnc/" in text
    assert "proxy_pass http://127.0.0.1:6080/;" in text
    assert "listen 0.0.0.0:6080" not in text
    assert "proxy_pass http://0.0.0.0:6080" not in text
    assert "proxy_pass http://127.0.0.1:8895/;" not in text


@pytest.mark.asyncio
async def test_app_serves_public_chat_page(client):
    r = await client.get("/jarvis/", follow_redirects=True)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    html = r.text
    assert 'id="log"' in html
    assert 'id="box"' in html
    assert 'id="mic"' in html
    assert 'id="orb"' in html
    assert 'id="mute-me"' in html
    assert 'id="mute-him"' in html
    assert 'src="/jarvis/voice-orb.js"' in html
    orb_js = await client.get("/jarvis/voice-orb.js")
    assert orb_js.status_code == 200
    assert "JarvisVoiceOrb" in orb_js.text
    assert "text/javascript" in orb_js.headers.get("content-type", "")
    assert 'id="wall"' not in html
    assert 'id="pc"' in html
    assert 'id="chat"' in html
    assert 'id="settings"' in html
    assert "Settings" in html
    assert "Spent today" in html
    assert "How he sounds and how he hears you." in html
    assert "He has not saved anything here yet." in html
    assert "Linux" in html
    assert "Get app" in html
    assert "/jarvis/screen" in html
    assert 'href="/jarvis/download/Jarvis-Setup.exe"' in html
    assert "/api/jarvis/ask" in html
    assert "/api/jarvis/speak" in html
    assert "/jarvis/hello/en.mp3" not in html
    assert "/jarvis/hello/tr.mp3" not in html
    assert 'id="hello-en"' not in html
    assert 'id="hello-tr"' not in html
    assert "speakFirstHello" not in html
    assert "/api/jarvis/realtime/session" in html
    assert ">Jarvis</h1>" not in html
    assert "API key" not in html
    assert "OpenRouter" not in html
    assert "OPENAI_API_KEY" not in html
    assert "AbortController" in html
    assert "speechSynthesis" not in html
    assert 'interimResults = true' in html
    assert "rec.continuous = true" in html
    assert "rec.continuous = false" not in html
    assert "startListen" in html
    assert "if (!muteMe) startListen()" in html
    assert "if (muteMe) stopListen()" in html
    assert "@keyframes listen-pulse" in html
    _assert_no_secret_values(html)


def test_public_first_open_defers_catalog_screen_and_fonts():
    page = PAGE.read_text(encoding="utf-8")
    start_talk = page.split("async function startTalk()", 1)[1].split("function askAbortMs", 1)[0]
    assert "startListen()" in start_talk
    assert "const upgrade = mintRealtime" in start_talk
    assert "prefetchSession()" in start_talk
    assert "if (upgrade) void connectRealtime()" in start_talk
    assert "speakFirstHello" not in start_talk
    assert "await " not in start_talk
    assert "/api/jarvis/realtime/session" not in start_talk
    assert "/api/jarvis/health" not in start_talk
    assert start_talk.index("prefetchSession()") < start_talk.index("const upgrade = mintRealtime")
    assert start_talk.index("const upgrade = mintRealtime") < start_talk.index("connectRealtime")
    assert start_talk.index("connectRealtime") < start_talk.index("startListen()")
    assert "startBrowserTalk()" not in start_talk
    assert "let canListen = true" in page
    assert "let mintRealtime = true" in page
    assert 'data-state="on"' in page
    assert "?lite=1" in page
    assert "void health(true)" in page
    assert "requestIdleCallback" in page
    iframe = page.split('id="pc-frame"', 1)[1].split(">", 1)[0]
    assert 'src="/jarvis/screen"' not in iframe
    assert "loadPcScreen" in page
    assert 'frame.setAttribute("src", "/jarvis/screen?picture="' in page
    assert "saveTalkSettings({ model_speed:" in page
    assert "saveTalkSettings({ quality_vs_price: q, model_lock: false })" in page
    assert "rememberTalkSettings" in page
    assert "applyPicture" in page
    assert "whenIdle" in page
    head = page.split("<style>", 1)[0]
    assert 'media="print"' in head
    assert "this.media='all'" in head
    assert "--ui-font: system-ui" in page
    assert "html.fonts-ready" in page
    for line in head.splitlines():
        if "fonts.googleapis.com/css2" in line and "noscript" not in line:
            assert 'media="print"' in line
    _assert_no_secret_values(page)


def test_health_sheet_matches_public_view_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.delenv("JARVIS_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("JARVIS_MONTHLY_BUDGET_USD", raising=False)
    from app.jarvis import settings_store
    from app.jarvis.spend import record_spend
    from app.jarvis.voice_ask import listen_health, public_talk_sheet

    settings_store.reset_cache()
    (tmp_path / "Memory").mkdir(parents=True, exist_ok=True)
    settings_store.save(
        {"model": "deepseek/deepseek-v4-flash-0731", "quality_vs_price": "fast"},
        root=tmp_path,
    )
    settings_store.reset_cache()
    record_spend(0.42, root=tmp_path)
    view = settings_store.public_view()
    sheet = public_talk_sheet()
    health = listen_health()
    assert sheet["model"] == view["model"] == "deepseek/deepseek-v4-flash-0731"
    assert sheet["spent_today_usd"] == view["spent_today_usd"] == pytest.approx(0.42)
    assert sheet["spent_month_usd"] == view["spent_month_usd"]
    assert sheet["remaining_budget_usd"] == view["remaining_budget_usd"]
    assert sheet["quality_vs_price"] == view["quality_vs_price"] == "fast"
    assert sheet["model_speed"] == view["model_speed"]
    assert sheet["monthly_budget_usd"] == view["monthly_budget_usd"]
    assert health["model"] == view["model"]
    assert health["spent_today_usd"] == view["spent_today_usd"]
    assert health["helper_models"] == view["helper_models"] == sheet["helper_models"]
    assert health.get("helper_name") == view.get("helper_name") == sheet.get("helper_name")
    if health.get("helper_name") is not None:
        assert health["helper_name"] in {"Quick", "Kimi", "Ox"}
    assert 1 <= len(health["helper_models"]) <= 20
    for row in health["helper_models"]:
        assert row["id"]
        assert row["name"]
        assert "gpt-realtime" not in row["id"]
        assert "price" not in row
    assert "OPENAI_API_KEY" not in json.dumps(health)
    assert "KIMI_CODE_API_KEY" not in json.dumps(health)
    assert "KIMI_API_KEY" not in json.dumps(health)
    assert "sk-or-" not in json.dumps(health)
    lite = listen_health(lite=True)
    assert "helper_models" not in lite
    assert "spent_today_usd" not in lite
    assert "spent_month_usd" not in lite
    assert "remaining_budget_usd" not in lite
    assert "monthly_budget_usd" not in lite
    assert "model" not in lite
    assert "helper_name" not in lite
    assert lite["can_listen"] == health["can_listen"]
    assert lite["listen_mode"] == health["listen_mode"]
    assert lite["realtime"] == health["realtime"]
    assert "OPENAI_API_KEY" not in json.dumps(lite)
    assert "sk-or-" not in json.dumps(lite)


def test_lite_health_does_not_load_helper_catalog(monkeypatch):
    from app.jarvis import voice_ask

    def boom() -> dict:
        raise AssertionError("full sheet should not load on lite health")

    monkeypatch.setattr(voice_ask, "public_talk_sheet", boom)
    lite = voice_ask.listen_health(lite=True)
    assert "helper_models" not in lite
    assert "spent_today_usd" not in lite
    assert "can_listen" in lite
    assert "listen_mode" in lite


@pytest.mark.asyncio
async def test_bare_jarvis_path_redirects_to_slash(client):
    r = await client.get("/jarvis", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location", "").endswith("/jarvis/")


@pytest.mark.asyncio
async def test_talk_apis_exist_under_jarvis_prefix(client):
    health = await client.get("/jarvis/api/jarvis/health")
    assert health.status_code == 200
    body = health.json()
    assert "can_listen" in body
    assert "can_speak" in body
    assert "model" in body
    assert "spent_today_usd" in body
    assert "spent_month_usd" in body
    assert "remaining_budget_usd" in body
    assert "quality_vs_price" in body
    assert "model_speed" in body
    assert "monthly_budget_usd" in body
    assert "helper_models" in body
    assert 1 <= len(body["helper_models"]) <= 20
    assert all("gpt-realtime" not in str(row.get("id") or "") for row in body["helper_models"])
    lite = await client.get("/jarvis/api/jarvis/health?lite=1")
    assert lite.status_code == 200
    lite_body = lite.json()
    assert "can_listen" in lite_body
    assert "listen_mode" in lite_body
    assert "realtime" in lite_body
    assert "helper_models" not in lite_body
    assert "spent_today_usd" not in lite_body
    assert "model" not in lite_body
    _assert_no_secret_values(lite.text)
    assert "operator-test-key" not in health.text
    _assert_no_secret_values(health.text)
    for key in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "API_SECRET",
        "BRIDGE_TOKEN",
        "TOKEN_ENCRYPTION_KEY",
    ):
        assert key not in health.text

    saved = await client.put(
        "/jarvis/api/jarvis/settings",
        json={"quality_vs_price": "smart", "model_speed": "careful"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["quality_vs_price"] == "smart"
    assert saved.json()["model_speed"] == "careful"
    again = await client.get("/jarvis/api/jarvis/settings")
    assert again.status_code == 200
    assert again.json()["quality_vs_price"] == "smart"
    assert again.json()["model_speed"] == "careful"
    health_after = await client.get("/jarvis/api/jarvis/health")
    assert health_after.json()["quality_vs_price"] == "smart"
    assert health_after.json()["model_speed"] == "careful"

    ask = await client.post("/jarvis/api/jarvis/ask", json={"text": "hello"})
    assert ask.status_code == 200
    asked = ask.json()
    assert asked["reply"] == "Hello."
    assert "model" in asked
    assert "spent_today_usd" in asked
    _assert_no_secret_values(ask.text)

    long_ask = await client.post(
        "/jarvis/api/jarvis/ask",
        json={
            "text": (
                "Please explain in careful detail why the sky appears blue "
                "at noon and red at sunset including the physics of scattering"
            )
        },
    )
    assert long_ask.status_code == 200
    assert long_ask.json()["reply"] == "Can't talk right now"
    assert "spent_today_usd" in long_ask.json()
    _assert_no_secret_values(long_ask.text)

    speak = await client.post("/jarvis/api/jarvis/speak", json={"text": "hi"})
    assert speak.status_code == 503


# PR #179 checked in local ffmpeg/SAPI robot clips. First hello must not
# be those files — OpenAI TTS (marin) is larger, 24 kHz / 128 kbps.
_ROBOT_HELLO = {
    "en": {
        "sha256": "479b50c74b8461846e9d0535d40ba73c228b9e8f97f85ceb0b48772be57cdfb0",
        "size": 5066,
    },
    "tr": {
        "sha256": "4bf676e10624e42e114752941d1c653c83ffa743c1b1a1f9b571344d46d1b39c",
        "size": 7704,
    },
}


def _mpeg_l3_rate(data: bytes) -> tuple[int, int]:
    """Return (bitrate_kbps, sample_hz) for the first MPEG Layer III frame."""
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        data = data[10 + size :]
    assert len(data) >= 4
    hdr = int.from_bytes(data[:4], "big")
    assert hdr >> 21 == 0x7FF
    version = (hdr >> 19) & 0x3
    layer = (hdr >> 17) & 0x3
    assert layer == 1  # Layer III
    br_idx = (hdr >> 12) & 0xF
    sr_idx = (hdr >> 10) & 0x3
    mpeg2_l3 = (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
    mpeg2_sr = (22050, 24000, 16000)
    assert version == 2  # MPEG-2
    assert 1 <= br_idx <= 14
    assert sr_idx < 3
    return mpeg2_l3[br_idx - 1], mpeg2_sr[sr_idx]


def test_hello_clip_path_is_tiny_locale_set():
    from app.jarvis.public_routes import hello_clip_path

    en = hello_clip_path("en")
    tr = hello_clip_path("TR")
    assert en is not None and en.is_file()
    assert tr is not None and tr.is_file()
    assert en.name == "en.mp3"
    assert tr.name == "tr.mp3"
    assert hello_clip_path("de") is None
    assert hello_clip_path("../en") is None
    assert hello_clip_path("en.mp3") is None


def test_hello_clips_are_openai_tts_not_local_robot():
    from app.jarvis.public_routes import HELLO_DIR, hello_clip_path

    for code in ("en", "tr"):
        path = hello_clip_path(code)
        assert path is not None and path.is_file()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        robot = _ROBOT_HELLO[code]
        assert digest != robot["sha256"]
        assert len(data) != robot["size"]
        assert len(data) > 10000
        assert b"Lavf60.16.100" not in data
        bitrate, sample = _mpeg_l3_rate(data)
        assert bitrate >= 96
        assert sample == 24000
        assert path.parent == HELLO_DIR


@pytest.mark.asyncio
async def test_cached_hello_clips_are_static_mpeg(client):
    en = await client.get("/jarvis/hello/en.mp3")
    tr = await client.get("/jarvis/hello/tr.mp3")
    missing = await client.get("/jarvis/hello/de.mp3")
    assert en.status_code == 200
    assert tr.status_code == 200
    assert missing.status_code == 404
    assert "audio/mpeg" in en.headers.get("content-type", "")
    assert "audio/mpeg" in tr.headers.get("content-type", "")
    assert en.content[:3] == b"ID3" or en.content[:1] == b"\xff"
    assert tr.content[:3] == b"ID3" or tr.content[:1] == b"\xff"
    assert len(en.content) >= 16
    assert len(tr.content) >= 16
    page = await client.get("/jarvis/", follow_redirects=True)
    html = page.text
    start_talk = html.split("async function startTalk()", 1)[1].split("function askTextMax", 1)[0]
    connect = html.split("async function connectRealtime()", 1)[1].split("function rememberMicGranted", 1)[0]
    prefetch = html.split("function prefetchSession()", 1)[1].split("\n      function ", 1)[0]
    assert "/api/jarvis/speak" not in start_talk
    assert "/api/jarvis/speak" not in connect
    assert "/api/jarvis/speak" not in prefetch
    assert "/jarvis/hello/en.mp3" not in start_talk
    assert "/jarvis/hello/en.mp3" not in connect
    assert "speakFirstHello" not in html
    assert 'src="/jarvis/hello/en.mp3"' not in html
    assert 'src="/jarvis/hello/tr.mp3"' not in html
    assert "prefetchSession()" in start_talk
    assert "const TEST_FORCE_ENGLISH = true" in html
    assert "Greet in one short line in English only" in html
    assert "Greet in one short line in the user's language" in html
    assert "function sendRealtimeGreet" in html
    assert "function tryGoDuplex" in html
    assert "tryGoDuplex()" in connect
    assert "hasRemoteAudioTrack" in connect
    _assert_no_secret_values(html)


@pytest.mark.asyncio
async def test_download_exe_when_file_exists(client, tmp_path, monkeypatch):
    exe = tmp_path / "Jarvis-Setup.exe"
    exe.write_bytes(b"MZ-fake-installer")
    monkeypatch.setenv("JARVIS_SETUP_EXE_PATH", str(exe))
    r = await client.get("/jarvis/download/Jarvis-Setup.exe")
    assert r.status_code == 200
    assert r.content == b"MZ-fake-installer"
    assert "application/octet-stream" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_download_missing_is_404_not_the_chat_page(client):
    r = await client.get("/jarvis/download/Jarvis-Setup.exe")
    assert r.status_code == 404
    assert 'id="log"' not in r.text
