import {
  ASK_PATH,
  COMPUTER_SCREEN_PATH,
  COMPUTER_START_PATH,
  ROUTINES_PATH,
  SETTINGS_API_PATH,
  SPEAK_PATH,
  TALK_LAST_PATH,
  TALK_LOG_PATH,
} from "./jarvis"

export function apiUrl(path: string): string {
  const extra =
    typeof window !== "undefined" && typeof window.jarvisApiBase === "string"
      ? window.jarvisApiBase
      : ""
  const base = (extra || process.env.NEXT_PUBLIC_JARVIS_API_BASE || "").replace(/\/$/, "")
  return `${base}${path}`
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return {}
  }
}

export async function fetchAsk(text: string): Promise<unknown> {
  const res = await fetch(apiUrl(ASK_PATH), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
  return readJson(res)
}

export async function fetchTalkLast(): Promise<{ turns?: unknown[] }> {
  const res = await fetch(apiUrl(TALK_LAST_PATH), { credentials: "include" })
  if (!res.ok) return {}
  return (await readJson(res)) as { turns?: unknown[] }
}

export function postTalkLog(role: string, text: string): void {
  fetch(apiUrl(TALK_LOG_PATH), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, text }),
  }).catch(() => {})
}

export async function fetchSettings(): Promise<Record<string, unknown>> {
  const res = await fetch(apiUrl(SETTINGS_API_PATH), { credentials: "include" })
  if (!res.ok) return {}
  return (await readJson(res)) as Record<string, unknown>
}

export function persistTalkMode(talkMode: string): void {
  fetch(apiUrl(SETTINGS_API_PATH), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ talk_mode: talkMode }),
  }).catch(() => {})
}

export async function fetchRoutines(): Promise<unknown> {
  const res = await fetch(apiUrl(ROUTINES_PATH), { credentials: "include" })
  if (!res.ok) return {}
  return readJson(res)
}

export async function fetchComputerScreen(): Promise<{ running?: boolean; error?: string }> {
  const res = await fetch(apiUrl(COMPUTER_SCREEN_PATH), { credentials: "include" })
  return (await readJson(res)) as { running?: boolean; error?: string }
}

export async function startComputer(): Promise<{ running?: boolean; error?: string }> {
  const res = await fetch(apiUrl(COMPUTER_START_PATH), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  })
  return (await readJson(res)) as { running?: boolean; error?: string }
}

export async function playSpeak(text: string): Promise<void> {
  const clean = String(text || "").replace(/\s+/g, " ").trim()
  if (!clean) return
  const res = await fetch(apiUrl(SPEAK_PATH), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: clean }),
  })
  if (!res.ok) return
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.play().catch(() => {})
}
