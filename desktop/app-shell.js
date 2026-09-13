/**
 * Windows Jarvis 3-pane shell contract (epic #66, issues #74 / #67).
 *
 * Pure helpers — Node tests can require this file. The visible chrome is
 * app/static/desktop.html. Electron loads /desktop as the main window.
 * /ceo stays the Realtime / Settings page (hidden talk engine + Settings).
 */
const SHELL_PATH = "/desktop";
const TALK_PATH = "/ceo";
const SETTINGS_PATH = "/ceo";
const SCREEN_VIEWER_PATH = "/ceo/jarvis-screen";
const NOVNC_URL = "http://127.0.0.1:6080";
const NOVNC_SESSION_URL = `${NOVNC_URL}/vnc.html?autoconnect=1&resize=scale`;

const SHELL = {
  path: SHELL_PATH,
  defaultLaunch: "main",
  theme: "light",
  leftWidth: 280,
  rightWidth: 340,
  minMiddleWidth: 360,
  minWindowWidth: 800,
  // #68 will put the live PC in the right pane. iframe of the existing
  // :6080 viewer is the planned embed (BrowserView is harder to collapse).
  screenEmbed: "iframe",
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
  screenSoon: "The live computer will show here.",
  terminalScreen: "Chat only — the computer stays hidden.",
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

function applyTalkMode(value) {
  const talkMode = normalizeTalkMode(value);
  const terminal = talkMode === "terminal";
  return {
    talkMode,
    showComputerSlot: !terminal,
    screenLabel: terminal ? LABELS.terminalScreen : LABELS.screenSoon,
    modeLabel: terminal ? LABELS.terminal : LABELS.computer,
  };
}

function screenEmbedPlan() {
  return {
    method: SHELL.screenEmbed,
    novnc: NOVNC_URL,
    session: NOVNC_SESSION_URL,
    viewerPath: SCREEN_VIEWER_PATH,
    note: "Do not kill jarvis-computer when the right pane collapses.",
  };
}

module.exports = {
  SHELL,
  LABELS,
  SHELL_PATH,
  TALK_PATH,
  SETTINGS_PATH,
  SCREEN_VIEWER_PATH,
  NOVNC_URL,
  NOVNC_SESSION_URL,
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
  screenEmbedPlan,
};
