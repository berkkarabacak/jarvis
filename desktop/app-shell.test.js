/**
 * Node assertions for desktop/app-shell.js (issues #74 / #67 / #68 / #69).
 * Run: node desktop/app-shell.test.js
 */
const assert = require("assert");
const {
  SHELL,
  LABELS,
  SHELL_PATH,
  TALK_PATH,
  SCREEN_VIEWER_PATH,
  NOVNC_URL,
  NOVNC_SESSION_URL,
  ASK_PATH,
  TALK_LAST_PATH,
  TALK_LOG_PATH,
  talkQuery,
  shellQuery,
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
  clipAsk,
  speechTurns,
  mergeHistory,
  applyTalkEvent,
  composerSubmit,
  askRequest,
  historyRequest,
  talkLogRequest,
  parseAskReply,
  selectLead,
  micPlan,
  chatView,
} = require("./app-shell");

assert.strictEqual(SHELL.path, "/desktop");
assert.strictEqual(SHELL.defaultLaunch, "main");
assert.strictEqual(SHELL.theme, "light");
assert.strictEqual(SHELL.screenEmbed, "iframe");
assert.strictEqual(SHELL.screenEmbedRejected, "BrowserView");
assert.ok(SHELL.leftWidth >= 240);
assert.ok(SHELL.rightWidth >= 280);
assert.ok(SHELL.minMiddleWidth >= 280);
assert.strictEqual(SHELL_PATH, "/desktop");
assert.strictEqual(TALK_PATH, "/ceo");
assert.strictEqual(SCREEN_VIEWER_PATH, "/ceo/jarvis-screen");
assert.strictEqual(NOVNC_URL, "http://127.0.0.1:6080");
assert.ok(NOVNC_SESSION_URL.includes("autoconnect=1"));

assert.strictEqual(LABELS.agents, "Helpers");
assert.strictEqual(LABELS.chats, "Chats");
assert.strictEqual(LABELS.groups, "Group chats");
assert.strictEqual(LABELS.screen, "Jarvis's screen");
assert.strictEqual(LABELS.routines, "Routines");
assert.strictEqual(LABELS.terminal, "Chat only");
assert.strictEqual(LABELS.hideScreen, "Hide screen");
assert.strictEqual(LABELS.showScreen, "Show Jarvis's screen");
assert.strictEqual(LABELS.startComputer, "Start Jarvis's computer");
assert.ok(/keeps running/i.test(LABELS.screenHidden));
assert.strictEqual(LABELS.you, "You");
assert.strictEqual(LABELS.lead, "Jarvis");
assert.strictEqual(LABELS.ready, "Ready when you are");
assert.strictEqual(LABELS.listening, "Listening…");
assert.strictEqual(LABELS.thinking, "Jarvis is thinking…");
assert.strictEqual(LABELS.addSoon, "Photos and files come later.");
assert.strictEqual(LABELS.cantTalk, "Can't talk right now");
assert.ok(!/composer|transcript|nav|sidebar/i.test(Object.values(LABELS).join(" ")));
assert.strictEqual(ASK_PATH, "/api/jarvis/ask");
assert.strictEqual(TALK_LAST_PATH, "/api/jarvis/talk/last");
assert.strictEqual(TALK_LOG_PATH, "/api/jarvis/talk/log");

const talk = talkQuery();
assert.strictEqual(talk.get("desktop"), "1");
assert.strictEqual(talk.get("autolisten"), "1");
assert.strictEqual(talkQuery({ settings: true }).get("settings"), "1");
assert.strictEqual(shellQuery().get("desktop"), "1");
assert.ok(talkHref(8787).startsWith("http://127.0.0.1:8787/ceo?"));
assert.ok(shellHref(8787).startsWith("http://127.0.0.1:8787/desktop?"));
assert.ok(talkHref(8787).includes("desktop=1"));
assert.ok(!shellHref(8787).includes("autolisten=1"));

assert.deepStrictEqual(normalizePaneState(null), { left: true, right: true });
assert.deepStrictEqual(normalizePaneState({ left: false }), { left: false, right: true });
assert.deepStrictEqual(togglePane({ left: true, right: true }, "left"), {
  left: false,
  right: true,
});
assert.deepStrictEqual(togglePane({ left: false, right: true }, "right"), {
  left: false,
  right: false,
});

const both = layoutColumns({ left: true, right: true });
assert.strictEqual(both.left, SHELL.leftWidth);
assert.strictEqual(both.right, SHELL.rightWidth);
assert.strictEqual(both.middle, "flex");
assert.strictEqual(both.leftOpen, true);
assert.strictEqual(layoutColumns({ left: false, right: false }).left, 0);
assert.strictEqual(layoutColumns({ left: false, right: false }).right, 0);
assert.strictEqual(layoutColumns({ left: false, right: false }).minMiddle, SHELL.minMiddleWidth);

assert.deepStrictEqual(fitPanesToWidth(1400, { left: true, right: true }), {
  left: true,
  right: true,
});
assert.deepStrictEqual(fitPanesToWidth(800, { left: true, right: true }), {
  left: false,
  right: false,
});

assert.strictEqual(normalizeTalkMode("terminal"), "terminal");
assert.strictEqual(normalizeTalkMode("nope"), "computer");
const term = applyTalkMode("terminal");
assert.strictEqual(term.talkMode, "terminal");
assert.strictEqual(term.showComputerSlot, false);
assert.strictEqual(term.screenShown, false);
assert.strictEqual(term.embedSrc, "");
assert.strictEqual(term.pauseEmbed, true);
assert.strictEqual(term.stopComputer, false);
assert.ok(/chat only/i.test(term.screenLabel));
const pc = applyTalkMode("computer");
assert.strictEqual(pc.showComputerSlot, true);
assert.strictEqual(pc.modeLabel, "Computer");
assert.strictEqual(pc.embedSrc, NOVNC_SESSION_URL);
assert.strictEqual(pc.stopComputer, false);
const hiddenPc = applyTalkMode("computer", { screenShown: false, paneOpen: true });
assert.strictEqual(hiddenPc.showComputerSlot, false);
assert.strictEqual(hiddenPc.pauseEmbed, true);
assert.strictEqual(hiddenPc.stopComputer, false);
assert.ok(/keeps running/i.test(hiddenPc.screenLabel));
const collapsed = applyTalkMode("computer", { paneOpen: false });
assert.strictEqual(collapsed.showComputerSlot, false);
assert.strictEqual(collapsed.stopComputer, false);

assert.strictEqual(screenShouldShow({ talkMode: "terminal" }), false);
assert.strictEqual(screenShouldShow({ talkMode: "computer", paneOpen: false }), false);
assert.strictEqual(screenShouldShow({ talkMode: "computer", screenShown: false }), false);
assert.strictEqual(screenShouldShow({ talkMode: "computer" }), true);

const live = liveComputerView({ talkMode: "computer", running: true });
assert.strictEqual(live.method, "iframe");
assert.strictEqual(live.visible, true);
assert.strictEqual(live.driving, true);
assert.strictEqual(live.embedSrc, NOVNC_SESSION_URL);
assert.strictEqual(live.killsComputerOnHide, false);
const chatOnly = liveComputerView({ talkMode: "terminal", running: true, screenShown: true });
assert.strictEqual(chatOnly.visible, false);
assert.strictEqual(chatOnly.driving, false);
assert.strictEqual(chatOnly.paused, true);
assert.strictEqual(chatOnly.embedSrc, "");
assert.strictEqual(chatOnly.startAllowed, false);
assert.strictEqual(chatOnly.stopComputer, false);
const pausedPane = liveComputerView({ talkMode: "computer", paneOpen: false, running: true });
assert.strictEqual(pausedPane.paused, true);
assert.strictEqual(pausedPane.embedSrc, "");
assert.strictEqual(pausedPane.stopComputer, false);
const down = liveComputerView({ talkMode: "computer", running: false });
assert.strictEqual(down.visible, true);
assert.strictEqual(down.embedSrc, "");
assert.strictEqual(down.startAllowed, true);

const paused = pauseLiveComputer();
assert.strictEqual(paused.method, "iframe");
assert.strictEqual(paused.embedSrc, "");
assert.strictEqual(paused.paused, true);
assert.strictEqual(paused.stopComputer, false);
assert.deepStrictEqual(paused.stopUrls, []);
assert.ok(/do not stop/i.test(paused.note));

const embed = screenEmbedPlan();
assert.strictEqual(embed.method, "iframe");
assert.strictEqual(embed.rejected, "BrowserView");
assert.strictEqual(embed.novnc, NOVNC_URL);
assert.strictEqual(embed.session, NOVNC_SESSION_URL);
assert.strictEqual(embed.viewerPath, SCREEN_VIEWER_PATH);
assert.ok(/collapse/i.test(embed.note));
assert.ok(/iframe/i.test(embed.note));

assert.strictEqual(clipAsk("  hello there  "), "hello there");
assert.strictEqual(composerSubmit("").ok, false);
assert.strictEqual(composerSubmit("  hi  ").ok, true);
assert.strictEqual(composerSubmit("  hi  ").text, "hi");
const asked = askRequest("what's on your screen");
assert.strictEqual(asked.ok, true);
assert.strictEqual(asked.url, "/api/jarvis/ask");
assert.strictEqual(asked.method, "POST");
assert.strictEqual(asked.body.text, "what's on your screen");
assert.strictEqual(historyRequest().url, "/api/jarvis/talk/last");
const logged = talkLogRequest("you", "hello");
assert.strictEqual(logged.ok, true);
assert.strictEqual(logged.url, "/api/jarvis/talk/log");
assert.strictEqual(logged.body.role, "you");

const speech = speechTurns([
  { role: "you", text: "hi" },
  { role: "tool", text: "opened" },
  { role: "jarvis", text: "Hello." },
  { role: "jarvis", text: "   " },
]);
assert.deepStrictEqual(speech.map((row) => row.role), ["you", "jarvis"]);
assert.strictEqual(speech[1].speaker, "Jarvis");

let thread = mergeHistory([], [
  { role: "you", text: "hi" },
  { role: "jarvis", text: "Hello." },
]);
assert.strictEqual(thread.length, 2);
thread = mergeHistory(thread, [{ role: "you", text: "hi" }, { role: "jarvis", text: "Hello." }]);
assert.strictEqual(thread.length, 2);

const liveTalk = applyTalkEvent([], { status: "thinking", you: "open chrome" });
assert.strictEqual(liveTalk.turns[0].role, "you");
assert.strictEqual(liveTalk.turns[0].text, "open chrome");
assert.ok(/thinking/i.test(liveTalk.subtitle));
const replied = applyTalkEvent(liveTalk.turns, { status: "idle", reply: "Opening Chrome." });
assert.strictEqual(replied.turns.length, 2);
assert.strictEqual(replied.turns[1].role, "jarvis");
assert.strictEqual(replied.subtitle, LABELS.ready);
const listen = applyTalkEvent([], { status: "listening" });
assert.strictEqual(listen.subtitle, LABELS.listening);

const parsed = parseAskReply({ reply: "Hello." });
assert.strictEqual(parsed.ok, true);
assert.strictEqual(parsed.reply, "Hello.");
assert.strictEqual(parseAskReply({}).emptyLabel, LABELS.cantTalk);

const jarvis = selectLead("jarvis");
assert.strictEqual(jarvis.name, "Jarvis");
assert.strictEqual(jarvis.talkTarget, "jarvis");
assert.strictEqual(jarvis.ready, true);
const writer = selectLead("writer");
assert.strictEqual(writer.name, "Writer");
assert.strictEqual(writer.ready, false);
assert.strictEqual(writer.talkTarget, "jarvis");
assert.ok(/coming soon/i.test(writer.subtitle));

const micEngine = micPlan(true);
assert.strictEqual(micEngine.startListen, true);
assert.strictEqual(micEngine.via, "talk-engine");
assert.strictEqual(micEngine.fallbackAsk, true);
assert.strictEqual(micPlan(false).via, "browser");

const empty = chatView([]);
assert.strictEqual(empty.empty, true);
assert.strictEqual(empty.emptyLabel, LABELS.emptyChat);
const filled = chatView(thread);
assert.strictEqual(filled.empty, false);
assert.strictEqual(filled.turns.length, 2);

console.log("app-shell helpers ok");
