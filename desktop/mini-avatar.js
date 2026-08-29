/**
 * Pure helpers for the Windows always-on-top mini Jarvis avatar
 * (ORCH-397 overlay, ORCH-398 talk-from-avatar).
 * No Electron imports — Node tests can require this file.
 */
const AVATAR = {
  size: 88,
  bubbleWidth: 248,
  bubbleHeight: 172,
  margin: 24,
  dragThresholdPx: 5,
  alwaysOnTopLevel: "status",
  raisesMainOnClick: false,
  defaultLaunch: "avatar",
  expandOpensMain: true,
  closeMainReturnsToAvatar: true,
  openBubbleOnLaunch: false,
  skipTaskbar: false,
  focusable: true,
  ignoreMouseEvents: false,
};

const TALK = {
  maxAskChars: 240,
  maxReplyChars: 160,
  raisesMain: false,
};

const ASSISTANT_TALK_EVENTS = {
  delta: [
    "response.audio_transcript.delta",
    "response.output_audio_transcript.delta",
    "response.text.delta",
    "response.output_text.delta",
  ],
  done: [
    "response.audio_transcript.done",
    "response.output_audio_transcript.done",
    "response.text.done",
    "response.output_text.done",
  ],
};

function defaultPosition(workArea) {
  return {
    x: workArea.x + workArea.width - AVATAR.size - AVATAR.margin,
    y: workArea.y + workArea.height - AVATAR.size - AVATAR.margin,
  };
}

function clampPosition(pos, workArea, size) {
  const w = typeof size === "number" ? size : size.width;
  const h = typeof size === "number" ? size : size.height;
  const minX = workArea.x;
  const minY = workArea.y;
  const maxX = workArea.x + workArea.width - w;
  const maxY = workArea.y + workArea.height - h;
  return {
    x: Math.round(Math.min(Math.max(pos.x, minX), Math.max(minX, maxX))),
    y: Math.round(Math.min(Math.max(pos.y, minY), Math.max(minY, maxY))),
  };
}

function shouldShowMainOnLaunch() {
  return false;
}

function shouldOpenBubbleOnLaunch() {
  return AVATAR.openBubbleOnLaunch === true;
}

function shouldShowAvatar(state) {
  if (!state || state.shuttingDown) return false;
  // Default surface is the mini avatar. Hide it only while the full
  // window is up, not minimized, and focused.
  if (state.mainVisible && !state.mainMinimized && state.mainFocused) {
    return false;
  }
  return true;
}

function shouldHideMainOnClose(state) {
  return !(state && state.shuttingDown);
}

function shouldQuitOnAvatarClose(_state) {
  // Avatar X, taskbar close, and tray Quit are the same as Quit Jarvis.
  // Mom must not need Task Manager. Talk close still hides to the avatar.
  return true;
}

function shouldQuitOnAvatarCloseButton() {
  return true;
}

function bubbleBounds(current, open) {
  const robotRight = current.x + current.width;
  const robotBottom = current.y + current.height;
  if (open) {
    return {
      x: robotRight - AVATAR.bubbleWidth,
      y: robotBottom - AVATAR.bubbleHeight,
      width: AVATAR.bubbleWidth,
      height: AVATAR.bubbleHeight,
    };
  }
  return {
    x: robotRight - AVATAR.size,
    y: robotBottom - AVATAR.size,
    width: AVATAR.size,
    height: AVATAR.size,
  };
}

function isClickNotDrag(dx, dy, threshold) {
  const limit = threshold == null ? AVATAR.dragThresholdPx : threshold;
  return Math.abs(dx) <= limit && Math.abs(dy) <= limit;
}

function clipLine(text, max) {
  const s = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
  if (!s) return "";
  const limit = typeof max === "number" ? max : TALK.maxReplyChars;
  if (s.length <= limit) return s;
  return s.slice(0, Math.max(0, limit - 1)).trimEnd() + "…";
}

function normalizeAsk(text) {
  return clipLine(text, TALK.maxAskChars);
}

function clipReply(text) {
  return clipLine(text, TALK.maxReplyChars);
}

function normalizeMuted(value) {
  return value === true || value === 1 || value === "1" || value === "true";
}

function assistantTalkFromEvent(event) {
  if (!event || !event.type) return null;
  if (ASSISTANT_TALK_EVENTS.delta.indexOf(event.type) >= 0) {
    return { kind: "delta", text: String(event.delta || event.transcript || "") };
  }
  if (ASSISTANT_TALK_EVENTS.done.indexOf(event.type) >= 0) {
    return { kind: "done", text: String(event.transcript || event.text || "") };
  }
  if (event.type === "response.output_item.done" && event.item && event.item.type === "message") {
    const parts = Array.isArray(event.item.content) ? event.item.content : [];
    const text = parts
      .map((p) => (p && (p.transcript || p.text)) || "")
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
    if (text) return { kind: "done", text };
  }
  return null;
}

function buildTalkState(partial) {
  const src = partial && typeof partial === "object" ? partial : {};
  const status = String(src.status || "idle");
  return {
    open: src.open === true,
    status: status,
    you: clipLine(src.you, TALK.maxAskChars),
    reply: clipReply(src.reply),
    muted: normalizeMuted(src.muted),
    raisesMain: false,
  };
}

function talkLine(state, canListen) {
  const src = state && typeof state === "object" ? state : {};
  const status = String(src.status || "");
  const reply = clipReply(src.reply);
  const you = clipLine(src.you, TALK.maxAskChars);
  if (reply) return reply;
  if (status === "listening") return "Listening…";
  if (status === "thinking") return you || "Thinking…";
  if (status === "unavailable") return "Can't hear right now";
  if (status === "error") {
    // OpenRouter-only installs can listen via Web Speech. Never show
    // "Can't hear" when that path is available.
    if (canListen === false) return "Can't hear right now";
    return "Listening…";
  }
  if (you) return you;
  return "Click or speak";
}

function talkPathFromHealth(health) {
  const h = health && typeof health === "object" ? health : {};
  const listenMode = String(h.listen_mode || "");
  const speakMode = String(h.speak_mode || "");
  const openrouter = h.openrouter === true;
  const canListen =
    h.can_listen === true ||
    openrouter ||
    listenMode === "browser_speech";
  const canSpeak =
    h.can_speak === true ||
    speakMode === "openrouter_tts" ||
    speakMode === "hosted_tts" ||
    speakMode === "openai_tts" ||
    speakMode === "openai_realtime";
  // Health wins. browser_speech / openrouter_tts / hosted_tts must talk
  // without minting a Realtime session. realtime=true alone is not enough
  // — that used to mean "flag on" and sent Mom's Talk button to a missing
  // OpenAI key.
  const useBrowser =
    listenMode === "browser_speech" ||
    speakMode === "openrouter_tts" ||
    speakMode === "hosted_tts";
  const mintRealtime =
    !useBrowser && h.realtime === true && listenMode === "openai_realtime";
  if (mintRealtime) {
    return {
      path: "openai_realtime",
      listenMode: "openai_realtime",
      canListen: true,
      canSpeak: true,
      mintRealtime: true,
    };
  }
  if (canListen || useBrowser) {
    return {
      path: "browser_speech",
      listenMode: "browser_speech",
      canListen: true,
      canSpeak: !!canSpeak,
      mintRealtime: false,
    };
  }
  return {
    path: "none",
    listenMode: "none",
    canListen: false,
    canSpeak: false,
    mintRealtime: false,
  };
}

function connectActionFromHealth(health) {
  const path = talkPathFromHealth(health);
  if (path.mintRealtime) return "mint_realtime_session";
  if (path.canListen) return "start_browser_listen";
  return "unavailable";
}

function afterRealtimeSessionFailure(health, sessionBody) {
  const path = talkPathFromHealth(health);
  const body = sessionBody && typeof sessionBody === "object" ? sessionBody : {};
  if (
    path.canListen ||
    path.path === "browser_speech" ||
    body.fallback === "browser_speech" ||
    body.listen_mode === "browser_speech" ||
    body.can_listen === true ||
    body.openrouter === true
  ) {
    return "start_browser_listen";
  }
  return "unavailable";
}

function shouldOpenBubbleForTalk(_state, _bubbleAlreadyOpen) {
  // Office-assistant style: the bubble opens only when the user clicks
  // the robot (or types an ask). Hidden CEO talk / autolisten / greeting
  // must not grow the overlay to the 248×172 bubble on cold start.
  return false;
}

function avatarWindowIsClickable(opts) {
  const src = opts && typeof opts === "object" ? opts : {};
  return src.focusable === true && src.skipTaskbar === false && src.ignoreMouseEvents !== true;
}

function speakIfUnmuted(muted, text, speakFn) {
  const clean = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
  if (!clean) return { spoke: false, cancelled: false };
  if (muted) return { spoke: false, cancelled: true };
  if (typeof speakFn === "function") speakFn(clean);
  return { spoke: true, cancelled: false };
}

function muteRealtimeOutput(sink, muted) {
  const on = muted === true;
  if (sink && typeof sink === "object") {
    sink.muted = on;
    if ("volume" in sink) sink.volume = on ? 0 : 1;
  }
  return { muted: on, volume: on ? 0 : 1 };
}

function buildMuteState(partial) {
  const src = partial && typeof partial === "object" ? partial : {};
  return { muted: src.muted === true };
}

function trayMenuItems(muted) {
  return [
    { id: "mute", label: muted ? "Unmute" : "Mute" },
    { id: "quit", label: "Quit Jarvis" },
  ];
}

function avatarWindowOptions(bounds) {
  return {
    width: bounds.width || AVATAR.size,
    height: bounds.height || AVATAR.size,
    x: bounds.x,
    y: bounds.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: AVATAR.skipTaskbar === true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    movable: true,
    hasShadow: false,
    show: false,
    focusable: AVATAR.focusable !== false,
    backgroundColor: "#00000000",
    title: "Jarvis",
    autoHideMenuBar: true,
    thickFrame: false,
  };
}

module.exports = {
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
  clipLine,
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
};
