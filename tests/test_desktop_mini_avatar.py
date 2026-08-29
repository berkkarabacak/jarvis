"""ORCH-397 / ORCH-398 — Windows always-on-top mini Jarvis avatar + talk."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"


def test_mini_avatar_helpers():
    script = DESKTOP / "mini-avatar.test.js"
    result = subprocess.run(
        ["node", str(script)],
        cwd=str(DESKTOP),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mini-avatar helpers ok" in result.stdout


def test_avatar_window_is_always_on_top_overlay():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert 'require("./mini-avatar")' in main
    assert "createAvatarWindow" in main
    assert "syncAvatarVisibility" in main
    assert "showInactive" in main
    assert "setAlwaysOnTop" in main
    assert "avatar.html" in main
    assert "focusVoiceFromAvatar" in main
    assert 'send("jarvis:focus-voice")' in main
    assert "Do not show or focus the main window" in main
    assert "mainWindow.focus()" not in main.split("function focusVoiceFromAvatar")[1].split("function ")[0]
    assert "mainWindow.show()" not in main.split("function focusVoiceFromAvatar")[1].split("function ")[0]


def test_avatar_click_opens_talk_bubble():
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    assert 'aria-label="Talk to Jarvis"' in html
    assert "<strong>Talk to Jarvis</strong>" not in html
    assert "Click or speak" in html
    assert 'id="avatar"' in html
    assert 'id="bubble"' in html
    assert "jarvisAvatar.clicked" in html
    assert "jarvisAvatar.moveBy" in html
    assert "<svg" in html
    assert "#12263a" in html
    assert "#f2c14e" in html
    preload = (DESKTOP / "avatar-preload.js").read_text(encoding="utf-8")
    assert "avatar:clicked" in preload
    assert "avatar:move-by" in preload


def _fn_body(src: str, name: str) -> str:
    token = f"function {name}"
    start = src.index(token)
    rest = src[start + len(token) :]
    nxt = rest.find("\nfunction ")
    return rest if nxt < 0 else rest[:nxt]


def test_avatar_ask_and_reply_stay_on_overlay():
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    assert 'id="ask"' in html
    assert 'id="bubble-line"' in html
    assert 'aria-label="Ask Jarvis"' in html
    assert "Type a bit" not in html
    assert "Listening" in html
    assert "SpeechRecognition" in html
    assert "speechSynthesis" not in html
    assert "SpeechSynthesisUtterance" not in html
    assert "speakReply" not in html
    assert 'id="mute"' in html
    assert 'id="close"' in html
    assert "let muted = false" in html
    assert "jarvisAvatar.setMuted" in html
    assert "jarvisAvatar.quit" in html
    assert "jarvisAvatar.health" in html
    assert "jarvisAvatar.ask" in html
    assert "jarvisAvatar.onTalk" in html
    assert "jarvisAvatar.typeFocus" in html
    assert "/ceo" not in html
    preload = (DESKTOP / "avatar-preload.js").read_text(encoding="utf-8")
    assert "avatar:ask" in preload
    assert "avatar:health" in preload
    assert "avatar:talk" in preload
    assert "avatar:type-focus" in preload
    assert "avatar:set-muted" in preload
    assert "avatar:quit" in preload
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "function askFromAvatar" in main
    assert "function sendAvatarTalk" in main
    assert "function setJarvisMuted" in main
    assert "function quitJarvis" in main
    assert "jarvis:avatar-ask" in main
    assert "jarvis:talk" in main
    assert "jarvis:muted" in main
    ask_fn = _fn_body(main, "askFromAvatar")
    assert "Do not show or focus the main window" in ask_fn
    assert "mainWindow.focus()" not in ask_fn
    assert "mainWindow.show()" not in ask_fn
    type_fn = _fn_body(main, "typeFocusFromAvatar")
    assert "Do not show or focus the main window" in type_fn
    assert "mainWindow.focus()" not in type_fn
    assert "mainWindow.show()" not in type_fn
    assert "avatarWindow.focus()" in _fn_body(main, "setAvatarTyping")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    assert "function normalizeAsk" in helpers
    assert "function clipReply" in helpers
    assert "function normalizeMuted" in helpers
    assert "function talkLine" in helpers
    assert "function talkPathFromHealth" in helpers
    assert "function connectActionFromHealth" in helpers
    assert "function afterRealtimeSessionFailure" in helpers
    assert "raisesMain: false" in helpers
    assert "fetchJarvisHealth" in main
    assert "avatar:health" in main
    # OpenRouter-only: error status stays ready, not "Can't hear".
    assert 'status === "error") return canListen === false' in html
    assert html.count("Can't hear right now") == 2
    assert "function talkPathFromHealth" in html
    assert "if (health.realtime) return" not in html


def test_ceo_page_has_voice_focus_hook():
    html = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert "function focusVoice" in html
    assert "jarvisDesktop.onFocusVoice" in html
    assert "function sendUserTextFromAvatar" in html
    assert "function reportAvatarTalk" in html
    assert "jarvisDesktop.onAvatarAsk" in html
    assert "jarvisDesktop.reportTalk" in html
    assert "response.output_audio_transcript.delta" in html
    assert "response.audio_transcript.done" in html
    assert "input_text" in html
    assert "pendingAvatarAsk" in html
    assert "/api/jarvis/ask" in html
    assert "/api/jarvis/speak" in html
    assert "askViaOpenRouter" in html
    assert "speakNeural" in html
    assert "outputMuted" in html
    assert "if (outputMuted) return false" in html
    assert "sink.muted = outputMuted" in html
    assert "startBrowserListen" in html
    assert "function talkPathFromHealth" in html
    assert "function startOpenRouterTalk" in html
    assert "speechSynthesis" not in html
    assert "SpeechSynthesisUtterance" not in html
    assert "speakReply" not in html
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    assert "jarvisDesktop" in preload
    assert "jarvis:focus-voice" in preload
    assert "jarvis:avatar-ask" in preload
    assert "jarvis:talk" in preload
    assert "jarvis:muted" in preload
    assert "getMuted" in preload


def test_installer_packs_avatar_files():
    yml = (DESKTOP / "electron-builder.installer.yml").read_text(encoding="utf-8")
    pkg = (DESKTOP / "package.json").read_text(encoding="utf-8")
    for name in (
        "mini-avatar.js",
        "avatar.html",
        "avatar-preload.js",
        "jarvis-tray.png",
    ):
        assert name in yml
        assert name in pkg
        assert (DESKTOP / name).is_file()


def test_avatar_is_not_a_second_main_window():
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "/ceo" not in html
    assert "1280" not in html
    assert "createAvatarWindow" in main
    assert "setSkipTaskbar" in main
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    assert "skipTaskbar: false" in helpers
    assert "focusable: true" in helpers
    assert "raisesMainOnClick: false" in helpers


def test_default_launch_is_avatar_only():
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    preload = (DESKTOP / "avatar-preload.js").read_text(encoding="utf-8")
    assert 'defaultLaunch: "avatar"' in helpers
    assert "function shouldShowMainOnLaunch" in helpers
    assert "function shouldOpenBubbleOnLaunch" in helpers
    assert "function shouldHideMainOnClose" in helpers
    assert "function shouldQuitOnAvatarClose" in helpers
    assert "shouldShowMainOnLaunch()" in main
    assert "shouldOpenBubbleOnLaunch()" in main
    assert "function expandMainWindow" in main
    assert "function hideMainWindow" in main
    assert "shouldHideMainOnClose" in main
    create_fn = _fn_body(main, "createWindow")
    assert "show: shouldShowMainOnLaunch()" in create_fn
    assert "createAvatarWindow" in create_fn
    close_fn = _fn_body(main, "createWindow")
    assert "hideMainWindow" in close_fn
    assert "closeAvatarWindow" not in close_fn
    expand_fn = _fn_body(main, "expandMainWindow")
    assert "mainWindow.show()" in expand_fn
    hide_fn = _fn_body(main, "hideMainWindow")
    assert "mainWindow.hide()" in hide_fn
    assert 'id="expand"' in html
    assert 'aria-label="Open Jarvis"' in html
    assert "jarvisAvatar.expand" in html
    assert "avatar:expand" in preload
    assert "avatar:expand" in main


def test_default_window_is_avatar_sized_not_open_bubble():
    """Cold start is the circular avatar, not the 248×172 talk bubble."""
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    assert "openBubbleOnLaunch: false" in helpers
    assert "function shouldOpenBubbleOnLaunch" in helpers
    create_av = _fn_body(main, "createAvatarWindow")
    assert "shouldOpenBubbleOnLaunch()" in create_av
    assert "bubbleBounds(" in create_av
    assert "did-finish-load" in create_av
    assert 'send("avatar:bubble"' in create_av
    send_fn = _fn_body(main, "sendAvatarTalk")
    assert "avatarBubbleOpen = true" not in send_fn
    assert "next.open = avatarBubbleOpen" in send_fn
    body_tag = html[html.index("<body") : html.index(">", html.index("<body")) + 1]
    assert "is-open" not in body_tag
    assert "body.is-open #bubble" in html
    assert "body.is-open #expand" in html
    expand_css = html[html.index("#expand {") : html.index("body.is-open #expand")]
    assert "display: none" in expand_css


def test_bubble_opens_only_after_avatar_click():
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    click_fn = _fn_body(main, "createAvatarWindow")
    assert "avatar:clicked" in click_fn
    assert "avatarBubbleOpen = !avatarBubbleOpen" in click_fn
    assert "applyAvatarBounds()" in click_fn
    assert "jarvisAvatar.clicked" in html
    open_fn = _fn_body(helpers, "shouldOpenBubbleForTalk")
    assert "return false" in open_fn
    ask_fn = _fn_body(main, "askFromAvatar")
    assert "avatarBubbleOpen = true" in ask_fn


def test_close_or_minimize_full_window_returns_to_avatar():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "shouldHideMainOnClose" in _fn_body(main, "createWindow")
    assert "e.preventDefault()" in _fn_body(main, "createWindow")
    assert "hideMainWindow" in main
    assert "syncAvatarVisibility" in _fn_body(main, "hideMainWindow")
    assert "shouldQuitOnAvatarClose" in main
    assert "Quit Jarvis" in main


def test_quit_on_avatar_close_button():
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    preload = (DESKTOP / "avatar-preload.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    assert 'id="close"' in html
    assert ">×</button>" in html
    assert 'aria-label="Quit Jarvis"' in html
    assert "jarvisAvatar.quit" in html
    assert "avatar:quit" in preload
    assert "avatar:quit" in main
    assert "function quitJarvis" in main
    assert "function shouldQuitOnAvatarCloseButton" in helpers
    quit_fn = _fn_body(main, "createAvatarWindow")
    assert "avatar:quit" in quit_fn
    assert "quitJarvis()" in quit_fn
    assert "shouldQuitOnAvatarCloseButton" in quit_fn


def test_taskbar_or_tray_quit():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    assert "new Tray" in main
    assert "function createTray" in main
    assert "function refreshTrayMenu" in main
    assert "Quit Jarvis" in main
    assert "trayMenuItems" in helpers
    assert 'label: "Quit Jarvis"' in helpers
    assert "createTray()" in _fn_body(main, "createWindow")
    create_av = _fn_body(main, "createAvatarWindow")
    assert "setSkipTaskbar(false)" in create_av
    assert "skipTaskbar: AVATAR.skipTaskbar === true" in helpers
    opts = _fn_body(helpers, "avatarWindowOptions")
    assert "skipTaskbar: AVATAR.skipTaskbar === true" in opts


def test_mute_stops_speak():
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    preload = (DESKTOP / "avatar-preload.js").read_text(encoding="utf-8")
    desk = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    assert 'id="mute"' in html
    assert 'aria-label="Mute Jarvis"' in html
    assert "icon-on" in html
    assert "jarvisAvatar.setMuted" in html
    assert "speechSynthesis" not in html
    assert "speakReply" not in html
    assert "function speakIfUnmuted" in helpers
    assert "function muteRealtimeOutput" in helpers
    assert "avatar:set-muted" in preload
    assert "jarvis:muted" in desk
    assert "function applyOutputMute" in ceo
    assert "outputMuted" in ceo
    assert "stopNeuralUtterance" in ceo
    assert "sink.muted = outputMuted" in ceo
    assert "if (outputMuted) return false" in ceo
    assert "if (!text || outputMuted)" in ceo
    assert "function setJarvisMuted" in main
    assert 'label: muted ? "Unmute" : "Mute"' in helpers


def test_avatar_window_is_clickable():
    helpers = (DESKTOP / "mini-avatar.js").read_text(encoding="utf-8")
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    html = (DESKTOP / "avatar.html").read_text(encoding="utf-8")
    assert "focusable: true" in helpers
    assert "function avatarWindowIsClickable" in helpers
    assert "src.focusable === true" in helpers
    create_av = _fn_body(main, "createAvatarWindow")
    assert "setFocusable(true)" in create_av
    assert "setIgnoreMouseEvents(false)" in create_av
    assert "setSkipTaskbar(false)" in create_av
    typing = _fn_body(main, "setAvatarTyping")
    assert "setFocusable(true)" in typing
    assert "setFocusable(!!on)" not in typing
    assert "setIgnoreMouseEvents(true)" not in main
    assert "jarvisAvatar.expand" in html
    assert 'id="ask"' in html
    assert 'id="ask-go"' in html
    assert 'id="close"' in html
    assert 'id="mute"' in html
