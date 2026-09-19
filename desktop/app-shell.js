/**
 * Windows Jarvis 3-pane shell contract (epic #66).
 * Issues #74 / #67 / #68 / #69 / #70 / #71 / #72 / #73.
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
 *
 * #70 left lists: Search, +, Chat/Helpers/Plugins/Routines nav, Assistants,
 * Recent chats, View all chats. Each list section collapses on its own.
 * Selecting a row focuses the middle header. Asks still go to Jarvis.
 *
 * #71 light data: Helpers = Jarvis (live) + documented stubs that are not
 * connected. Chats = talk history when present. Group chats stay empty
 * until a real group list exists. Never invent live teammates.
 *
 * #72 Routines: under the live PC. Real local schedules from
 * /api/jarvis/routines (JobStore). Honest empty when none. + does not
 * invent a create flow.
 *
 * #73 Settings gear opens /ceo?settings=1 (talk_mode / model / voice /
 * computer stay on /api/jarvis/settings). Narrow windows collapse
 * left/right by default.
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
const SETTINGS_API_PATH = "/api/jarvis/settings";
const ROUTINES_PATH = "/api/jarvis/routines";
const SCHEDULES_PATH = "/api/schedules";
const MAX_ASK_CHARS = 240;
const MAX_REPLY_CHARS = 2000;
const SESSION_GAP_MS = 45 * 60 * 1000;
const CHAT_TITLE_CHARS = 36;

const SHELL = {
  path: SHELL_PATH,
  defaultLaunch: "main",
  theme: "light",
  leftWidth: 276,
  rightWidth: 360,
  minMiddleWidth: 360,
  minWindowWidth: 800,
  collapseBelow: 900,
  // #68: iframe of the existing :6080 session. BrowserView is harder to
  // collapse with the chrome and is not used for the in-pane live PC.
  screenEmbed: "iframe",
  screenEmbedRejected: "BrowserView",
};

const LABELS = {
  app: "Jarvis",
  teammate: "Your AI teammate",
  search: "Search assistants, chats…",
  agents: "Helpers",
  assistants: "Assistants",
  chats: "Recent chats",
  groups: "Group chats",
  viewAll: "View all chats",
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
  liveComputer: "Live Computer",
  routines: "Routines",
  computer: "Computer",
  terminal: "Chat only",
  plugins: "Plugins",
  profile: "You",
  profileMail: "berk@jarvis.app",
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
  openScreen: "Open in new window",
  usingComputer: "Jarvis is using the computer…",
  connected: "Connected",
  newChat: "New chat",
  notConnected: "Not connected yet",
  emptyChats: "No chats yet. Send a message to start.",
  emptyGroups: "No group chats yet. They come later.",
  nothingMatches: "Nothing matches.",
  pluginsSoon: "Plugins come later.",
  profileSoon: "Your profile comes later.",
  emptyRoutines: "No routines yet.",
  addRoutine: "Add routine",
  createRoutine: "Create routine",
  addRoutineSoon: "Adding a routine comes later.",
  routineReadOnly: "This routine is on the schedule. Changing it comes later.",
  hidePanesHint: "Chat is in the middle. Jarvis's screen is on the right. Hide chats or Hide computer when you want more room.",
};

const DATA_SOURCES = {
  helpers: "local-lead + documented-stub",
  chats: "talk-history",
  groups: "none",
  routines: "local-schedules",
  note: "Only Jarvis is a live helper. Stubs are not connected. Group chats have no list yet. Routines are real local schedules, or empty.",
};

const HELPER_STUBS = [
  { id: "writer", name: "Writer", initial: "W", color: "#0f766e" },
  { id: "helper", name: "Helper", initial: "H", color: "#b45309" },
  { id: "finder", name: "Finder", initial: "F", color: "#7c3aed" },
];

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

function isNarrowWidth(width) {
  const w = Number(width) || 0;
  return w > 0 && w < SHELL.collapseBelow;
}

function fitPanesToWidth(width, state) {
  const next = normalizePaneState(state);
  if (isNarrowWidth(width)) {
    return { left: false, right: false };
  }
  return next;
}

function defaultPanesForWidth(width) {
  return fitPanesToWidth(width, { left: true, right: true });
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

function makeTurn(turn) {
  const role = normalizeRole(turn && turn.role);
  const text = clipReply(turn && turn.text);
  if (!role || !text) return null;
  return {
    role,
    text,
    speaker: role === "you" ? LABELS.you : LABELS.lead,
    ts: String((turn && turn.ts) || ""),
  };
}

function pushUniqueTurn(turns, turn) {
  const next = Array.isArray(turns) ? turns.slice() : [];
  const item = makeTurn(turn);
  if (!item) return next;
  const key = turnKey(item);
  if (next.some((row) => turnKey(row) === key)) return next;
  next.push(item);
  return next;
}

function appendTurn(turns, turn) {
  const next = Array.isArray(turns) ? turns.slice() : [];
  const item = makeTurn(turn);
  if (!item) return next;
  const last = next[next.length - 1];
  if (last && turnKey(last) === turnKey(item)) return next;
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
  if (you) next = appendTurn(next, { role: "you", text: you });
  if (reply) next = appendTurn(next, { role: "jarvis", text: reply });
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

function helpersFromInventory() {
  const jarvis = {
    id: "jarvis",
    name: LABELS.lead,
    initial: "J",
    color: "#2563EB",
    subtitle: LABELS.ready,
    source: "local-lead",
    kind: "helper",
    live: true,
    ready: true,
    unread: 0,
    talkTarget: "jarvis",
  };
  const stubs = HELPER_STUBS.map((row) => ({
    id: row.id,
    name: row.name,
    initial: row.initial,
    color: row.color,
    subtitle: LABELS.notConnected,
    source: "documented-stub",
    kind: "helper",
    live: false,
    ready: false,
    unread: 0,
    talkTarget: "jarvis",
  }));
  return [jarvis, ...stubs];
}

const LEADS = Object.fromEntries(helpersFromInventory().map((row) => [row.id, row]));

function groupChatsFromInventory() {
  return [];
}

function parseTurnTime(ts) {
  const raw = String(ts || "").trim();
  if (!raw) return 0;
  const n = Date.parse(raw);
  return Number.isFinite(n) ? n : 0;
}

function formatChatWhen(ts, now) {
  const n = parseTurnTime(ts);
  if (!n) return "";
  const d = new Date(n);
  const ref = now instanceof Date ? now : new Date();
  const startToday = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate()).getTime();
  const startYest = startToday - 86400000;
  if (n >= startToday) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  if (n >= startYest) return "Yesterday";
  return d.toLocaleDateString([], { month: "numeric", day: "numeric", year: "numeric" });
}

function friendlyModel(data) {
  const src = data && typeof data === "object" ? data : {};
  const name = String(src.helper_name || "").trim();
  if (name) return name;
  const model = String(src.model || "").trim();
  if (!model) return LABELS.lead;
  const parts = model.split("/");
  return parts[parts.length - 1] || LABELS.lead;
}

function splitTalkSessions(turns) {
  const speech = speechTurns(turns);
  const groups = [];
  let current = [];
  let prevTs = 0;
  for (const row of speech) {
    const ts = parseTurnTime(row.ts);
    if (current.length && prevTs && ts && ts - prevTs > SESSION_GAP_MS) {
      groups.push(current);
      current = [];
    }
    current.push(row);
    if (ts) prevTs = ts;
  }
  if (current.length) groups.push(current);
  return groups;
}

function titleFromSession(session, isLatest) {
  if (isLatest) return LABELS.lead;
  const firstYou = (Array.isArray(session) ? session : []).find((row) => row && row.role === "you");
  const raw = firstYou ? clipAsk(firstYou.text) : LABELS.lead;
  if (!raw) return LABELS.lead;
  if (raw.length <= CHAT_TITLE_CHARS) return raw;
  return `${raw.slice(0, Math.max(1, CHAT_TITLE_CHARS - 1)).trimEnd()}…`;
}

function chatsFromHistory(turns) {
  const sessions = splitTalkSessions(turns);
  if (!sessions.length) return [];
  return sessions
    .slice()
    .reverse()
    .map((session, index) => {
      const last = session[session.length - 1];
      const first = session[0] || {};
      const live = index === 0;
      const stamp = String(first.ts || index).toLowerCase().replace(/[^a-z0-9]+/g, "");
      return {
        id: live ? "talk-live" : `talk-${stamp || index}`,
        name: titleFromSession(session, live),
        preview: last ? last.text : "",
        when: formatChatWhen(last && last.ts),
        source: "talk-history",
        kind: "chat",
        live,
        ready: true,
        unread: 0,
        talkTarget: "jarvis",
      };
    });
}

function normalizeNavSections(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    helpers: src.helpers !== false,
    chats: src.chats !== false,
    groups: src.groups !== false,
  };
}

function toggleNavSection(state, which) {
  const next = normalizeNavSections(state);
  const key = String(which || "").trim().toLowerCase();
  if (key === "helpers" || key === "chats" || key === "groups") {
    next[key] = !next[key];
  }
  return next;
}

function filterNavItems(items, query) {
  const list = Array.isArray(items) ? items : [];
  const q = String(query || "").replace(/\s+/g, " ").trim().toLowerCase();
  if (!q) return list.slice();
  return list.filter((row) => {
    if (!row || typeof row !== "object") return false;
    const hay = [row.name, row.preview, row.subtitle]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    return hay.includes(q);
  });
}

function leftNavView(state) {
  const src = state && typeof state === "object" ? state : {};
  const query = String(src.query || "");
  const searching = query.replace(/\s+/g, " ").trim().length > 0;
  const helpers = filterNavItems(helpersFromInventory(), query);
  const chats = filterNavItems(chatsFromHistory(src.turns), query);
  const groups = filterNavItems(groupChatsFromInventory(), query);
  return {
    helpers,
    chats,
    groups,
    sections: normalizeNavSections(src.sections),
    query,
    searching,
    emptyHelpers: helpers.length === 0,
    emptyChats: chats.length === 0,
    emptyGroups: groups.length === 0,
    emptyChatsLabel: searching ? LABELS.nothingMatches : LABELS.emptyChats,
    emptyGroupsLabel: searching ? LABELS.nothingMatches : LABELS.emptyGroups,
    plusLabel: LABELS.newChat,
    sources: DATA_SOURCES,
  };
}

function selectLead(id, extras) {
  const extra = extras && typeof extras === "object" ? extras : {};
  const key = String(id || "").trim().toLowerCase();
  const helpers = helpersFromInventory();
  const chats = Array.isArray(extra.chats) ? extra.chats : chatsFromHistory(extra.turns);
  const groups = Array.isArray(extra.groups) ? extra.groups : [];
  const found = helpers.concat(chats, groups).find((row) => String(row.id).toLowerCase() === key);
  const known = found || helpers[0];
  const ready = known.ready === true;
  return {
    id: known.id,
    name: known.name,
    subtitle: ready ? LABELS.ready : (known.subtitle || LABELS.notConnected),
    talkTarget: "jarvis",
    ready,
    source: known.source || (ready ? "local-lead" : "documented-stub"),
    kind: known.kind || "helper",
    live: known.live === true,
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

function settingsPlan() {
  return {
    fromChrome: true,
    via: "gear",
    path: SETTINGS_PATH,
    query: { settings: "1", desktop: "1" },
    href: talkHref(8787, { settings: true }),
    persist: SETTINGS_API_PATH,
    fields: ["model", "realtime_voice", "computer_kind", "talk_mode"],
    talkMode: true,
    note: "Gear opens /ceo?settings=1. Model, voice, computer, and talk_mode stay on /api/jarvis/settings.",
  };
}

function settingsRequest() {
  return { url: SETTINGS_API_PATH, method: "GET" };
}

function persistTalkModeRequest(value) {
  const talkMode = normalizeTalkMode(value);
  return {
    url: SETTINGS_API_PATH,
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: { talk_mode: talkMode },
  };
}

function routinesRequest() {
  return { url: ROUTINES_PATH, method: "GET" };
}

function addRoutinePlan() {
  return {
    ok: false,
    canCreate: false,
    label: LABELS.addRoutineSoon,
    note: "Creating routines is not available yet.",
  };
}

function routineRow(row) {
  if (!row || typeof row !== "object") return null;
  const id = String(row.id || "").trim();
  const name = String(row.name || "").trim();
  if (!id || !name) return null;
  const when = String(row.when || row.schedule_human || row.subtitle || "").trim()
    || (row.enabled === false ? "Off" : "On the schedule");
  return {
    id,
    name,
    when,
    enabled: row.enabled !== false,
    source: row.source || DATA_SOURCES.routines,
    live: row.live !== false,
    readOnly: row.read_only !== false,
  };
}

function routinesFromSchedules(payload) {
  const body = payload && typeof payload === "object" ? payload : {};
  const raw = Array.isArray(body.routines)
    ? body.routines
    : Array.isArray(body.schedules)
      ? body.schedules
      : Array.isArray(payload)
        ? payload
        : [];
  const items = [];
  for (const row of raw) {
    const item = routineRow(row);
    if (item) items.push(item);
  }
  return items;
}

function routinesView(payload) {
  const items = routinesFromSchedules(payload);
  const body = payload && typeof payload === "object" ? payload : {};
  return {
    items,
    empty: items.length === 0,
    emptyLabel: body.empty_label || LABELS.emptyRoutines,
    addLabel: LABELS.addRoutine,
    addSoon: body.add_soon || LABELS.addRoutineSoon,
    canCreate: body.can_create === true,
    source: DATA_SOURCES.routines,
    plusOpens: addRoutinePlan(),
  };
}

module.exports = {
  SHELL,
  LABELS,
  DATA_SOURCES,
  HELPER_STUBS,
  LEADS,
  SESSION_GAP_MS,
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
  SETTINGS_API_PATH,
  ROUTINES_PATH,
  SCHEDULES_PATH,
  MAX_ASK_CHARS,
  MAX_REPLY_CHARS,
  talkQuery,
  shellQuery,
  pageHref,
  talkHref,
  shellHref,
  normalizePaneState,
  togglePane,
  isNarrowWidth,
  fitPanesToWidth,
  defaultPanesForWidth,
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
  appendTurn,
  mergeHistory,
  applyTalkEvent,
  composerSubmit,
  askRequest,
  historyRequest,
  talkLogRequest,
  speakRequest,
  parseAskReply,
  helpersFromInventory,
  groupChatsFromInventory,
  splitTalkSessions,
  chatsFromHistory,
  formatChatWhen,
  friendlyModel,
  normalizeNavSections,
  toggleNavSection,
  filterNavItems,
  leftNavView,
  selectLead,
  micPlan,
  chatView,
  settingsPlan,
  settingsRequest,
  persistTalkModeRequest,
  routinesRequest,
  addRoutinePlan,
  routineRow,
  routinesFromSchedules,
  routinesView,
};
