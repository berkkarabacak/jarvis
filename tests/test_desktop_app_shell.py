"""Windows 3-pane shell chrome — issues #74 / #67 / #68 / #69 / #70 / #71 / #72 / #73 (epic #66)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")
os.environ.setdefault("LLM_MODEL_MODE", "fixed")
os.environ.setdefault("DEFAULT_MODEL", "openai/gpt-4.1-mini")

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
SHELL_HTML = ROOT / "app" / "static" / "desktop.html"


def test_app_shell_helpers():
    script = DESKTOP / "app-shell.test.js"
    result = subprocess.run(
        ["node", str(script)],
        cwd=str(DESKTOP),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "app-shell helpers ok" in result.stdout


def test_electron_hosts_three_pane_as_primary_window():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    pkg = (DESKTOP / "package.json").read_text(encoding="utf-8")
    yml = (DESKTOP / "electron-builder.installer.yml").read_text(encoding="utf-8")

    assert 'require("./app-shell")' in main
    assert "function desktopUrl" in main
    assert "function ceoUrl" in main
    assert "loadURL(desktopUrl(port))" in main
    assert "createTalkEngineWindow" in main
    assert "function openSettingsInWindow" in main
    assert "jarvis:open-settings" in main
    assert "Quit Jarvis" in main
    assert "trayMenuItems" in main
    assert "shouldShowFirstRunKeyWindow" in main
    assert "/desktop" in shell
    assert 'defaultLaunch: "main"' in helpers
    assert "function shouldShowMainOnLaunch" in helpers
    assert "openSettings" in preload
    assert "startListen" in preload
    assert "onTalk" in preload
    assert "jarvis:start-listen" in main
    assert "jarvis:ask-talk" in main
    assert "function sendMainTalk" in main
    assert "jarvis:talk-event" in main
    assert "app-shell.js" in pkg
    assert "app-shell.js" in yml
    assert (DESKTOP / "app-shell.js").is_file()


def test_three_pane_html_matches_windows_mock_chrome():
    html = SHELL_HTML.read_text(encoding="utf-8")
    low = html.lower()
    assert 'id="left"' in html
    assert 'id="middle"' in html
    assert 'id="right"' in html
    assert 'id="live-computer"' in html
    assert 'id="composer"' in html
    assert 'id="ask"' in html
    assert 'id="mic"' in html
    assert 'id="send"' in html
    assert 'id="attach"' in html
    assert "Your AI teammate" in html
    assert "Search assistants, chats" in html
    assert "Ctrl K" in html
    assert "Helpers" in html
    assert "Recent chats" in html
    assert "View all chats" in html
    assert "Group chats" in html
    assert "Live Computer" in html
    assert "Jarvis's screen" in html
    assert "Routines" in html
    assert "Create routine" in html
    assert "Type a message" in html
    assert "Hide chats" in html
    assert "Show chats" in html
    assert "Hide computer" in html
    assert "Show computer" in html
    assert "Chat only" in html
    assert "Open in new window" in html
    assert "Jarvis is using the computer" in html
    assert "talk_mode" in html
    assert "/api/jarvis/settings" in html
    assert "127.0.0.1:6080" in html
    assert "left-collapsed" in html
    assert "right-collapsed" in html
    assert "#1A1D23" in html
    assert "#F8F9FB" in html
    assert "border-radius: 14px" in html or "border-radius: var(--radius)" in html
    assert "api key" not in low
    assert "openrouter" not in low
    assert 'id="voiceDock"' not in html
    assert "Adding a routine comes later." in html or "No routines yet." in html
    assert 'id="new-chat"' in html
    assert "New chat" in html
    assert "nav-toggle" in html
    assert 'id="nav-chat"' in html
    assert 'id="nav-helpers"' in html
    assert 'id="nav-routines"' in html
    assert 'data-section="helpers"' in html
    assert 'data-section="chats"' in html
    assert 'data-section="groups"' in html
    assert "Not connected yet" in html
    assert "No chats yet. Send a message to start." in html
    assert "No group chats yet. They come later." in html
    assert "class=\"unread\"" in html or 'class="unread"' in html
    assert 'id="settings"' in html
    assert 'id="model-btn"' in html
    assert "Buyra" not in html


def test_right_pane_embeds_live_novnc_iframe():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    readme = (DESKTOP / "README.md").read_text(encoding="utf-8")

    assert 'id="live-computer"' in html
    assert 'data-embed="iframe"' in html
    assert 'id="live-frame"' in html
    assert 'title="Jarvis\'s screen"' in html
    assert 'id="hide-screen"' in html
    assert 'id="show-screen"' in html
    assert 'aria-label="Hide screen"' in html
    assert 'aria-label="Show screen"' in html
    assert 'id="start-computer"' in html
    assert "Start Jarvis's computer" in html
    assert "Show Jarvis's screen" in html
    assert "Chat only — the computer stays hidden." in html
    assert "Jarvis's screen is hidden. The computer keeps running." in html
    assert "http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale" in html
    assert "/api/jarvis/computer/screen" in html
    assert "/api/jarvis/computer/screen/start" in html
    assert "function clearLiveFrame" in js
    assert "function computerShouldShow" in js
    assert "function syncLiveComputer" in js
    assert 'setAttribute("src", "about:blank")' in js
    assert 'sessionStorage.setItem(SCREEN_STORAGE' in js
    assert 'if (talkMode === "terminal") screenShown = false' in js
    assert "if (!computerShouldShow()) return" in js
    assert "BrowserView" in html
    assert "new BrowserView" not in main
    assert "require(\"electron\")" in main
    assert "BrowserView" in main
    assert "iframe" in main.lower()
    assert 'screenEmbed: "iframe"' in shell
    assert 'screenEmbedRejected: "BrowserView"' in shell
    assert "Do not attach a BrowserView here." in main
    assert "iframed" in readme.lower() or "iframe" in readme.lower()
    assert "BrowserView is not used" in readme


def test_hide_and_chat_only_do_not_stop_jarvis_computer():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    combined = html + "\n" + shell + "\n" + main
    low = combined.lower()

    assert "clearLiveFrame" in js
    assert "syncLiveComputer" in js
    assert 'docker compose down' not in low
    assert "docker stop" not in low
    assert "/api/jarvis/computer/screen/stop" not in low
    assert "jarvis-computer/stop" not in low
    assert "kill jarvis-computer" not in js.lower()
    assert "stopComputer: false" in shell
    assert "killsComputerOnHide: false" in shell
    assert "Do not stop jarvis-computer" in shell or "do not stop jarvis-computer" in shell
    assert "savePanes(panes)" in js
    assert "setScreenShown(false)" in js
    assert "persistTalkMode(\"terminal\")" in js


def test_middle_pane_is_live_chat_thread():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    readme = (DESKTOP / "README.md").read_text(encoding="utf-8")

    assert 'data-chat="live"' in html
    assert 'id="chat-title"' in html
    assert "Jarvis" in html
    assert 'id="thread"' in html
    assert 'id="empty-chat"' in html
    assert 'id="pending"' in html
    assert 'id="composer"' in html
    assert 'id="ask"' in html
    assert 'id="mic"' in html
    assert 'id="send"' in html
    assert 'id="add"' in html
    assert "Type a message" in html
    assert "Ready when you are" in html
    assert "This chat is ready. Messages will show up here." in html
    assert "Photos and files come later." in html
    assert "Can't talk right now" in html
    assert 'class="msg jarvis pending"' in html
    assert 'className = "msg " + turn.role' in js
    assert "display: flex" in html
    assert "flex-direction: column" in html
    assert "/api/jarvis/ask" in html
    assert "/api/jarvis/talk/last" in html
    assert "/api/jarvis/talk/log" in html
    assert "function sendAsk" in js
    assert "function rememberTurn" in js
    assert "function paintThread" in js
    assert "function loadHistory" in js
    assert "function startListen" in js
    assert "function applyTalkEvent" in js
    assert "function startBrowserListen" in js
    assert "SpeechRecognition" in js
    assert "Chat comes next." not in html
    assert "Talk comes next." not in html
    assert "innerHTML" not in js
    assert "ASK_PATH" in shell
    assert 'ASK_PATH = "/api/jarvis/ask"' in shell
    assert "function composerSubmit" in shell
    assert "function speechTurns" in shell
    assert "function applyTalkEvent" in shell
    assert "function selectLead" in shell
    assert "function micPlan" in shell
    assert "startListen" in preload
    assert "onTalk" in preload
    assert "jarvis:start-listen" in main
    assert "function sendMainTalk" in main
    assert "jarvis:talk-event" in main
    assert "focusVoiceFromAvatar" in main
    assert "/api/jarvis/ask" in readme
    assert "middle pane" in readme.lower() or "chat thread" in readme.lower()
    assert "Quit Jarvis" in main
    assert "API secret" not in html
    assert "openrouter" not in html.lower()
    assert "sk-" not in html.lower()


def test_left_pane_is_collapsible_helpers_chats_and_groups():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")

    assert 'id="search"' in html
    assert 'id="new-chat"' in html
    assert 'aria-label="New chat"' in html
    assert 'id="toggle-helpers"' in html
    assert 'id="toggle-chats"' in html
    assert 'id="toggle-groups"' in html
    assert "aria-expanded" in html
    assert 'data-section="helpers"' in html
    assert 'data-section="chats"' in html
    assert 'data-section="groups"' in html
    assert 'data-open="0"' in html
    assert "function toggleNavSection" in shell
    assert "function normalizeNavSections" in shell
    assert "function leftNavView" in shell
    assert "function paintLeftNav" in js
    assert "function saveNav" in js
    assert "function paintNavSections" in js
    assert "jarvis.shell.nav" in js
    assert "function selectLead" in js
    assert "chatTitle.textContent" in js
    assert 'selectLead("jarvis")' in js
    assert "talkTarget: \"jarvis\"" in shell
    assert "Quit Jarvis" in (DESKTOP / "main.js").read_text(encoding="utf-8")


def test_left_nav_uses_talk_history_and_honest_stubs():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    readme = (DESKTOP / "README.md").read_text(encoding="utf-8")

    assert 'data-source="local-lead documented-stub"' in html
    assert 'data-source="talk-history"' in html
    assert 'data-source="none"' in html
    assert 'data-source="local-lead"' in html
    assert 'data-source="documented-stub"' in html
    assert "Not connected yet" in html
    assert "Ready when you are" in html
    assert "No chats yet. Send a message to start." in html
    assert "No group chats yet. They come later." in html
    assert "Buyra" not in html
    assert "Placeholder chat" not in html
    assert "Placeholder group" not in html
    assert 'data-id="family"' not in html
    assert 'data-id="home"' not in html
    assert "function chatsFromHistory" in js
    assert "function chatsFromHistory" in shell
    assert "function helpersFromInventory" in shell
    assert "function groupChatsFromInventory" in shell
    assert "documented-stub" in shell
    assert "talk-history" in shell
    assert 'DATA_SOURCES' in shell
    assert "Never invent live teammates" in shell or "never invent live teammates" in shell.lower()
    assert "function refreshChatsFromTurns" in js
    assert "/api/jarvis/talk/last" in html
    assert "innerHTML" not in js
    assert "left nav" in readme.lower() or "helpers" in readme.lower()
    assert "talk history" in readme.lower() or "talk-history" in readme.lower()
    assert "not connected" in readme.lower()


def test_middle_pane_keeps_right_pane_live_pc():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    assert 'id="live-computer"' in html
    assert 'id="live-frame"' in html
    assert "function syncLiveComputer" in js
    assert "function sendAsk" in js
    assert "http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale" in html
    assert "/api/jarvis/computer/screen/stop" not in html
    assert "function computerShouldShow" in js


def test_routines_block_under_live_pc_is_honest():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    readme = (DESKTOP / "README.md").read_text(encoding="utf-8")

    assert 'id="routines-block"' in html
    assert 'id="routines"' in html
    assert 'id="empty-routines"' in html
    assert 'id="routine-note"' in html
    assert 'id="add-routine"' in html
    assert 'aria-label="Add routine"' in html
    assert "No routines yet." in html
    assert "Morning briefing" not in html
    assert "Evening wrap" not in html
    assert 'data-source="local-schedules"' in html
    assert "/api/jarvis/routines" in html
    assert "function paintRoutines" in js
    assert "function loadRoutines" in js
    assert "function addRoutineSoon" in js
    assert "Adding a routine comes later." in js
    assert "routine-note" in js
    assert "function routinesView" in shell
    assert "function addRoutinePlan" in shell
    assert 'ROUTINES_PATH = "/api/jarvis/routines"' in shell
    assert "does not invent" in shell.lower() or "honest empty" in shell.lower()
    assert "routines" in readme.lower()
    assert "no routines yet" in readme.lower()


def test_settings_gear_opens_ceo_settings_and_keeps_talk_mode():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")

    assert 'id="settings"' in html
    assert 'aria-label="Settings"' in html
    assert "function openSettings" in js
    assert "jarvisDesktop.openSettings" in js
    assert "/ceo?settings=1&desktop=1" in js
    assert "function settingsPlan" in shell
    assert "talk_mode" in shell
    assert "/api/jarvis/settings" in js
    assert "function persistTalkMode" in js
    assert "function loadTalkMode" in js
    assert "function openSettingsInWindow" in main
    assert "jarvis:open-settings" in main
    assert "openSettings" in preload
    assert "shouldOpenSettings" in ceo
    assert 'q.get("settings") === "1"' in ceo
    assert 'id = "iu-talk-mode"' in ceo
    assert 'persistJarvis({ talk_mode: selectedTalkMode })' in ceo
    assert "Chat only" in ceo
    assert "talk_mode: selectedTalkMode" in ceo


def test_narrow_window_collapses_left_and_right_by_default():
    html = SHELL_HTML.read_text(encoding="utf-8")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    shell = (DESKTOP / "app-shell.js").read_text(encoding="utf-8")

    assert "max-width: 899px" in html
    assert "body:not(.left-open) #left" in html
    assert "body:not(.right-open) #right" in html
    assert "left-open" in js
    assert "right-open" in js
    assert "collapseBelow: 900" in shell
    assert "function isNarrowWidth" in shell
    assert "function defaultPanesForWidth" in shell
    assert "function fitPanesToWidth" in js
    assert "width < 900" in js


def test_desktop_smoke_notes_cover_windows_path():
    readme = (DESKTOP / "README.md").read_text(encoding="utf-8")
    installer = (ROOT / "docs" / "windows-installer.md").read_text(encoding="utf-8")
    start = (ROOT / "docs" / "START-HERE-WINDOWS.txt").read_text(encoding="utf-8")
    low = (readme + "\n" + installer + "\n" + start).lower()

    assert "npm start" in readme
    assert "smoke" in readme.lower()
    assert "chat is in the middle" in low or "chat is the middle" in low
    assert "jarvis's screen" in low
    assert "hide chats" in low or "hide computer" in low
    assert "gear" in low
    assert "settings" in low
    assert "talk_mode" in readme or "chat only" in low
    assert "api key" not in readme.lower()
    assert "Jarvis-Setup.exe" in installer
    assert "narrow" in readme.lower() or "small window" in low


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_desktop_route_serves_three_pane_shell(client):
    r = await client.get("/desktop")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert 'id="left"' in r.text
    assert 'id="middle"' in r.text
    assert 'id="right"' in r.text
    assert 'id="live-computer"' in r.text
    assert 'id="live-frame"' in r.text
    assert 'data-embed="iframe"' in r.text
    assert 'data-chat="live"' in r.text
    assert 'id="routines-block"' in r.text
    assert "No routines yet." in r.text
    assert "/api/jarvis/routines" in r.text
    assert "/api/jarvis/ask" in r.text
    assert "/api/jarvis/talk/last" in r.text
    assert "API secret" not in r.text
    assert "or-test-key" not in r.text


@pytest.mark.asyncio
async def test_ceo_talk_page_still_exists(client):
    r = await client.get("/ceo")
    assert r.status_code == 200
    assert 'id="voiceDock"' in r.text
