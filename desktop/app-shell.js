/**
 * Windows Jarvis 3-pane shell contract (epic #66, issues #74 / #67 / #68).
 *
 * Pure helpers — Node tests can require this file. The visible chrome is
 * app/static/desktop.html. Electron loads /desktop as the main window.
 * /ceo stays the Realtime / Settings page (hidden talk engine + Settings).
 *
 * #68 live PC: iframe of localhost noVNC inside #live-computer. BrowserView
 * is a native overlay and would need manual bounds on collapse; an iframe
 * hides with the pane. Hide / Chat only blanks the iframe and must not
 * stop jarvis-computer.
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
  screenShouldShow,
  liveComputerView,
  pauseLiveComputer,
  screenEmbedPlan,
};
