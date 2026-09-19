import assert from "node:assert/strict"
import { test } from "node:test"
import {
  ASK_PATH,
  LABELS,
  NOVNC_SESSION_URL,
  TALK_LAST_PATH,
  appendTurn,
  applyTalkEvent,
  chatsFromHistory,
  clipAsk,
  composerSubmit,
  helpersFromInventory,
  liveComputerView,
  normalizeTalkMode,
  parseAskReply,
  screenShouldShow,
} from "./jarvis.ts"

test("ask and history paths stay on Jarvis APIs", () => {
  assert.equal(ASK_PATH, "/api/jarvis/ask")
  assert.equal(TALK_LAST_PATH, "/api/jarvis/talk/last")
})

test("composer and ask reply", () => {
  assert.equal(clipAsk("  hi  "), "hi")
  assert.equal(composerSubmit("").ok, false)
  assert.equal(composerSubmit("hello").ok, true)
  assert.equal(parseAskReply({ reply: "Hello." }).ok, true)
  assert.equal(parseAskReply({}).emptyLabel, LABELS.cantTalk)
})

test("talk_mode hide never stops the computer", () => {
  assert.equal(normalizeTalkMode("terminal"), "terminal")
  assert.equal(normalizeTalkMode("nope"), "computer")
  assert.equal(screenShouldShow({ talkMode: "terminal" }), false)
  assert.equal(screenShouldShow({ talkMode: "computer", screenShown: false }), false)
  assert.equal(screenShouldShow({ talkMode: "computer" }), true)
  const live = liveComputerView({ talkMode: "computer", running: true })
  assert.equal(live.method, "iframe")
  assert.equal(live.embedSrc, NOVNC_SESSION_URL)
  assert.equal(live.stopComputer, false)
  assert.equal(live.killsComputerOnHide, false)
  const chatOnly = liveComputerView({
    talkMode: "terminal",
    running: true,
    screenShown: true,
  })
  assert.equal(chatOnly.visible, false)
  assert.equal(chatOnly.embedSrc, "")
  assert.equal(chatOnly.stopComputer, false)
})

test("helpers are honest: only Jarvis is live", () => {
  const helpers = helpersFromInventory()
  assert.equal(helpers[0].id, "jarvis")
  assert.equal(helpers[0].live, true)
  assert.ok(helpers.slice(1).every((row) => row.live === false))
  assert.ok(helpers.slice(1).every((row) => /not connected/i.test(row.subtitle)))
  assert.deepEqual(chatsFromHistory([]), [])
})

test("talk events append unique turns", () => {
  const turns = appendTurn([], { role: "you", text: "hi" })
  assert.equal(turns[0].role, "you")
  const talked = applyTalkEvent([], { status: "thinking", you: "open chrome" })
  assert.match(talked.subtitle, /thinking/i)
})
