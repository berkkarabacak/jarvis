/**
 * Node assertions for desktop/app-shell.js (issues #74 / #67 / #68 / #69 / #70 / #71 / #72 / #73).
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
  appendTurn,
  mergeHistory,
  applyTalkEvent,
  composerSubmit,
  askRequest,
  historyRequest,
  talkLogRequest,
  parseAskReply,
  selectLead,
  helpersFromInventory,
  groupChatsFromInventory,
  chatsFromHistory,
  normalizeNavSections,
  toggleNavSection,
  filterNavItems,
  leftNavView,
  DATA_SOURCES,
  micPlan,
  chatView,
  isNarrowWidth,
  defaultPanesForWidth,
  settingsPlan,
  settingsRequest,
  persistTalkModeRequest,
  routinesRequest,
  addRoutinePlan,
  routinesFromSchedules,
  routinesView,
  ROUTINES_PATH,
  SETTINGS_API_PATH,
} = require("./app-shell");

assert.strictEqual(SHELL.path, "/desktop");
assert.strictEqual(SHELL.defaultLaunch, "main");
assert.strictEqual(SHELL.theme, "light");
assert.strictEqual(SHELL.screenEmbed, "iframe");
assert.strictEqual(SHELL.screenEmbedRejected, "BrowserView");
assert.ok(SHELL.leftWidth >= 240);
assert.ok(SHELL.rightWidth >= 280);
assert.ok(SHELL.minMiddleWidth >= 280);
assert.strictEqual(SHELL.collapseBelow, 900);
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
assert.strictEqual(LABELS.newChat, "New chat");
assert.strictEqual(LABELS.notConnected, "Not connected yet");
assert.strictEqual(LABELS.emptyChats, "No chats yet. Send a message to start.");
assert.strictEqual(LABELS.emptyGroups, "No group chats yet. They come later.");
assert.strictEqual(LABELS.nothingMatches, "Nothing matches.");
assert.strictEqual(DATA_SOURCES.helpers, "local-lead + documented-stub");
assert.strictEqual(DATA_SOURCES.chats, "talk-history");
assert.strictEqual(DATA_SOURCES.groups, "none");
assert.strictEqual(DATA_SOURCES.routines, "local-schedules");
assert.ok(/only jarvis is a live helper/i.test(DATA_SOURCES.note));
assert.ok(/real local schedules/i.test(DATA_SOURCES.note));
assert.strictEqual(LABELS.emptyRoutines, "No routines yet.");
assert.strictEqual(LABELS.addRoutine, "Add routine");
assert.strictEqual(LABELS.addRoutineSoon, "Adding a routine comes later.");
assert.ok(/middle/i.test(LABELS.hidePanesHint));
assert.ok(/right/i.test(LABELS.hidePanesHint));
assert.ok(/hide chats/i.test(LABELS.hidePanesHint));
assert.strictEqual(ROUTINES_PATH, "/api/jarvis/routines");
assert.strictEqual(SETTINGS_API_PATH, "/api/jarvis/settings");
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
assert.strictEqual(isNarrowWidth(899), true);
assert.strictEqual(isNarrowWidth(900), false);
assert.strictEqual(isNarrowWidth(1400), false);
assert.deepStrictEqual(defaultPanesForWidth(800), { left: false, right: false });
assert.deepStrictEqual(defaultPanesForWidth(1200), { left: true, right: true });
assert.deepStrictEqual(fitPanesToWidth(899, { left: true, right: true }), {
  left: false,
  right: false,
});
assert.deepStrictEqual(fitPanesToWidth(900, { left: true, right: true }), {
  left: true,
  right: true,
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
const twice = appendTurn(appendTurn(thread, { role: "you", text: "hi" }), { role: "you", text: "hi" });
assert.strictEqual(twice.length, 3);
assert.strictEqual(twice[2].text, "hi");

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
assert.strictEqual(jarvis.source, "local-lead");
assert.strictEqual(jarvis.live, true);
const writer = selectLead("writer");
assert.strictEqual(writer.name, "Writer");
assert.strictEqual(writer.ready, false);
assert.strictEqual(writer.talkTarget, "jarvis");
assert.strictEqual(writer.source, "documented-stub");
assert.strictEqual(writer.live, false);
assert.ok(/not connected/i.test(writer.subtitle));
assert.strictEqual(selectLead("buyra").id, "jarvis");
assert.strictEqual(selectLead("family").live, true);

const helpers = helpersFromInventory();
assert.strictEqual(helpers[0].id, "jarvis");
assert.strictEqual(helpers[0].live, true);
assert.ok(helpers.slice(1).every((row) => row.source === "documented-stub" && row.live === false));
assert.deepStrictEqual(groupChatsFromInventory(), []);

assert.deepStrictEqual(chatsFromHistory([]), []);
assert.deepStrictEqual(chatsFromHistory([{ role: "tool", text: "opened" }]), []);
const oneChat = chatsFromHistory([
  { role: "you", text: "hey jarvis", ts: "2026-09-13T10:00:00Z" },
  { role: "jarvis", text: "Hello.", ts: "2026-09-13T10:00:02Z" },
]);
assert.strictEqual(oneChat.length, 1);
assert.strictEqual(oneChat[0].id, "talk-live");
assert.strictEqual(oneChat[0].name, "Jarvis");
assert.strictEqual(oneChat[0].preview, "Hello.");
assert.strictEqual(oneChat[0].source, "talk-history");
assert.strictEqual(oneChat[0].talkTarget, "jarvis");
const twoChats = chatsFromHistory([
  { role: "you", text: "old hello", ts: "2026-09-12T10:00:00Z" },
  { role: "jarvis", text: "Hi.", ts: "2026-09-12T10:00:02Z" },
  { role: "you", text: "new hello", ts: "2026-09-13T12:00:00Z" },
  { role: "jarvis", text: "Hello again.", ts: "2026-09-13T12:00:03Z" },
]);
assert.strictEqual(twoChats.length, 2);
assert.strictEqual(twoChats[0].id, "talk-live");
assert.strictEqual(twoChats[0].preview, "Hello again.");
assert.strictEqual(twoChats[1].name, "old hello");
assert.strictEqual(twoChats[1].source, "talk-history");
const pickedChat = selectLead("talk-live", { chats: twoChats });
assert.strictEqual(pickedChat.name, "Jarvis");
assert.strictEqual(pickedChat.talkTarget, "jarvis");
assert.strictEqual(pickedChat.ready, true);

assert.deepStrictEqual(normalizeNavSections(null), { helpers: true, chats: true, groups: true });
assert.deepStrictEqual(toggleNavSection({ helpers: true, chats: true, groups: true }, "chats"), {
  helpers: true,
  chats: false,
  groups: true,
});
assert.deepStrictEqual(toggleNavSection({ helpers: true, chats: false, groups: true }, "helpers"), {
  helpers: false,
  chats: false,
  groups: true,
});
assert.strictEqual(toggleNavSection({ helpers: true, chats: true, groups: true }, "chats").groups, true);

const filtered = filterNavItems(helpers, "writ");
assert.strictEqual(filtered.length, 1);
assert.strictEqual(filtered[0].id, "writer");
assert.deepStrictEqual(filterNavItems(helpers, "zzzz"), []);

const emptyNav = leftNavView({});
assert.strictEqual(emptyNav.emptyChats, true);
assert.strictEqual(emptyNav.emptyGroups, true);
assert.strictEqual(emptyNav.emptyChatsLabel, LABELS.emptyChats);
assert.strictEqual(emptyNav.emptyGroupsLabel, LABELS.emptyGroups);
assert.strictEqual(emptyNav.helpers[0].id, "jarvis");
assert.strictEqual(emptyNav.plusLabel, "New chat");
assert.ok(emptyNav.helpers.some((row) => row.live === true));
assert.ok(emptyNav.helpers.filter((row) => row.live).length === 1);
const filledNav = leftNavView({ turns: [
  { role: "you", text: "hey jarvis", ts: "2026-09-13T10:00:00Z" },
  { role: "jarvis", text: "Hello.", ts: "2026-09-13T10:00:02Z" },
]});
assert.strictEqual(filledNav.emptyChats, false);
assert.strictEqual(filledNav.chats[0].source, "talk-history");
const searchNav = leftNavView({ query: "zzzz", turns: [
  { role: "you", text: "hey", ts: "2026-09-13T10:00:00Z" },
]});
assert.strictEqual(searchNav.emptyChats, true);
assert.strictEqual(searchNav.emptyChatsLabel, LABELS.nothingMatches);
assert.ok(!filledNav.helpers.some((row) => /buyra|family|home/i.test(row.name)));
assert.ok(!filledNav.chats.some((row) => row.live === false && /connected/i.test(row.preview || "")));

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

const settings = settingsPlan();
assert.strictEqual(settings.fromChrome, true);
assert.strictEqual(settings.via, "gear");
assert.strictEqual(settings.path, "/ceo");
assert.strictEqual(settings.query.settings, "1");
assert.strictEqual(settings.query.desktop, "1");
assert.ok(settings.href.includes("settings=1"));
assert.ok(settings.href.includes("desktop=1"));
assert.strictEqual(settings.persist, "/api/jarvis/settings");
assert.ok(settings.fields.includes("talk_mode"));
assert.ok(settings.fields.includes("model"));
assert.ok(settings.fields.includes("realtime_voice"));
assert.ok(settings.fields.includes("computer_kind"));
assert.strictEqual(settings.talkMode, true);
assert.strictEqual(settingsRequest().url, "/api/jarvis/settings");
assert.strictEqual(settingsRequest().method, "GET");
const savedMode = persistTalkModeRequest("terminal");
assert.strictEqual(savedMode.method, "PUT");
assert.deepStrictEqual(savedMode.body, { talk_mode: "terminal" });
assert.strictEqual(persistTalkModeRequest("nope").body.talk_mode, "computer");

assert.strictEqual(routinesRequest().url, "/api/jarvis/routines");
assert.strictEqual(addRoutinePlan().ok, false);
assert.strictEqual(addRoutinePlan().canCreate, false);
assert.ok(/comes later/i.test(addRoutinePlan().label));
assert.deepStrictEqual(routinesFromSchedules({}), []);
assert.deepStrictEqual(routinesFromSchedules({ routines: [] }), []);
assert.deepStrictEqual(routinesFromSchedules({
  routines: [{ id: "", name: "Ghost" }, { name: "No id" }],
}), []);
const scheduled = routinesFromSchedules({
  routines: [
    { id: "job-1", name: "Inbox sort", when: "Every day at 07:00", enabled: true },
  ],
});
assert.strictEqual(scheduled.length, 1);
assert.strictEqual(scheduled[0].name, "Inbox sort");
assert.strictEqual(scheduled[0].when, "Every day at 07:00");
assert.strictEqual(scheduled[0].source, "local-schedules");
const fromControlRoom = routinesFromSchedules({
  schedules: [{ id: "job-2", name: "Weekly wrap", schedule_human: "Every Monday at 09:00" }],
});
assert.strictEqual(fromControlRoom[0].when, "Every Monday at 09:00");
const none = routinesView({});
assert.strictEqual(none.empty, true);
assert.strictEqual(none.emptyLabel, LABELS.emptyRoutines);
assert.strictEqual(none.canCreate, false);
assert.strictEqual(none.plusOpens.canCreate, false);
assert.ok(!none.items.some((row) => /morning briefing|evening wrap/i.test(row.name)));
const some = routinesView({ routines: scheduled });
assert.strictEqual(some.empty, false);
assert.strictEqual(some.items[0].name, "Inbox sort");

console.log("app-shell helpers ok");
