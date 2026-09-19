/**
 * Desktop UI helpers shared with Electron's app-shell contract.
 * Keep labels and talk_mode / hide-without-stop rules honest.
 */

export const ASK_PATH = "/api/jarvis/ask"
export const TALK_LAST_PATH = "/api/jarvis/talk/last"
export const TALK_LOG_PATH = "/api/jarvis/talk/log"
export const SPEAK_PATH = "/api/jarvis/speak"
export const SETTINGS_API_PATH = "/api/jarvis/settings"
export const ROUTINES_PATH = "/api/jarvis/routines"
export const COMPUTER_SCREEN_PATH = "/api/jarvis/computer/screen"
export const COMPUTER_START_PATH = "/api/jarvis/computer/screen/start"
export const NOVNC_URL = "http://127.0.0.1:6080"
export const NOVNC_SESSION_URL = `${NOVNC_URL}/vnc.html?autoconnect=1&resize=scale`
export const MAX_ASK_CHARS = 240
export const MAX_REPLY_CHARS = 2000
export const SESSION_GAP_MS = 45 * 60 * 1000
export const CHAT_TITLE_CHARS = 36
export const COLLAPSE_BELOW = 900

export const LABELS = {
  app: "Jarvis",
  teammate: "Your AI teammate",
  search: "Search assistants, chats…",
  helpers: "Helpers",
  assistants: "Assistants",
  chats: "Recent chats",
  groups: "Group chats",
  viewAll: "View all chats",
  composer: "Type a message…",
  ready: "Ready when you are",
  listening: "Listening…",
  thinking: "Jarvis is thinking…",
  emptyChat: "This chat is ready. Messages will show up here.",
  emptyOrbTitle: "Start a conversation",
  cantTalk: "Can't talk right now",
  addSoon: "Photos and files come later.",
  notConnected: "Not connected yet",
  emptyChats: "No chats yet. Send a message to start.",
  emptyGroups: "No group chats yet. They come later.",
  nothingMatches: "Nothing matches.",
  pluginsSoon: "Plugins come later.",
  profileSoon: "Your profile comes later.",
  emptyRoutines: "No routines yet.",
  addRoutineSoon: "Adding a routine comes later.",
  createRoutine: "Create routine",
  liveComputer: "Live Computer",
  computer: "Computer",
  terminal: "Chat only",
  hideScreen: "Hide screen",
  showScreen: "Show Jarvis's screen",
  startComputer: "Start Jarvis's computer",
  openScreen: "Open in new window",
  usingComputer: "Jarvis is using the computer…",
  connected: "Connected",
  screenLive: "Jarvis's screen is live.",
  screenHidden: "Jarvis's screen is hidden. The computer keeps running.",
  screenDown: "Jarvis's computer is not running.",
  terminalScreen: "Chat only — the computer stays hidden.",
  newChat: "New chat",
  you: "You",
  lead: "Jarvis",
} as const

export type TalkRole = "you" | "jarvis"

export type TalkTurn = {
  role: TalkRole
  text: string
  speaker: string
  ts: string
}

export type TalkMode = "computer" | "terminal"

export function clipTalkText(text: unknown, max = MAX_REPLY_CHARS): string {
  const s = String(text == null ? "" : text).replace(/\s+/g, " ").trim()
  if (!s) return ""
  if (s.length <= max) return s
  return s.slice(0, Math.max(0, max - 1)).trimEnd() + "…"
}

export function clipAsk(text: unknown): string {
  return clipTalkText(text, MAX_ASK_CHARS)
}

export function clipReply(text: unknown): string {
  return clipTalkText(text, MAX_REPLY_CHARS)
}

export function clipReplyKeepBreaks(text: unknown): string {
  return String(text == null ? "" : text)
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

export function normalizeRole(role: unknown): TalkRole | "" {
  const who = String(role || "").trim().toLowerCase()
  if (who === "you" || who === "user") return "you"
  if (who === "jarvis" || who === "assistant") return "jarvis"
  return ""
}

export function normalizeTalkMode(value: unknown): TalkMode {
  return String(value || "").trim().toLowerCase() === "terminal"
    ? "terminal"
    : "computer"
}

export function composerSubmit(text: unknown): { ok: boolean; text: string } {
  const asked = clipAsk(text)
  return { ok: !!asked, text: asked }
}

export function parseAskReply(payload: unknown): {
  reply: string
  ok: boolean
  emptyLabel: string
} {
  const body = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {}
  const ui = body.ui != null ? body.ui : body.result
  const uiObj = ui && typeof ui === "object" ? (ui as Record<string, unknown>) : null
  const reply = clipReplyKeepBreaks(body.reply || (uiObj && uiObj.summary) || "")
  return {
    reply,
    ok: !!reply,
    emptyLabel: reply ? "" : LABELS.cantTalk,
  }
}

export function makeTurn(turn: { role?: unknown; text?: unknown; ts?: unknown } | null): TalkTurn | null {
  const role = normalizeRole(turn && turn.role)
  const text =
    role === "you" ? clipAsk(turn && turn.text) : clipReplyKeepBreaks(turn && turn.text)
  if (!role || !text) return null
  return {
    role,
    text,
    speaker: role === "you" ? LABELS.you : LABELS.lead,
    ts: String((turn && turn.ts) || ""),
  }
}

function turnKey(turn: TalkTurn): string {
  return `${turn.role}\0${clipReply(turn.text)}`
}

export function appendTurn(turns: TalkTurn[], turn: { role?: unknown; text?: unknown; ts?: unknown }): TalkTurn[] {
  const next = Array.isArray(turns) ? turns.slice() : []
  const item = makeTurn(turn)
  if (!item) return next
  const last = next[next.length - 1]
  if (last && turnKey(last) === turnKey(item)) return next
  next.push(item)
  return next
}

export function speechTurns(rows: unknown): TalkTurn[] {
  const list = Array.isArray(rows) ? rows : []
  const out: TalkTurn[] = []
  for (const row of list) {
    const item = makeTurn(row as { role?: unknown; text?: unknown; ts?: unknown })
    if (item) out.push(item)
  }
  return out
}

export function mergeHistory(turns: TalkTurn[], rows: unknown): TalkTurn[] {
  const incoming = speechTurns(rows)
  if (!incoming.length) return Array.isArray(turns) ? turns.slice() : []
  const prev = Array.isArray(turns) ? turns : []
  if (!prev.length || incoming.length >= prev.length) return incoming
  return prev.slice()
}

export function applyTalkEvent(
  turns: TalkTurn[],
  event: { status?: unknown; you?: unknown; reply?: unknown }
): { turns: TalkTurn[]; status: string; subtitle: string } {
  const you = clipAsk(event && event.you)
  const reply = clipReplyKeepBreaks(event && event.reply)
  let next = Array.isArray(turns) ? turns.slice() : []
  if (you) next = appendTurn(next, { role: "you", text: you })
  if (reply) next = appendTurn(next, { role: "jarvis", text: reply })
  const status = String(
    event.status || (reply ? "idle" : you ? "thinking" : "") || "idle"
  )
  let subtitle: string = LABELS.ready
  if (status === "listening") subtitle = LABELS.listening
  else if (status === "thinking" || (you && !reply)) subtitle = LABELS.thinking
  else if (status === "unavailable" || status === "error") subtitle = LABELS.cantTalk
  return { turns: next, status, subtitle }
}

export function helpersFromInventory() {
  return [
    {
      id: "jarvis",
      name: LABELS.lead,
      initial: "J",
      color: "#2563EB",
      subtitle: LABELS.ready,
      source: "local-lead",
      live: true,
      ready: true,
    },
    {
      id: "writer",
      name: "Writer",
      initial: "W",
      color: "#0f766e",
      subtitle: LABELS.notConnected,
      source: "documented-stub",
      live: false,
      ready: false,
    },
    {
      id: "helper",
      name: "Helper",
      initial: "H",
      color: "#b45309",
      subtitle: LABELS.notConnected,
      source: "documented-stub",
      live: false,
      ready: false,
    },
    {
      id: "finder",
      name: "Finder",
      initial: "F",
      color: "#7c3aed",
      subtitle: LABELS.notConnected,
      source: "documented-stub",
      live: false,
      ready: false,
    },
  ].map((row) => ({
    ...row,
    talkTarget: "jarvis" as const,
  }))
}

export function parseTurnTime(ts: unknown): number {
  const n = Date.parse(String(ts || ""))
  return Number.isFinite(n) ? n : 0
}

export function formatChatWhen(ts: unknown, now?: Date): string {
  const n = parseTurnTime(ts)
  if (!n) return ""
  const d = new Date(n)
  const ref = now instanceof Date ? now : new Date()
  const startToday = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate()).getTime()
  const startYest = startToday - 86400000
  if (n >= startToday) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  }
  if (n >= startYest) return "Yesterday"
  return d.toLocaleDateString([], { month: "numeric", day: "numeric", year: "numeric" })
}

export function chatsFromHistory(turns: TalkTurn[]) {
  const speech = Array.isArray(turns) ? turns.filter((row) => row && (row.role === "you" || row.role === "jarvis") && row.text) : []
  const groups: TalkTurn[][] = []
  let current: TalkTurn[] = []
  let prevTs = 0
  for (const row of speech) {
    const ts = parseTurnTime(row.ts)
    if (current.length && prevTs && ts && ts - prevTs > SESSION_GAP_MS) {
      groups.push(current)
      current = []
    }
    current.push(row)
    if (ts) prevTs = ts
  }
  if (current.length) groups.push(current)
  return groups
    .slice()
    .reverse()
    .map((session, index) => {
      const last = session[session.length - 1]
      const first = session[0] || { ts: "" }
      const firstYou = session.find((row) => row.role === "you")
      const live = index === 0
      let title: string = LABELS.lead
      if (!live && firstYou && firstYou.text) {
        title =
          firstYou.text.length > CHAT_TITLE_CHARS
            ? `${firstYou.text.slice(0, CHAT_TITLE_CHARS - 1).trimEnd()}…`
            : firstYou.text
      }
      const sid = String(first.ts || index).replace(/[^a-z0-9]/gi, "").toLowerCase()
      return {
        id: live ? "talk-live" : `talk-${sid || index}`,
        name: title,
        preview: last ? last.text : "",
        when: formatChatWhen(last && last.ts),
        source: "talk-history",
        live,
        ready: true,
        talkTarget: "jarvis" as const,
      }
    })
}

export function filterNavItems<T extends { name?: string; preview?: string; subtitle?: string }>(
  items: T[],
  query: string
): T[] {
  const q = String(query || "").replace(/\s+/g, " ").trim().toLowerCase()
  if (!q) return items.slice()
  return items.filter((row) => {
    const hay = [row.name, row.preview, row.subtitle]
      .map((value) => String(value || "").toLowerCase())
      .join(" ")
    return hay.includes(q)
  })
}

export function screenShouldShow(state: {
  talkMode?: unknown
  paneOpen?: boolean
  screenShown?: boolean
}): boolean {
  if (normalizeTalkMode(state.talkMode) === "terminal") return false
  if (state.paneOpen === false) return false
  if (state.screenShown === false) return false
  return true
}

export function liveComputerView(state: {
  talkMode?: unknown
  paneOpen?: boolean
  screenShown?: boolean
  running?: boolean
}) {
  const talkMode = normalizeTalkMode(state.talkMode)
  const paneOpen = state.paneOpen !== false
  const screenShown = talkMode === "terminal" ? false : state.screenShown !== false
  const running = state.running === true
  const show = screenShouldShow({ talkMode, paneOpen, screenShown })
  return {
    method: "iframe" as const,
    talkMode,
    visible: show,
    embedSrc: show && running ? NOVNC_SESSION_URL : "",
    startAllowed: show && !running,
    stopComputer: false,
    killsComputerOnHide: false,
  }
}

export function friendlyModel(data: { helper_name?: unknown; model?: unknown } | null): string {
  const src = data && typeof data === "object" ? data : {}
  const name = String(src.helper_name || "").trim()
  if (name) return name
  const model = String(src.model || "").trim()
  if (!model) return LABELS.lead
  const parts = model.split("/")
  return parts[parts.length - 1] || LABELS.lead
}

export function defaultPanesForWidth(width: number): { left: boolean; right: boolean } {
  if (width > 0 && width < COLLAPSE_BELOW) return { left: false, right: false }
  return { left: true, right: true }
}

export function routinesFromPayload(payload: unknown): { id: string; name: string; when: string }[] {
  const body = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {}
  const raw = Array.isArray(body.routines)
    ? body.routines
    : Array.isArray(body.schedules)
      ? body.schedules
      : []
  const items: { id: string; name: string; when: string }[] = []
  for (const row of raw) {
    if (!row || typeof row !== "object") continue
    const rec = row as Record<string, unknown>
    const id = String(rec.id || "").trim()
    const name = String(rec.name || "").trim()
    if (!id || !name) continue
    const when =
      String(rec.when || rec.schedule_human || rec.subtitle || "").trim() ||
      (rec.enabled === false ? "Off" : "On the schedule")
    items.push({ id, name, when })
  }
  return items
}
