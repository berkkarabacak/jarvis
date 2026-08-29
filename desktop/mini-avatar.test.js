/**
 * Node assertions for desktop/mini-avatar.js (ORCH-397 / ORCH-398).
 * Run: node desktop/mini-avatar.test.js
 */
const assert = require("assert");
const {
  AVATAR,
  TALK,
  ASSISTANT_TALK_EVENTS,
  defaultPosition,
  clampPosition,
  shouldShowMainOnLaunch,
  shouldOpenBubbleOnLaunch,
  shouldShowAvatar,
  shouldHideMainOnClose,
  shouldQuitOnAvatarClose,
  shouldQuitOnAvatarCloseButton,
  avatarWindowIsClickable,
  speakIfUnmuted,
  muteRealtimeOutput,
  buildMuteState,
  trayMenuItems,
  bubbleBounds,
  isClickNotDrag,
  normalizeAsk,
  clipReply,
  normalizeMuted,
  assistantTalkFromEvent,
  buildTalkState,
  talkLine,
  talkPathFromHealth,
  connectActionFromHealth,
  afterRealtimeSessionFailure,
  shouldOpenBubbleForTalk,
  avatarWindowOptions,
} = require("./mini-avatar");

const work = { x: 0, y: 0, width: 1920, height: 1080 };

assert.strictEqual(AVATAR.raisesMainOnClick, false);
assert.strictEqual(AVATAR.defaultLaunch, "avatar");
assert.strictEqual(AVATAR.expandOpensMain, true);
assert.strictEqual(AVATAR.closeMainReturnsToAvatar, true);
assert.strictEqual(AVATAR.openBubbleOnLaunch, false);
assert.strictEqual(shouldShowMainOnLaunch(), false);
assert.strictEqual(shouldOpenBubbleOnLaunch(), false);
assert.strictEqual(AVATAR.alwaysOnTopLevel, "status");
assert.ok(AVATAR.size <= 120, "avatar must stay tiny");
assert.ok(AVATAR.bubbleWidth < 400, "talk bubble must not become a second window");
assert.ok(AVATAR.bubbleHeight < 200);
assert.ok(AVATAR.bubbleHeight >= 160, "bubble must fit a short reply + tiny ask box");
assert.strictEqual(TALK.raisesMain, false);
assert.ok(TALK.maxAskChars <= 240);
assert.ok(TALK.maxReplyChars <= 160);

const pos = defaultPosition(work);
assert.strictEqual(pos.x, 1920 - AVATAR.size - AVATAR.margin);
assert.strictEqual(pos.y, 1080 - AVATAR.size - AVATAR.margin);

assert.deepStrictEqual(
  clampPosition({ x: -40, y: 5000 }, work, AVATAR.size),
  { x: 0, y: 1080 - AVATAR.size }
);
assert.deepStrictEqual(
  clampPosition({ x: 10, y: 10 }, work, AVATAR.size),
  { x: 10, y: 10 }
);

assert.strictEqual(
  shouldShowAvatar({
    mainExists: true,
    mainVisible: true,
    mainMinimized: false,
    mainFocused: true,
  }),
  false,
  "hide overlay while the main Jarvis window is focused"
);
assert.strictEqual(
  shouldShowAvatar({
    mainExists: true,
    mainVisible: true,
    mainMinimized: false,
    mainFocused: false,
  }),
  true,
  "show overlay when Chrome/Excel/Word has focus"
);
assert.strictEqual(
  shouldShowAvatar({
    mainExists: true,
    mainVisible: true,
    mainMinimized: true,
    mainFocused: false,
  }),
  true
);
assert.strictEqual(
  shouldShowAvatar({
    mainExists: true,
    mainVisible: false,
    mainMinimized: false,
    mainFocused: false,
  }),
  true
);
assert.strictEqual(
  shouldShowAvatar({
    mainExists: false,
    mainVisible: false,
    mainMinimized: false,
    mainFocused: false,
  }),
  true,
  "avatar-only cold start still shows the overlay"
);
assert.strictEqual(shouldShowAvatar(null), false);
assert.strictEqual(shouldShowAvatar({ shuttingDown: true, mainVisible: false }), false);
assert.strictEqual(shouldHideMainOnClose({ shuttingDown: false }), true);
assert.strictEqual(shouldHideMainOnClose({ shuttingDown: true }), false);
assert.strictEqual(
  shouldQuitOnAvatarClose({ mainVisible: false, mainMinimized: false }),
  true,
  "closing the avatar while Talk is hidden is a real quit"
);
assert.strictEqual(
  shouldQuitOnAvatarClose({ mainVisible: true, mainMinimized: false }),
  true,
  "avatar X / taskbar close always quits, even if Talk is up"
);
assert.strictEqual(
  shouldQuitOnAvatarClose({ mainVisible: true, mainMinimized: true }),
  true
);
assert.strictEqual(
  shouldQuitOnAvatarCloseButton(),
  true,
  "quit-on-avatar-close-button"
);

const collapsed = { x: 1800, y: 960, width: AVATAR.size, height: AVATAR.size };
const open = bubbleBounds(collapsed, true);
assert.strictEqual(open.width, AVATAR.bubbleWidth);
assert.strictEqual(open.height, AVATAR.bubbleHeight);
assert.strictEqual(open.x + open.width, collapsed.x + collapsed.width);
assert.strictEqual(open.y + open.height, collapsed.y + collapsed.height);
const back = bubbleBounds(open, false);
assert.deepStrictEqual(back, collapsed);

assert.strictEqual(isClickNotDrag(0, 0), true);
assert.strictEqual(isClickNotDrag(3, 2), true);
assert.strictEqual(isClickNotDrag(20, 0), false);

const opts = avatarWindowOptions(pos);
assert.strictEqual(opts.alwaysOnTop, true);
assert.strictEqual(opts.frame, false);
assert.strictEqual(opts.transparent, true);
assert.strictEqual(opts.skipTaskbar, false);
assert.strictEqual(opts.show, false);
assert.strictEqual(opts.focusable, true);
assert.strictEqual(opts.fullscreenable, false);
assert.ok(avatarWindowIsClickable(opts), "avatar window is clickable");
assert.ok(opts.width <= 120);
assert.ok(opts.height <= 120);
assert.strictEqual(AVATAR.skipTaskbar, false);
assert.strictEqual(AVATAR.focusable, true);
assert.strictEqual(AVATAR.ignoreMouseEvents, false);

assert.strictEqual(normalizeAsk("  what time is it?  "), "what time is it?");
assert.strictEqual(normalizeAsk("   "), "");
assert.ok(normalizeAsk("x".repeat(400)).length <= TALK.maxAskChars);
assert.ok(normalizeAsk("x".repeat(400)).endsWith("…"));
assert.strictEqual(clipReply("  Sure, 3pm.  "), "Sure, 3pm.");
assert.ok(clipReply("y".repeat(400)).length <= TALK.maxReplyChars);

assert.deepStrictEqual(
  assistantTalkFromEvent({
    type: "response.output_audio_transcript.delta",
    delta: "Hello",
  }),
  { kind: "delta", text: "Hello" }
);
assert.deepStrictEqual(
  assistantTalkFromEvent({
    type: "response.audio_transcript.done",
    transcript: "Hello there",
  }),
  { kind: "done", text: "Hello there" }
);
assert.deepStrictEqual(
  assistantTalkFromEvent({
    type: "response.output_item.done",
    item: {
      type: "message",
      content: [{ transcript: "On it." }],
    },
  }),
  { kind: "done", text: "On it." }
);
assert.strictEqual(assistantTalkFromEvent({ type: "response.created" }), null);
assert.ok(ASSISTANT_TALK_EVENTS.delta.length >= 2);
assert.ok(ASSISTANT_TALK_EVENTS.done.length >= 2);

const talk = buildTalkState({
  status: "speaking",
  you: "  what time?  ",
  reply: "  Three.  ",
});
assert.strictEqual(talk.raisesMain, false);
assert.strictEqual(talk.you, "what time?");
assert.strictEqual(talk.reply, "Three.");
assert.strictEqual(talk.status, "speaking");
assert.strictEqual(
  shouldOpenBubbleForTalk({ reply: "hi", status: "listening" }, false),
  false,
  "talk / autolisten events must not pop the bubble; click does"
);
assert.strictEqual(shouldOpenBubbleForTalk({ reply: "hi" }, true), false);
assert.strictEqual(shouldOpenBubbleForTalk({ status: "idle" }, false), false);
assert.strictEqual(shouldOpenBubbleForTalk({ status: "error" }, false), false);

assert.strictEqual(talkLine({ status: "listening" }), "Listening…");
assert.strictEqual(talkLine({ status: "thinking", you: "hi" }), "hi");
assert.strictEqual(
  talkLine({ status: "error" }, true),
  "Listening…",
  "OpenRouter-only installs stay ready instead of Can't hear"
);
assert.strictEqual(talkLine({ status: "error" }), "Listening…");
assert.strictEqual(talkLine({ status: "error" }, false), "Can't hear right now");
assert.strictEqual(talkLine({ status: "unavailable" }), "Can't hear right now");
assert.strictEqual(talkLine({ status: "idle", reply: "42 GB free" }), "42 GB free");

const openRouterOnlyHealth = {
  ok: true,
  realtime: false,
  can_listen: true,
  listen_mode: "browser_speech",
  can_speak: true,
  speak_mode: "openrouter_tts",
  neural_tts: true,
  openrouter: true,
};
assert.deepStrictEqual(talkPathFromHealth(openRouterOnlyHealth).path, "browser_speech");
assert.strictEqual(talkPathFromHealth(openRouterOnlyHealth).mintRealtime, false);
assert.strictEqual(talkPathFromHealth(openRouterOnlyHealth).canListen, true);
assert.strictEqual(talkPathFromHealth(openRouterOnlyHealth).canSpeak, true);
assert.strictEqual(
  connectActionFromHealth(openRouterOnlyHealth),
  "start_browser_listen",
  "OpenRouter-only Talk/call must not mint a Realtime session"
);
assert.strictEqual(
  afterRealtimeSessionFailure(openRouterOnlyHealth, {
    detail: "OPENAI_API_KEY is not set (required for Realtime voice)",
  }),
  "start_browser_listen",
  "a missing OpenAI key must not block talk"
);

const staleRealtimeFlag = {
  realtime: true,
  can_listen: true,
  listen_mode: "browser_speech",
  speak_mode: "openrouter_tts",
  openrouter: true,
};
assert.strictEqual(
  connectActionFromHealth(staleRealtimeFlag),
  "start_browser_listen",
  "listen_mode=browser_speech / speak_mode=openrouter_tts beat a stale realtime flag"
);

const realtimeReady = {
  realtime: true,
  can_listen: true,
  listen_mode: "openai_realtime",
  can_speak: true,
  speak_mode: "openai_realtime",
};
assert.strictEqual(connectActionFromHealth(realtimeReady), "mint_realtime_session");
assert.strictEqual(
  afterRealtimeSessionFailure(realtimeReady, { can_listen: true, fallback: "browser_speech" }),
  "start_browser_listen"
);

const hostedTalkHealth = {
  ok: true,
  realtime: false,
  can_listen: true,
  listen_mode: "browser_speech",
  can_speak: true,
  speak_mode: "hosted_tts",
  neural_tts: true,
  openrouter: false,
  hosted_talk: true,
};
assert.strictEqual(talkPathFromHealth(hostedTalkHealth).mintRealtime, false);
assert.strictEqual(talkPathFromHealth(hostedTalkHealth).canListen, true);
assert.strictEqual(talkPathFromHealth(hostedTalkHealth).canSpeak, true);
assert.strictEqual(connectActionFromHealth(hostedTalkHealth), "start_browser_listen");

const noKeys = {
  realtime: false,
  can_listen: false,
  listen_mode: "none",
  can_speak: false,
  speak_mode: "none",
  openrouter: false,
};
assert.strictEqual(connectActionFromHealth(noKeys), "unavailable");
assert.strictEqual(afterRealtimeSessionFailure(noKeys, {}), "unavailable");
assert.strictEqual(talkPathFromHealth({}).mintRealtime, false);

const launchTalk = buildTalkState({ status: "listening" });
assert.strictEqual(launchTalk.open, false, "talk state defaults closed");
assert.strictEqual(launchTalk.muted, false);
assert.strictEqual(normalizeMuted(true), true);
assert.strictEqual(normalizeMuted("true"), true);
assert.strictEqual(normalizeMuted("nope"), false);
assert.strictEqual(buildTalkState({ muted: true }).muted, true);

const collapsedLaunch = avatarWindowOptions(
  bubbleBounds({ x: pos.x, y: pos.y, width: AVATAR.size, height: AVATAR.size }, shouldOpenBubbleOnLaunch())
);
assert.strictEqual(collapsedLaunch.width, AVATAR.size);
assert.strictEqual(collapsedLaunch.height, AVATAR.size);
assert.notStrictEqual(collapsedLaunch.width, AVATAR.bubbleWidth);
assert.notStrictEqual(collapsedLaunch.height, AVATAR.bubbleHeight);

// quit-on-avatar-close-button + taskbar or tray quit
assert.strictEqual(shouldQuitOnAvatarCloseButton(), true);
assert.deepStrictEqual(trayMenuItems(false), [
  { id: "mute", label: "Mute" },
  { id: "quit", label: "Quit Jarvis" },
]);
assert.deepStrictEqual(trayMenuItems(true)[0], { id: "mute", label: "Unmute" });
assert.strictEqual(trayMenuItems(false).some((item) => item.id === "quit"), true);

// mute stops speak (neural TTS + Realtime sink; never SAPI)
assert.deepStrictEqual(buildMuteState({ muted: true }), { muted: true });
assert.deepStrictEqual(buildMuteState({}), { muted: false });
const spoken = [];
assert.deepStrictEqual(speakIfUnmuted(false, "Hello there", (t) => spoken.push(t)), {
  spoke: true,
  cancelled: false,
});
assert.deepStrictEqual(spoken, ["Hello there"]);
assert.deepStrictEqual(speakIfUnmuted(true, "Stay quiet", (t) => spoken.push(t)), {
  spoke: false,
  cancelled: true,
});
assert.deepStrictEqual(spoken, ["Hello there"]);
const sink = { muted: false, volume: 1 };
assert.deepStrictEqual(muteRealtimeOutput(sink, true), { muted: true, volume: 0 });
assert.strictEqual(sink.muted, true);
assert.strictEqual(sink.volume, 0);
muteRealtimeOutput(sink, false);
assert.strictEqual(sink.muted, false);
assert.strictEqual(sink.volume, 1);

console.log("mini-avatar helpers ok");
