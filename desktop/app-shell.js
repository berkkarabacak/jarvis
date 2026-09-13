/**
 * Windows Jarvis 3-pane shell contract (epic #66, issues #74 / #67 / #68 / #69).
 *
 * Pure helpers — Node tests can require this file. The visible chrome is
 * app/static/desktop.html. Electron loads /desktop as the main window.
 * /ceo stays the Realtime / Settings page (hidden talk engine + Settings).
 *
 * #68 live PC: iframe of localhost noVNC inside #live-computer. BrowserView
 * is a native overlay and would need manual bounds on collapse; an iframe
 * hides with the pane. Hide / Chat only blanks the iframe and must not
 * stop jarvis-computer.
 *
 * #69 middle pane: live You / Jarvis thread + composer. Typed send hits
 * /api/jarvis/ask. History is /api/jarvis/talk/last. Mic starts listen
 * (browser speech, or the hidden /ceo talk engine already used by Electron).
 */
const SHELL_PATH = "/desktop";
const TALK_PATH = "/ceo";
const SETTINGS_PATH = "/ceo";
const SCREEN_VIEWER_PATH = "/ceo/jarvis-screen";
const NOVNC_URL = "http://127.0.0.1:6080";
const NOVNC_SESSION_URL = `${NOVNC_URL}/vnc.html?autoconnect=1&resize=scale`;
const ASK_PATH = "/api/jarvis/ask";
const TALK_LAST_PATH = "/api/jarvis/talk/last";
const TALK_LOG_PATH = "/api/jarvis/talk/log";
const SPEAK_PATH = "/api/jarvis/speak";
const MAX_ASK_CHARS = 240;
const MAX_REPLY_CHARS = 2000;

const SHELL = {
  path: SHELL_PATH,
  defaultLaunch: "main",
  theme: "light",
  leftWidth: 280,
  rightWidth: 340,
  minMiddleWidth: 360,
  minWindowWidth: 800,
  // #68: iframe of the existing :6080 session. BrowserView is harder to
  // collapse with the chrome and is not used for the in-pane live PC.
  screenEmbed: "iframe",
  screenEmbedRejected: "BrowserView",
};

const LABELS = {
  app: "Jarvis",
  search: "Search",
  agents: "Helpers",
  chats: "Chats",
  groups: "Group chats",
  composer: "Type a message",
  add: "Add",
  talk: "Talk",
  send: "Send",
  settings: "Settings",
  hideLeft: "Hide chats",
  showLeft: "Show chats",
  hideRight: "Hide computer",
  showRight: "Show computer",
  screen: "Jarvis's screen",
  routines: "Routines",
  computer: "Computer",
  terminal: "Chat only",
  plugins: "Plugins",
  profile: "You",
  emptyChat: "This chat is ready. Messages will show up here.",
  you: "You",
  lead: "Jarvis",
  ready: "Ready when you are",
  listening: "Listening…",
  thinking: "Jarvis is thinking…",
  addSoon: "Photos and files come later.",
  cantTalk: "Can't talk right now",
  comingSoon: "Coming soon",
  screenSoon: "The live computer will show here.",
  screenLive: "Jarvis's screen is live.",
  screenHidden: "Jarvis's screen is hidden. The computer keeps running.",
  screenDown: "Jarvis's computer is not running.",
  terminalScreen: "Chat only — the computer stays hidden.",
  hideScreen: "Hide screen",
  showScreen: "Show Jarvis's screen",
  startComputer: "Start Jarvis's computer",
  openScreen: "Open Jarvis's screen",
};

function talkQuery(extra) {
  const q = new URLSearchParams({ autolisten: "1", handsfree: "1", desktop: "1" });
  if (extra && extra.settings) q.set("settings", "1");
  return q;
}

function shellQuery(extra) {
  const q = new URLSearchParams({ desktop: "1" });
  if (extra && extra.settings) q.set("settings", "1");
  return q;
}

function pageHref(port, path, query) {
  const q = query instanceof URLSearchParams ? query : new URLSearchParams(query || {});
  return `http://127.0.0.1:${port}${path}?${q.toString()}`;
}

function talkHref(port, extra) {
  return pageHref(port, TALK_PATH, talkQuery(extra));
}

function shellHref(port, extra) {
  return pageHref(port, SHELL_PATH, shellQuery(extra));
}

function normalizePaneState(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    left: src.left !== false,
    right: src.right !== false,
  };
}

function togglePane(state, which) {
  const next = normalizePaneState(state);
  if (which === "left") next.left = !next.left;
  if (which === "right") next.right = !next.right;
  return next;
}

function fitPanesToWidth(width, state) {
  const next = normalizePaneState(state);
  const w = Number(width) || 0;
  if (w > 0 && w < 900) {
    return { left: false, right: false };
  }
  return next;
}

function layoutColumns(state) {
  const panes = normalizePaneState(state);
  return {
    left: panes.left ? SHELL.leftWidth : 0,
    right: panes.right ? SHELL.rightWidth : 0,
    middle: "flex",
    minMiddle: SHELL.minMiddleWidth,
    leftOpen: panes.left,
    rightOpen: panes.right,
  };
}

function normalizeTalkMode(value) {
  const mode = String(value || "").trim().toLowerCase();
  return mode === "terminal" ? "terminal" : "computer";
}

function screenShouldShow(state) {
  const src = state && typeof state === "object" ? state : {};
  const talkMode = normalizeTalkMode(src.talkMode);
  if (talkMode === "terminal") return false;
  if (src.paneOpen === false) return false;
  if (src.screenShown === false) return false;
  return true;
}

function applyTalkMode(value, extras) {
  const talkMode = normalizeTalkMode(value);
  const terminal = talkMode === "terminal";
  const extra = extras && typeof extras === "object" ? extras : {};
  const paneOpen = extra.paneOpen !== false;
  const screenShown = terminal ? false : extra.screenShown !== false;
  const show = screenShouldShow({ talkMode, paneOpen, screenShown });
  return {
    talkMode,
    showComputerSlot: show,
    screenShown,
    paneOpen,
    screenLabel: terminal
      ? LABELS.terminalScreen
      : show
        ? LABELS.screenLive
        : LABELS.screenHidden,
    modeLabel: terminal ? LABELS.terminal : LABELS.computer,
    embedSrc: show ? NOVNC_SESSION_URL : "",
    pauseEmbed: !show,
    stopComputer: false,
  };
}

function liveComputerView(state) {
  const src = state && typeof state === "object" ? state : {};
  const talkMode = normalizeTalkMode(src.talkMode);
  const paneOpen = src.paneOpen !== false;
  const screenShown = talkMode === "terminal" ? false : src.screenShown !== false;
  const running = src.running === true;
  const show = screenShouldShow({ talkMode, paneOpen, screenShown });
  return {
    method: SHELL.screenEmbed,
    talkMode,
    visible: show,
    driving: show,
    paused: !show,
    embedSrc: show && running ? NOVNC_SESSION_URL : "",
    startAllowed: show && !running,
    stopComputer: false,
    killsComputerOnHide: false,
  };
}

function pauseLiveComputer() {
  return {
    method: SHELL.screenEmbed,
    embedSrc: "",
    paused: true,
    stopComputer: false,
    stopUrls: [],
    note: "Blank the iframe. Do not stop jarvis-computer.",
  };
}

function screenEmbedPlan() {
  return {
    method: SHELL.screenEmbed,
    rejected: SHELL.screenEmbedRejected,
    novnc: NOVNC_URL,
    session: NOVNC_SESSION_URL,
    viewerPath: SCREEN_VIEWER_PATH,
    note: "Iframe collapses with the pane. BrowserView needs manual bounds. Do not kill jarvis-computer when the right pane collapses.",
  };
}

function clipTalkText(text, max) {
  const s = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
  if (!s) return "";
  const limit = typeof max === "number" ? max : MAX_REPLY_CHARS;
  if (s.length <= limit) return s;
  return s.slice(0, Math.max(0, limit - 1)).trimEnd() + "…";
}

function clipAsk(text) {
  return clipTalkText(text, MAX_ASK_CHARS);
}

function clipReply(text) {
  return clipTalkText(text, MAX_REPLY_CHARS);
}

function normalizeRole(role) {
  const who = String(role || "").trim().toLowerCase();
  if (who === "you" || who === "user") return "you";
  if (who === "jarvis" || who === "assistant") return "jarvis";
  return "";
}

function turnKey(turn) {
  const src = turn && typeof turn === "object" ? turn : {};
  return `${normalizeRole(src.role)}\0${clipReply(src.text)}`;
}

function speechTurns(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const out = [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const role = normalizeRole(row.role);
    const text = clipReply(row.text);
    if (!role || !text) continue;
    out.push({
      role,
      text,
      speaker: role === "you" ? LABELS.you : LABELS.lead,
      ts: String(row.ts || ""),
    });
  }
  return out;
}

function pushUniqueTurn(turns, turn) {
  const next = Array.isArray(turns) ? turns.slice() : [];
  const role = normalizeRole(turn && turn.role);
  const text = clipReply(turn && turn.text);
  if (!role || !text) return next;
  const item = {
    role,
    text,
    speaker: role === "you" ? LABELS.you : LABELS.lead,
    ts: String((turn && turn.ts) || ""),
  };
  const key = turnKey(item);
  if (next.some((row) => turnKey(row) === key)) return next;
  next.push(item);
  return next;
}

function mergeHistory(turns, rows) {
  let next = Array.isArray(turns) ? turns.slice() : [];
  for (const row of speechTurns(rows)) {
    next = pushUniqueTurn(next, row);
  }
  return next;
}

function applyTalkEvent(turns, event) {
  const src = event && typeof event === "object" ? event : {};
  const you = clipAsk(src.you);
  const reply = clipReply(src.reply);
  let next = Array.isArray(turns) ? turns.slice() : [];
  if (you) next = pushUniqueTurn(next, { role: "you", text: you });
  if (reply) next = pushUniqueTurn(next, { role: "jarvis", text: reply });
  const status = String(src.status || (reply ? "idle" : you ? "thinking" : "") || "idle");
  let subtitle = LABELS.ready;
  if (status === "listening") subtitle = LABELS.listening;
  else if (status === "thinking" || (you && !reply)) subtitle = LABELS.thinking;
  else if (status === "unavailable" || status === "error") subtitle = LABELS.cantTalk;
  return { turns: next, status, subtitle, you, reply };
}

function composerSubmit(text) {
  const asked = clipAsk(text);
  return { ok: !!asked, text: asked };
}

function askRequest(text) {
  const asked = clipAsk(text);
  return {
    ok: !!asked,
    url: ASK_PATH,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: { text: asked },
  };
}

function historyRequest() {
  return { url: TALK_LAST_PATH, method: "GET" };
}

function talkLogRequest(role, text) {
  const who = normalizeRole(role);
  const said = who === "you" ? clipAsk(text) : clipReply(text);
  return {
    ok: !!(who && said),
    url: TALK_LOG_PATH,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: { role: who, text: said },
  };
}

function speakRequest(text) {
  const said = clipReply(text);
  return {
    ok: !!said,
    url: SPEAK_PATH,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: { text: said },
  };
}

function parseAskReply(payload) {
  const body = payload && typeof payload === "object" ? payload : {};
  const ui = body.ui != null ? body.ui : body.result;
  const reply = clipReply(body.reply || (ui && ui.summary) || "");
  return {
    reply,
    ok: !!reply,
    needsConfirm: !!(ui && ui.needs_confirm),
    emptyLabel: reply ? "" : LABELS.cantTalk,
  };
}

const LEADS = {
  jarvis: { id: "jarvis", name: "Jarvis", ready: true },
  writer: { id: "writer", name: "Writer", ready: false },
  helper: { id: "helper", name: "Helper", ready: false },
  finder: { id: "finder", name: "Finder", ready: false },
  buyra: { id: "buyra", name: "Buyra", ready: true },
  home: { id: "home", name: "Home", ready: true },
};

function selectLead(id) {
  const key = String(id || "").trim().toLowerCase();
  const known = LEADS[key] || LEADS.jarvis;
  return {
    id: known.id,
    name: known.name,
    subtitle: known.ready ? LABELS.ready : LABELS.comingSoon,
    talkTarget: "jarvis",
    ready: known.ready === true,
  };
}

function micPlan(hasDesktopBridge) {
  return {
    startListen: true,
    via: hasDesktopBridge ? "talk-engine" : "browser",
    fallbackAsk: true,
    browserSpeech: true,
  };
}

function chatView(turns, extras) {
  const extra = extras && typeof extras === "object" ? extras : {};
  const rows = speechTurns(turns);
  return {
    empty: rows.length === 0,
    emptyLabel: LABELS.emptyChat,
    turns: rows,
    title: extra.title || LABELS.lead,
    subtitle: extra.subtitle || LABELS.ready,
  };
}

module.exports = {
  SHELL,
  LABELS,
  LEADS,
  SHELL_PATH,
  TALK_PATH,
  SETTINGS_PATH,
  SCREEN_VIEWER_PATH,
  NOVNC_URL,
  NOVNC_SESSION_URL,
  ASK_PATH,
  TALK_LAST_PATH,
  TALK_LOG_PATH,
  SPEAK_PATH,
  MAX_ASK_CHARS,
  MAX_REPLY_CHARS,
  talkQuery,
  shellQuery,
  pageHref,
  talkHref,
  shellHref,
  normalizePaneState,
  togglePane,
  fitPanesToWidth,
  layoutColumns,
  normalizeTalkMode,
  applyTalkMode,
  screenShouldShow,
  liveComputerView,
  pauseLiveComputer,
  screenEmbedPlan,
  clipTalkText,
  clipAsk,
  clipReply,
  normalizeRole,
  speechTurns,
  pushUniqueTurn,
  mergeHistory,
  applyTalkEvent,
  composerSubmit,
  askRequest,
  historyRequest,
  talkLogRequest,
  speakRequest,
  parseAskReply,
  selectLead,
  micPlan,
  chatView,
};
