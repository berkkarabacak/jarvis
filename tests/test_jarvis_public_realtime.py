"""Public Talk is full-duplex Realtime when mint works, browser speech otherwise."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
CEO = ROOT / "app" / "static" / "ceo.html"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    token = f"function {name}("
    start = src.index(token)
    rest = src[start:]
    nxt = rest.find("\n      function ", 1)
    nxt2 = rest.find("\n      async function ", 1)
    cuts = [i for i in (nxt, nxt2) if i > 0]
    return rest if not cuts else rest[: min(cuts)]


def test_public_page_never_contains_operator_keys():
    page = _page()
    assert "sk-" not in page
    assert "sk-or-" not in page
    assert "OPENAI_API_KEY" not in page
    assert "OPENROUTER_API_KEY" not in page
    low = page.lower()
    assert "api key" not in low
    assert "openrouter" not in low


def test_public_talk_uses_hosted_webrtc_when_health_says_realtime():
    page = _page()
    ceo = CEO.read_text(encoding="utf-8")
    assert "function talkPathFromHealth" in page
    assert 'listenMode === "openai_realtime"' in page
    assert "mintRealtime: true" in page
    assert "/api/jarvis/realtime/session" in page
    assert "RTCPeerConnection" in page
    assert "https://api.openai.com/v1/realtime/calls" in page
    assert 'Content-Type": "application/sdp"' in page
    assert 'createDataChannel("oai-events")' in page
    assert "function startTalk" in page
    assert "const upgrade = mintRealtime" in _fn(page, "startTalk")
    assert "prefetchSession()" in _fn(page, "startTalk")
    assert "if (upgrade) void connectRealtime()" in _fn(page, "startTalk")
    assert "startListen()" in _fn(page, "startTalk")
    assert "speakFirstHello" not in _fn(page, "startTalk")
    assert "/jarvis/hello/" not in _fn(page, "startTalk")
    assert "/api/jarvis/health" not in _fn(page, "startTalk")
    assert "void startTalk()" in page
    # Same WebRTC mint + SDP path as the desktop Talk page. Not a second protocol.
    assert "/api/jarvis/realtime/session" in ceo
    assert "https://api.openai.com/v1/realtime/calls" in ceo
    assert 'createDataChannel("oai-events")' in ceo


def test_public_duplex_keeps_mic_open_while_jarvis_speaks():
    page = _page()
    start_talk = _fn(page, "startTalk")
    connect = _fn(page, "connectRealtime")
    handle = _fn(page, "handleRealtimeEvent")
    speak = _fn(page, "speak")
    paint = _fn(page, "paintMic")
    barge = _fn(page, "bargeIn")
    assert "haltRec()" not in start_talk
    assert "haltRec()" not in handle
    assert "/api/jarvis/realtime/session" in connect
    assert "haltRec()" not in connect.split("/api/jarvis/realtime/session", 1)[0]
    assert "speaking = true" in handle
    assert "haltRec()" not in handle.split("speaking = true")[1][:200]
    assert "if (!duplexLive)" in speak
    assert "haltRec()" in speak
    assert "if (duplexLive)" in paint
    assert "wantListen && !muteMe" in paint
    assert "input_audio_buffer.speech_started" in handle
    assert "output_audio_buffer.clear" in barge
    assert "clearBufferedAudio" in barge
    assert "if (greetInFlight) return" in barge
    assert "interrupt_response" in page
    assert "sendSessionTurnDetection(false)" in page
    assert "getUserMedia" in connect
    assert "micStream" in connect


def test_public_connect_hello_has_no_tools():
    page = _page()
    connect = _fn(page, "connectRealtime")
    greet = _fn(page, "realtimeGreetEvent")
    go = _fn(page, "tryGoDuplex")
    send = _fn(page, "sendRealtimeGreet")
    assert 'tool_choice: "none"' in greet
    assert "TEST_FORCE_ENGLISH" in greet
    assert "Greet in one short line in English only" in greet
    assert "Do not use Italian, Korean, Portuguese" in greet
    assert "Do not invent a language" in greet
    assert "Greet in one short line in the user's language" in greet
    assert "Do not use another language for the greeting" in greet
    assert "Say a short English hello" not in greet
    assert "Say a short hello only in the default page language" not in greet
    assert "Do not call any tools" in greet
    assert 'output_modalities: ["audio"]' in greet
    assert "duplexLive = true" in go
    assert go.index("duplexLive = true") < go.rindex("sendRealtimeGreet")
    assert "if (!duplexLive) return false" in send
    assert "dc.readyState !== \"open\"" in send
    session = _fn(page, "sessionBody")
    assert "navigator.language" in session
    assert "timeZone" in session
    assert "locale:" in session
    assert "timezone:" in session
    assert 'locale: TEST_FORCE_ENGLISH ? "en"' in session
    assert "const TEST_FORCE_ENGLISH = true" in page
    assert "sessionBody()" in connect
    assert "tryGoDuplex()" in connect
    assert "canMarkDuplexLive" in go
    # Unsolicited first speech must not be a bare response.create (that
    # made the model volunteer get_disk_space). User text / tool results still create.
    bare = 'dc.send(JSON.stringify({ type: "response.create" }));'
    assert bare not in connect
    assert bare not in send
    assert "response.create" in greet


def test_look_ask_is_desktop_goal_and_forced_see_screen():
    page = _page()
    assert "function looksLikeLookAsk" in page
    assert "function lookResponseEvent" in page
    assert "function startLookResponse" in page
    assert "function finishGreetForUserAsk" in page
    run = _fn(page, "runTool")
    assert "looksLikeLookAsk(live)" in run or "looksLikeDesktopAsk(live)" in run
    assert "looksLikeLookAsk(lastUserGoal)" in run
    send = _fn(page, "sendUserText")
    assert "lookResponseEvent()" in send
    handle = _fn(page, "handleRealtimeEvent")
    assert "startLookResponse()" in handle
    assert "finishGreetForUserAsk()" in handle
    extracted = "\n".join(
        [
            _fn(page, "looksLikeLookAsk"),
            _fn(page, "looksLikeDesktopAsk"),
            _fn(page, "lookResponseEvent"),
            _fn(page, "startLookResponse"),
            _fn(page, "finishGreetForUserAsk"),
        ]
    )
    script = (
        "const TEST_FORCE_ENGLISH = true;\n"
        + extracted
        + """
    const sent = [];
    let greetInFlight = true;
    let restored = false;
    const dc = {
      readyState: "open",
      send: function (raw) { sent.push(JSON.parse(raw)); }
    };
    function restoreTalkTurnDetection() { restored = true; }
    if (!looksLikeLookAsk("what do you see on the screen")) process.exit(2);
    if (!looksLikeLookAsk("What do you see on the screen?")) process.exit(3);
    if (!looksLikeLookAsk("Can you... what do you see on your screen?")) process.exit(4);
    if (looksLikeLookAsk("can you hear me")) process.exit(5);
    if (looksLikeLookAsk("Really?")) process.exit(6);
    if (!looksLikeDesktopAsk("what do you see on the screen")) process.exit(7);
    const ev = lookResponseEvent();
    const text = String((ev.response || {}).instructions || "");
    if (ev.type !== "response.create") process.exit(8);
    if (text.indexOf("see_screen") < 0) process.exit(9);
    if (text.indexOf("Hello") < 0) process.exit(10);
    if (text.indexOf("English") < 0) process.exit(11);
    if (!ev.response.tool_choice || ev.response.tool_choice.name !== "see_screen") process.exit(12);
    startLookResponse();
    if (greetInFlight) process.exit(13);
    if (!restored) process.exit(14);
    if (!sent.length || sent[0].type !== "response.cancel") process.exit(15);
    if (sent[1].type !== "response.create") process.exit(16);
    if (String((sent[1].response || {}).instructions || "").indexOf("see_screen") < 0) process.exit(17);
    process.stdout.write(JSON.stringify({
      greetInFlight: greetInFlight,
      restored: restored,
      sentTypes: sent.map((s) => s.type),
      tool: (sent[1].response || {}).tool_choice
    }));
    """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = json.loads(result.stdout)
    assert runtime["greetInFlight"] is False
    assert runtime["restored"] is True
    assert runtime["sentTypes"] == ["response.cancel", "response.create"]
    assert runtime["tool"] == {"type": "function", "name": "see_screen"}


def test_public_realtime_transcript_and_tools_stay_on_the_page():
    page = _page()
    handle = _fn(page, "handleRealtimeEvent")
    assert "input_audio_transcription" in handle
    assert "setLiveYou" in handle
    assert "setLiveJarvis" in handle
    assert "commitAssistantTalk" in handle
    assert "assistantTalkFromEvent" in page
    assert "response.output_audio_transcript.delta" in page
    assert "response.done" in _fn(page, "assistantTalkFromEvent")
    assert "/api/jarvis/tools/run" in page
    assert "/api/jarvis/taint/clear" in page
    assert "function runTool" in page
    assert "function_call_arguments.done" in handle
    assert "function sendToolResult" in page
    run = _fn(page, "runTool")
    assert "lastUserGoal" in page
    assert "rememberUserGoal" in page
    assert "payload.goal = lastUserGoal" in run or "payload.goal=lastUserGoal" in run
    assert "JSON.stringify({ name: name, arguments: payload, allowed: publicTalkAllowed() })" in run
    assert "user_goal" not in run
    assert "sk-" not in run
    assert "OPENAI_API_KEY" not in run


def test_public_hire_speaks_first_and_never_says_empty_braces():
    page = _page()
    assert "function looksLikeHireAsk" in page
    assert "function hireStartLine" in page
    assert "function hireWaveLine" in page
    assert "function emptySpeech" in page
    assert "function startHireResponse" in page
    assert "function hireAfterToolEvent" in page
    assert "function speakHireIfSilent" in page
    assert "Making the next ones." in page
    assert "I'll make " in page
    assert "Never say {}" in page
    assert "void speak(line, true)" in page
    assert "const TEST_FORCE_ENGLISH = true" in page
    send = _fn(page, "sendUserText")
    assert "startHireResponse" in send
    handle = _fn(page, "handleRealtimeEvent")
    assert "startHireResponse" in handle
    assert "speakHireIfSilent" in handle
    commit = _fn(page, "commitAssistantTalk")
    assert "emptySpeech(said)" in commit
    send_tool = _fn(page, "sendToolResult")
    assert "isChildLimitOutput" in send_tool
    assert "speakHireWave" in send_tool
    ask = _fn(page, "ask")
    assert "emptySpeech(reply)" in ask
    extracted = "\n".join(
        [
            _fn(page, "looksLikeHireAsk"),
            _fn(page, "emptySpeech"),
            _fn(page, "hireCountWord"),
            _fn(page, "hireStartLine"),
            _fn(page, "hireWaveLine"),
            _fn(page, "isChildLimitOutput"),
            _fn(page, "hireAfterToolEvent"),
        ]
    )
    script = (
        "const TEST_FORCE_ENGLISH = true;\n"
        + extracted
        + """
    if (!looksLikeHireAsk("Create five different Tetris games. Use sub-agents as much as you can.")) process.exit(2);
    if (!looksLikeHireAsk("create 5 html files")) process.exit(3);
    if (looksLikeHireAsk("hello")) process.exit(4);
    if (!emptySpeech("{}")) process.exit(5);
    if (!emptySpeech("")) process.exit(6);
    if (emptySpeech("I'll make five different games.")) process.exit(7);
    const start = hireStartLine("Create five different Tetris games.");
    if (start !== "I'll make five different Tetris games.") process.exit(8);
    if (hireWaveLine() !== "Making the next ones.") process.exit(9);
    if (!isChildLimitOutput(JSON.stringify({ ok: false, error: "CHILD_LIMIT" }))) process.exit(10);
    const ev = hireAfterToolEvent(true);
    const text = String((ev.response || {}).instructions || "");
    if (text.indexOf("CHILD_LIMIT is not a stop") < 0) process.exit(11);
    if (text.indexOf("Never say {}") < 0) process.exit(12);
    if (text.indexOf("English") < 0) process.exit(13);
    process.stdout.write("ok");
    """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"


def test_mint_409_falls_back_to_browser_speech_and_ask():
    page = _page()
    connect = _fn(page, "connectRealtime")
    start_talk = _fn(page, "startTalk")
    start_browser = _fn(page, "startBrowserTalk")
    assert "token.fallback === \"browser_speech\"" in connect
    assert "startBrowserTalk()" in connect
    assert "startListen()" in start_talk
    assert "startBrowserTalk()" not in start_talk
    assert "OPENAI_API_KEY" not in connect
    assert "required" not in connect.lower()
    assert "startListen()" in start_browser
    assert "/api/jarvis/ask" in page
    assert "/api/jarvis/speak" in page
    assert "rec.continuous = true" in page
    assert "rec.continuous = false" not in page
    assert "speaking = true" in _fn(page, "speak")
    assert "haltRec()" in _fn(page, "speak")


def test_start_talk_connects_realtime_immediately_after_prefetch():
    """startTalk prefetches session, starts connectRealtime, does not await mint."""
    page = _page()
    start_talk = _fn(page, "startTalk")
    connect = _fn(page, "connectRealtime")
    boot = _fn(page, "bootTalk")
    idle = page.split("whenIdle(function () {", 1)[1].split("});", 1)[0]
    assert "wantListen = true" in start_talk
    assert "canListen = true" in start_talk
    assert "prefetchSession()" in start_talk
    assert "const upgrade = mintRealtime" in start_talk
    assert "if (upgrade) void connectRealtime()" in start_talk
    assert "startListen()" in start_talk
    assert "paintMic()" in start_talk
    assert "speakFirstHello" not in start_talk
    assert "playHelloSrc" not in start_talk
    assert "/jarvis/hello/" not in start_talk
    assert "/api/jarvis/speak" not in start_talk
    assert "await " not in start_talk
    assert "await connectRealtime" not in start_talk
    assert "/api/jarvis/realtime/session" not in start_talk
    assert "/api/jarvis/health" not in start_talk
    assert start_talk.index("prefetchSession()") < start_talk.index("connectRealtime")
    assert start_talk.index("connectRealtime") < start_talk.index("startListen()")
    assert "startBrowserTalk()" not in start_talk
    assert "mintRealtime = false" in _fn(page, "startBrowserTalk")
    assert "/api/jarvis/realtime/session" in connect
    assert "getUserMedia" in connect
    assert connect.index("/api/jarvis/realtime/session") < connect.index("getUserMedia")
    assert "stopListen()" in _fn(page, "tryGoDuplex")
    assert "duplexLive = true" in _fn(page, "tryGoDuplex")
    go = _fn(page, "tryGoDuplex")
    assert go.index("duplexLive = true") < go.index("stopListen()")
    assert go.index("duplexLive = true") < go.rindex("sendRealtimeGreet")
    assert "startBrowserTalk()" in connect
    assert "failRealtimeNoDuplex" in connect or "armDuplexWait" in connect
    assert "hasRemoteAudioTrack" in connect
    assert "/api/jarvis/health" not in boot
    assert "void health(true)" in page
    assert "void bootTalk()" in page
    assert "prefetchSession()" in page
    assert "prefetchSession()" not in idle
    assert page.index("prefetchSession()") < page.index("void bootTalk()")
    script = """
    const events = [];
    let mintRealtime = true;
    let listening = false;
    function prefetchSession() { events.push("prefetchSession"); }
    function startListen() { listening = true; events.push("startListen"); }
    function paintMic() { events.push("paintMic"); }
    function startBrowserTalk() { mintRealtime = false; events.push("startBrowserTalk"); }
    async function connectRealtime() {
      events.push("connectRealtime");
      events.push("fetch:session");
      await new Promise((r) => setTimeout(r, 80));
      events.push("mint:done");
    }
    async function startTalk() {
      prefetchSession();
      const upgrade = mintRealtime;
      if (upgrade) void connectRealtime();
      startListen();
      paintMic();
    }
    const p = startTalk();
    if (!listening) process.exit(2);
    if (events[0] !== "prefetchSession") process.exit(3);
    if (events.includes("mint:done")) process.exit(4);
    if (events.includes("startBrowserTalk")) process.exit(5);
    if (!events.includes("connectRealtime")) process.exit(6);
    if (events.includes("speakFirstHello")) process.exit(10);
    Promise.resolve(p).then(() => {
      if (events.includes("mint:done")) process.exit(7);
      if (!listening) process.exit(8);
      if (mintRealtime !== true) process.exit(9);
      process.stdout.write(JSON.stringify({ events: events, mintRealtime: mintRealtime }));
    });
    """
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = json.loads(result.stdout)
    assert runtime["events"][0] == "prefetchSession"
    assert runtime["events"].index("prefetchSession") < runtime["events"].index("connectRealtime")
    assert runtime["events"].index("connectRealtime") < runtime["events"].index("startListen")
    assert runtime["events"].index("connectRealtime") < runtime["events"].index("fetch:session")
    assert "mint:done" not in runtime["events"]
    assert "startBrowserTalk" not in runtime["events"]
    assert "speakFirstHello" not in runtime["events"]
    assert runtime["mintRealtime"] is True


def test_first_hello_is_realtime_after_duplex_not_cached_clip():
    """Boot first hello is gpt-realtime RTC audio after duplexLive, not a clip or /speak."""
    page = _page()
    start_talk = _fn(page, "startTalk")
    boot = _fn(page, "bootTalk")
    connect = _fn(page, "connectRealtime")
    prefetch = _fn(page, "prefetchSession")
    idle = page.split("whenIdle(function () {", 1)[1].split("});", 1)[0]
    head = page.split("<style>", 1)[0]
    assert "speakFirstHello" not in page
    assert "playHelloSrc" not in page
    assert "prefetchHello" not in page
    assert "helloClip" not in page
    assert 'id="hello-en"' not in page
    assert 'id="hello-tr"' not in page
    assert 'src="/jarvis/hello/en.mp3"' not in page
    assert 'src="/jarvis/hello/tr.mp3"' not in page
    assert "/jarvis/hello/" not in start_talk
    assert "/jarvis/hello/" not in connect
    assert "/jarvis/hello/" not in boot
    assert "/jarvis/hello/" not in prefetch
    assert "/api/jarvis/speak" not in start_talk
    assert "/api/jarvis/speak" not in connect
    assert "/api/jarvis/speak" not in boot
    assert "/api/jarvis/speak" not in prefetch
    assert "speechSynthesis" not in page
    assert "await connectRealtime" not in start_talk
    assert "await connectRealtime" not in boot
    assert "prefetchSession()" in start_talk
    assert "if (upgrade) void connectRealtime()" in start_talk
    assert start_talk.index("prefetchSession()") < start_talk.index("connectRealtime")
    assert "/api/jarvis/realtime/session" in head
    assert 'method: "POST"' in head
    assert "prefetchSession()" not in idle
    assert "loadPcScreen()" in idle
    assert "void health()" in idle
    assert page.index("prefetchSession()") < page.index("void bootTalk()")
    assert page.index("__jarvisSessionPrefetch") < page.index("function startTalk")
    greet = _fn(page, "realtimeGreetEvent")
    go = _fn(page, "tryGoDuplex")
    send = _fn(page, "sendRealtimeGreet")
    assert "Greet in one short line in English only" in greet
    assert "Greet in one short line in the user's language" in greet
    assert "duplexLive = true" in go
    assert go.index("duplexLive = true") < go.rindex("sendRealtimeGreet")
    assert "if (!duplexLive) return false" in send
    assert "dc.readyState !== \"open\"" in send
    assert "srcObject" in connect
    assert "hasRemoteAudioTrack" in connect
    assert "tryGoDuplex()" in connect
    assert "/jarvis/hello/" not in greet
    assert "/jarvis/hello/" not in go
    assert "/jarvis/hello/" not in send
    assert "/api/jarvis/speak" not in greet
    assert "/api/jarvis/speak" not in go
    assert "/api/jarvis/speak" not in send
    assert "speechSynthesis" not in greet
    extracted = "\n".join(
        [
            _fn(page, "assistantTextFromParts"),
            _fn(page, "assistantTalkFromEvent"),
            _fn(page, "hasRemoteAudioTrack"),
            _fn(page, "canMarkDuplexLive"),
            _fn(page, "realtimeGreetEvent"),
        ]
    )
    script = (
        "const TEST_FORCE_ENGLISH = true;\n"
        + extracted
        + """
    const events = [];
    const sent = [];
    const log = [];
    let greeted = false;
    let duplexLive = false;
    let channelOpen = false;
    let remoteAudio = false;
    const sessionReady = true;
    const sink = { srcObject: null };
    const dc = {
      readyState: "closed",
      send: function (raw) { sent.push(JSON.parse(raw)); }
    };
    function markAndGreet() {
      if (duplexLive) {
        if (!greeted && dc.readyState === "open") {
          greeted = true;
          events.push("realtimeHello");
          dc.send(JSON.stringify(realtimeGreetEvent()));
        }
        return;
      }
      if (!sessionReady) return;
      if (!canMarkDuplexLive(channelOpen, remoteAudio, sink, dc)) return;
      duplexLive = true;
      events.push("duplexLive");
      greeted = true;
      events.push("realtimeHello");
      dc.send(JSON.stringify(realtimeGreetEvent()));
    }
    function logAssistant(event) {
      const talk = assistantTalkFromEvent(event);
      if (talk && (talk.text || "").trim()) {
        log.push({ who: "jarvis", text: String(talk.text).trim() });
        events.push("assistantLog");
      }
    }
    events.push("prefetch");
    events.push("connect");
    channelOpen = true;
    dc.readyState = "open";
    markAndGreet();
    if (duplexLive) process.exit(2);
    if (greeted) process.exit(3);
    if (sent.length) process.exit(4);
    sink.srcObject = { getAudioTracks: function () { return [{ readyState: "live" }]; } };
    remoteAudio = true;
    markAndGreet();
    if (!duplexLive) process.exit(6);
    if (!greeted) process.exit(7);
    if (events.indexOf("prefetch") > events.indexOf("connect")) process.exit(8);
    if (events.indexOf("duplexLive") > events.indexOf("realtimeHello")) process.exit(9);
    if (!sent.length || sent[0].type !== "response.create") process.exit(10);
    if (String((sent[0].response || {}).instructions || "").indexOf("English only") < 0) process.exit(11);
    if (String((sent[0].response || {}).instructions || "").indexOf("user's language") >= 0) process.exit(17);
    logAssistant({ type: "response.output_audio_transcript.done", transcript: "Hey, I am here." });
    if (!log.length || log[0].text !== "Hey, I am here.") process.exit(12);
    if (events.some((e) => String(e).includes("/jarvis/hello/"))) process.exit(13);
    if (events.some((e) => String(e).includes("/api/jarvis/speak"))) process.exit(14);
    if (JSON.stringify(sent).includes("/jarvis/hello/")) process.exit(15);
    if (JSON.stringify(sent).includes("/api/jarvis/speak")) process.exit(16);
    process.stdout.write(JSON.stringify({
      events: events,
      greeted: greeted,
      duplexLive: duplexLive,
      log: log,
      sentTypes: sent.map((s) => s.type)
    }));
    """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = json.loads(result.stdout)
    assert runtime["greeted"] is True
    assert runtime["duplexLive"] is True
    assert runtime["events"][0] == "prefetch"
    assert runtime["events"].index("prefetch") < runtime["events"].index("connect")
    assert runtime["events"].index("duplexLive") < runtime["events"].index("realtimeHello")
    assert runtime["events"].index("realtimeHello") < runtime["events"].index("assistantLog")
    assert runtime["log"] == [{"who": "jarvis", "text": "Hey, I am here."}]
    assert runtime["sentTypes"] == ["response.create"]
    assert "/jarvis/hello/en.mp3" not in runtime["events"]
    assert all("/api/jarvis/speak" not in str(ev) for ev in runtime["events"])


def test_first_hello_path_does_not_play_clip_or_speak_api():
    """Boot first-hello does not play /jarvis/hello/en.mp3 or POST /speak."""
    page = _page()
    start_talk = _fn(page, "startTalk")
    connect = _fn(page, "connectRealtime")
    prefetch = _fn(page, "prefetchSession")
    boot = _fn(page, "bootTalk")
    greet = _fn(page, "realtimeGreetEvent")
    go = _fn(page, "tryGoDuplex")
    send = _fn(page, "sendRealtimeGreet")
    for src in (start_talk, connect, prefetch, boot, greet, go, send):
        assert "/jarvis/hello/en.mp3" not in src
        assert "/jarvis/hello/tr.mp3" not in src
        assert "/api/jarvis/speak" not in src
        assert "new Audio(" not in src
        assert "speechSynthesis" not in src
    assert "speakFirstHello" not in page
    assert "playHelloSrc" not in page
    assert 'src="/jarvis/hello/en.mp3"' not in page
    assert "prefetchSession()" in start_talk
    assert start_talk.index("prefetchSession()") <= start_talk.index("connectRealtime")
    assert "Greet in one short line in English only" in greet
    assert "Greet in one short line in the user's language" in greet
    script = """
    const events = [];
    globalThis.fetch = (url) => {
      events.push("fetch:" + String(url));
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };
    globalThis.Audio = function (src) {
      events.push("audio:" + String(src || ""));
      this.play = () => { events.push("play:" + String(src || "")); return Promise.resolve(); };
    };
    const played = [];
    function playHelloSrc(src) { played.push(src); events.push("playHelloSrc:" + src); }
    function speakFirstHello() { playHelloSrc("/jarvis/hello/en.mp3"); }
    function prefetchSession() { events.push("prefetchSession"); }
    async function startTalk() {
      prefetchSession();
      events.push("startTalk");
    }
    prefetchSession();
    startTalk();
    if (played.length) process.exit(2);
    if (events.some((e) => e.includes("/jarvis/hello/"))) process.exit(3);
    if (events.some((e) => e.includes("/api/jarvis/speak"))) process.exit(4);
    if (events.indexOf("prefetchSession") > events.indexOf("startTalk")) process.exit(5);
    process.stdout.write(JSON.stringify({ events: events, played: played }));
    """
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = json.loads(result.stdout)
    assert runtime["played"] == []
    assert all("/jarvis/hello/" not in ev for ev in runtime["events"])
    assert all("/api/jarvis/speak" not in ev for ev in runtime["events"])
    assert runtime["events"].index("prefetchSession") <= runtime["events"].index("startTalk")


def test_mute_me_is_the_only_stop():
    page = _page()
    assert "if (muteMe) stopListen()" in page
    assert "setMicEnabled(false)" in page
    assert "response.cancel" in page
    assert 'aria-label="Mute me"' in page
    assert "id=\"stopBtn\"" not in page
    click = page[page.find('mic.addEventListener("click"') :]
    assert "void startTalk()" in click
    assert "startListen()" not in click.split("});", 1)[0]
    start_talk = _fn(page, "startTalk")
    assert "if (duplexLive)" in start_talk
    assert "disarmFirstClickTalk()" in start_talk
    mute = _fn(page, "onMuteMe")
    assert "stopListen()" in mute
    assert "setMicEnabled(false)" in mute


def test_public_page_does_not_pin_spanish_speech_recognition():
    page = _page()
    assert 'rec.lang = "es-ES"' not in page
    assert "es-ES" not in page
    assert "rec.continuous = true" in page
    assert 'rec.lang = "en-US"' not in page


def test_public_page_marks_test_force_english():
    page = _page()
    assert "const TEST_FORCE_ENGLISH = true" in page
    assert "var TEST_FORCE_ENGLISH = true" in page
    greet = _fn(page, "realtimeGreetEvent")
    session = _fn(page, "sessionBody")
    assert "TEST_FORCE_ENGLISH" in greet
    assert "English only" in greet
    assert 'locale: TEST_FORCE_ENGLISH ? "en"' in session
    assert "navigator.language" in session


def test_greet_instructions_english_only_when_test_force_english():
    """When the TEST pin is on, the live greet is English only — not Italy/Korea."""
    page = _page()
    greet = _fn(page, "realtimeGreetEvent")
    script = (
        "const TEST_FORCE_ENGLISH = true;\n"
        + greet
        + """
    const ev = realtimeGreetEvent();
    const text = String((ev.response || {}).instructions || "");
    if (text.indexOf("English only") < 0) process.exit(2);
    if (text.indexOf("Italian") < 0) process.exit(3);
    if (text.indexOf("Korean") < 0) process.exit(4);
    if (text.indexOf("Portuguese") < 0) process.exit(5);
    if (text.indexOf("user's language") >= 0) process.exit(6);
    if (text.indexOf("Ciao") >= 0) process.exit(7);
    if (text.indexOf("Olá") >= 0) process.exit(8);
    process.stdout.write(text);
    """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = result.stdout
    assert "English only" in text
    assert "Do not use Italian, Korean, Portuguese" in text
    assert "user's language" not in text


def test_greet_instructions_locale_again_when_test_force_english_off():
    """Flip the TEST pin off and the greet is the user's language again."""
    page = _page()
    greet = _fn(page, "realtimeGreetEvent")
    script = (
        "const TEST_FORCE_ENGLISH = false;\n"
        + greet
        + """
    const ev = realtimeGreetEvent();
    const text = String((ev.response || {}).instructions || "");
    if (text.indexOf("user's language") < 0) process.exit(2);
    if (text.indexOf("English only") >= 0) process.exit(3);
    process.stdout.write(text);
    """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "user's language" in result.stdout
    assert "English only" not in result.stdout


def test_realtime_session_does_not_pin_spanish():
    from app.jarvis.realtime import (
        JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
        JARVIS_REALTIME_INSTRUCTIONS,
        TEST_FORCE_ENGLISH,
        build_realtime_session_config,
    )

    cfg = build_realtime_session_config()
    assert cfg.get("output_modalities") == ["audio"]
    tx = cfg["audio"]["input"]["transcription"]
    lang = str(tx.get("language") or "").strip().lower()
    assert tx.get("model") == "gpt-4o-mini-transcribe"
    if TEST_FORCE_ENGLISH:
        assert lang == "en"
    else:
        assert "language" not in tx or not lang or lang == "auto"
        assert lang not in {"es", "pt", "fr", "en", "es-es", "pt-br", "en-us"}
    for text in (JARVIS_PUBLIC_REALTIME_INSTRUCTIONS, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "the page locale" in low
        assert "after they speak" in low
        assert "never pick a random romance language" in low
        assert "default spoken language is english" not in low


def test_realtime_instructions_test_force_english_pins_english(monkeypatch):
    """TEST pin: Italy / Korea / Brazil locale still gets English only."""
    from app.jarvis import realtime as rt

    monkeypatch.setattr(rt, "TEST_FORCE_ENGLISH", True)
    for locale, timezone in (
        ("it-IT", "Europe/Rome"),
        ("ko-KR", "Asia/Seoul"),
        ("pt-BR", "America/Sao_Paulo"),
        ("de-DE", "Europe/Berlin"),
        (None, "Europe/Rome"),
    ):
        text = rt.build_instructions(locale=locale, timezone=timezone)
        low = text.lower()
        assert "TEST_FORCE_ENGLISH" in text
        assert "Default language until they speak: English." in text
        assert "English only" in text
        assert "Do not invent Italian, Korean, or Portuguese." in text
        assert "First hello in English" in text
        assert "the page locale" not in low
        assert "Default language until they speak: Italian" not in text
        assert "Default language until they speak: Korean" not in text
        assert "Default language until they speak: Portuguese" not in text
        assert "Default language until they speak: German" not in text
        assert "Oi! Eu estou bem" not in text
        cfg = rt.build_realtime_session_config(locale=locale, timezone=timezone)
        tx = cfg["audio"]["input"]["transcription"]
        assert tx.get("language") == "en"
        assert "Default language until they speak: English." in str(
            cfg.get("instructions") or ""
        )


def test_realtime_instructions_locale_default_not_english_lock(monkeypatch):
    """Locale is the greeting default. Olá is not prescribed unless locale is pt."""
    from app.jarvis import realtime as rt

    monkeypatch.setattr(rt, "TEST_FORCE_ENGLISH", False)
    assert rt.locale_language_name("tr-TR") == "Turkish"
    assert rt.locale_language_name("de-DE") == "German"
    assert rt.locale_language_name("en-US") == "English"
    assert rt.locale_language_name("pt-BR") == "Portuguese"
    assert rt.locale_language_name(None, "Europe/Istanbul") == "Turkish"
    assert rt.locale_language_name("en-US", "America/Sao_Paulo") == "English"

    for locale, name in (
        ("de-DE", "German"),
        ("tr-TR", "Turkish"),
        ("en-US", "English"),
    ):
        text = rt.build_instructions(locale=locale)
        line = f"Default language until they speak: {name}."
        assert line in text
        assert "Do not use another language for the greeting." in text
        assert "Default language until they speak: Portuguese" not in text
        assert "Oi! Eu estou bem" not in text
        assert "E você, como é que tá?" not in text
        assert "TEST_FORCE_ENGLISH" not in text
        cfg = rt.build_realtime_session_config(locale=locale)
        assert line in str(cfg.get("instructions") or "")
        tx = cfg["audio"]["input"]["transcription"]
        assert "language" not in tx or not tx.get("language")

    pt = rt.build_instructions(locale="pt-BR")
    assert "Default language until they speak: Portuguese." in pt
    assert "Oi! Eu estou bem" not in pt

    bare = rt.build_instructions()
    assert "Default language until they speak:" not in bare
    assert "default spoken language is english" not in bare.lower()
    assert "First words of a session: casual English" not in bare
    assert "Patient teacher. No tools for that." in bare
    assert "Coach in the language they asked in." in bare
    for text in (
        rt.JARVIS_PUBLIC_REALTIME_INSTRUCTIONS,
        rt.JARVIS_REALTIME_INSTRUCTIONS,
        bare,
    ):
        assert "Oi! Eu estou bem" not in text
        assert "never pick a random romance language" in text.lower()


@pytest.mark.asyncio
async def test_mint_session_test_force_english_ignores_italy_locale(
    tmp_path, monkeypatch
):
    """TEST pin: it-IT / Europe/Rome still mints English, transcription en."""
    import httpx
    from app.config import get_settings
    from app.jarvis import gateway as gw
    from app.jarvis import realtime as rt
    from app.jarvis import realtime_routes, settings_store
    from app.main import create_app

    monkeypatch.setattr(rt, "TEST_FORCE_ENGLISH", True)
    monkeypatch.setattr(realtime_routes, "TEST_FORCE_ENGLISH", True)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
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
            session = (json or {}).get("session") or {}
            minted.append(session)
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
                json={
                    "voice": "marin",
                    "locale": "it-IT",
                    "timezone": "Europe/Rome",
                },
                headers={"Accept-Language": "it-IT,it;q=0.9"},
            )
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    assert len(minted) == 1
    session = minted[0]
    text = str(session.get("instructions") or "")
    assert "TEST_FORCE_ENGLISH" in text
    assert "Default language until they speak: English." in text
    assert "Do not invent Italian, Korean, or Portuguese." in text
    assert "Default language until they speak: Italian" not in text
    assert "Ciao" not in text
    assert "Oi! Eu estou bem" not in text
    tx = session["audio"]["input"]["transcription"]
    assert tx.get("language") == "en"
    assert "sk-" not in text
    assert "sk-test-openai" not in text


@pytest.mark.asyncio
async def test_mint_session_uses_page_locale_not_random_portuguese(
    tmp_path, monkeypatch
):
    import httpx
    from app.config import get_settings
    from app.jarvis import gateway as gw
    from app.jarvis import realtime as rt
    from app.jarvis import realtime_routes, settings_store
    from app.main import create_app

    monkeypatch.setattr(rt, "TEST_FORCE_ENGLISH", False)
    monkeypatch.setattr(realtime_routes, "TEST_FORCE_ENGLISH", False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
    minted: list[str] = []

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
            session = (json or {}).get("session") or {}
            minted.append(str(session.get("instructions") or ""))
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
                json={
                    "voice": "marin",
                    "locale": "de-DE",
                    "timezone": "Europe/Berlin",
                },
                headers={"Accept-Language": "pt-BR,pt;q=0.9"},
            )
            accept = await ac.post(
                "/api/jarvis/realtime/session",
                json={"voice": "marin"},
                headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
            )
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    assert r.status_code == 200
    assert accept.status_code == 200
    assert len(minted) == 2
    german, turkish = minted
    assert "Default language until they speak: German." in german
    assert "Default language until they speak: Portuguese" not in german
    assert "Oi! Eu estou bem" not in german
    assert "Default language until they speak: Turkish." in turkish
    from app.jarvis.realtime import build_realtime_session_config

    tx = build_realtime_session_config(locale="de-DE")["audio"]["input"]["transcription"]
    assert "language" not in tx or not tx.get("language")


@pytest.mark.asyncio
async def test_public_health_reports_realtime_listen_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_REALTIME", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-optional-upgrade")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mom-key-not-real")
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
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
            r = await ac.get("/jarvis/api/jarvis/health")
            page = await ac.get("/jarvis/", follow_redirects=True)
    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    body = r.json()
    assert r.status_code == 200
    assert body["realtime"] is True
    assert body["listen_mode"] == "openai_realtime"
    assert "OPENAI_API_KEY" not in r.text
    assert "sk-test-openai-optional-upgrade" not in r.text
    html = page.text
    assert "/api/jarvis/realtime/session" in html
    assert "sk-" not in html
    assert "OPENAI_API_KEY" not in html
