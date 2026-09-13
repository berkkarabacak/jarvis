/**
 * Node assertions for desktop/app-shell.js (issues #74 / #67).
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
  screenEmbedPlan,
} = require("./app-shell");

assert.strictEqual(SHELL.path, "/desktop");
assert.strictEqual(SHELL.defaultLaunch, "main");
assert.strictEqual(SHELL.theme, "light");
assert.strictEqual(SHELL.screenEmbed, "iframe");
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
assert.ok(!/composer|transcript|nav|sidebar/i.test(Object.values(LABELS).join(" ")));

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
assert.ok(/chat only/i.test(term.screenLabel));
const pc = applyTalkMode("computer");
assert.strictEqual(pc.showComputerSlot, true);
assert.strictEqual(pc.modeLabel, "Computer");

const embed = screenEmbedPlan();
assert.strictEqual(embed.method, "iframe");
assert.strictEqual(embed.novnc, NOVNC_URL);
assert.strictEqual(embed.viewerPath, SCREEN_VIEWER_PATH);
assert.ok(/collapse/i.test(embed.note));

console.log("app-shell helpers ok");
