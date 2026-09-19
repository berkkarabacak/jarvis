"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { LeftPane } from "./LeftPane"
import { MiddlePane } from "./MiddlePane"
import { RightPane } from "./RightPane"
import {
  COLLAPSE_BELOW,
  LABELS,
  appendTurn,
  applyTalkEvent,
  chatsFromHistory,
  composerSubmit,
  defaultPanesForWidth,
  filterNavItems,
  friendlyModel,
  helpersFromInventory,
  liveComputerView,
  mergeHistory,
  normalizeTalkMode,
  parseAskReply,
  routinesFromPayload,
  type TalkMode,
  type TalkTurn,
} from "@/lib/jarvis"
import {
  fetchAsk,
  fetchComputerScreen,
  fetchRoutines,
  fetchSettings,
  fetchTalkLast,
  persistTalkMode,
  playSpeak,
  postTalkLog,
  startComputer,
} from "@/lib/api"
import { desktopBridge } from "@/lib/bridge"

const PANE_STORAGE = "jarvis.shell.panes"
const NAV_STORAGE = "jarvis.shell.nav"
const SCREEN_STORAGE = "jarvis.shell.pcVisible"

function readJson<T>(raw: string | null, fallback: T): T {
  try {
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function Shell() {
  const [turns, setTurns] = useState<TalkTurn[]>([])
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [listening, setListening] = useState(false)
  const [subtitle, setSubtitle] = useState<string>(LABELS.ready)
  const [query, setQuery] = useState("")
  const [selectedId, setSelectedId] = useState("jarvis")
  const [sections, setSections] = useState({ helpers: true, chats: true, groups: false })
  const [panes, setPanes] = useState({ left: true, right: true })
  const [talkMode, setTalkMode] = useState<TalkMode>("computer")
  const [screenShown, setScreenShown] = useState(true)
  const [computerRunning, setComputerRunning] = useState(false)
  const [starting, setStarting] = useState(false)
  const [screenCopy, setScreenCopy] = useState("Checking Jarvis's screen…")
  const [modelLabel, setModelLabel] = useState<string>(LABELS.lead)
  const [routines, setRoutines] = useState<{ id: string; name: string; when: string }[]>([])
  const [routineNote, setRoutineNote] = useState("")
  const [menuOpen, setMenuOpen] = useState(false)
  const [notice, setNotice] = useState("Jarvis is ready")
  const sendingRef = useRef(false)
  const engineHeard = useRef(false)
  const recRef = useRef<{ stop: () => void } | null>(null)

  const say = useCallback((text: string) => setNotice(text), [])

  const helpers = useMemo(
    () => filterNavItems(helpersFromInventory(), query),
    [query]
  )
  const chatRows = useMemo(
    () => filterNavItems(chatsFromHistory(turns), query),
    [turns, query]
  )
  const selected = helpersFromInventory().find((row) => row.id === selectedId) || helpersFromInventory()[0]
  const title = selected?.ready === false ? selected.name : selected?.name || LABELS.lead

  const computerView = liveComputerView({
    talkMode,
    paneOpen: panes.right,
    screenShown,
    running: computerRunning,
  })

  const connectedCopy =
    talkMode === "terminal"
      ? LABELS.terminal
      : computerView.visible && computerRunning
        ? LABELS.connected
        : computerView.visible
          ? "Not running"
          : "Hidden"

  const savePanes = useCallback((next: { left: boolean; right: boolean }) => {
    setPanes(next)
    try {
      localStorage.setItem(PANE_STORAGE, JSON.stringify(next))
    } catch {
      /* ignore */
    }
  }, [])

  const applyMode = useCallback((value: unknown) => {
    const next = normalizeTalkMode(value)
    setTalkMode(next)
    if (next === "terminal") {
      setScreenShown(false)
      try {
        sessionStorage.setItem(SCREEN_STORAGE, "0")
      } catch {
        /* ignore */
      }
    }
    return next
  }, [])

  const loadHistory = useCallback(async () => {
    if (sendingRef.current) return
    const data = await fetchTalkLast()
    if (sendingRef.current) return
    setTurns((prev) => {
      if (!prev.length) return mergeHistory([], data.turns)
      if (Array.isArray(data.turns) && data.turns.length >= prev.length) {
        return mergeHistory([], data.turns)
      }
      return prev
    })
  }, [])

  const loadSettings = useCallback(async () => {
    const data = await fetchSettings()
    applyMode(data.talk_mode)
    setModelLabel(friendlyModel(data))
  }, [applyMode])

  const loadPc = useCallback(async () => {
    if (!computerView.visible) return
    const data = await fetchComputerScreen()
    if (data.running) {
      setComputerRunning(true)
      setScreenCopy(LABELS.screenLive)
      return
    }
    setComputerRunning(false)
    setScreenCopy(data.error || LABELS.screenDown)
  }, [computerView.visible])

  useEffect(() => {
    const width = typeof window === "undefined" ? 1400 : window.innerWidth
    const stored = readJson(typeof window === "undefined" ? null : localStorage.getItem(PANE_STORAGE), {
      left: true,
      right: true,
    })
    setPanes(width < COLLAPSE_BELOW ? defaultPanesForWidth(width) : stored)
    setSections(
      readJson(typeof window === "undefined" ? null : localStorage.getItem(NAV_STORAGE), {
        helpers: true,
        chats: true,
        groups: false,
      })
    )
    try {
      const raw = sessionStorage.getItem(SCREEN_STORAGE)
      if (raw === "0") setScreenShown(false)
    } catch {
      /* ignore */
    }
    loadHistory()
    loadSettings()
    fetchRoutines().then((payload) => setRoutines(routinesFromPayload(payload)))
    const hist = window.setInterval(() => {
      if (!sendingRef.current) loadHistory()
    }, 4000)
    const settingsTick = window.setInterval(() => {
      if (document.visibilityState === "visible") loadSettings()
    }, 4000)
    const onResize = () => {
      if (window.innerWidth < COLLAPSE_BELOW) {
        setPanes({ left: false, right: false })
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "k") {
        e.preventDefault()
        document.getElementById("search")?.focus()
      }
    }
    window.addEventListener("resize", onResize)
    window.addEventListener("keydown", onKey)
    window.addEventListener("focus", loadSettings)
    return () => {
      window.clearInterval(hist)
      window.clearInterval(settingsTick)
      window.removeEventListener("resize", onResize)
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("focus", loadSettings)
    }
  }, [loadHistory, loadSettings])

  useEffect(() => {
    if (!computerView.visible) {
      setComputerRunning(false)
      setScreenCopy(talkMode === "terminal" ? LABELS.terminalScreen : LABELS.screenHidden)
      return
    }
    loadPc()
  }, [computerView.visible, talkMode, loadPc])

  useEffect(() => {
    const bridge = desktopBridge()
    if (!bridge) return
    bridge.onTalk?.((event) => {
      const next = applyTalkEvent([], event)
      if (event.you) {
        engineHeard.current = true
        stopBrowserListen()
        setTurns((prev) => appendTurn(prev, { role: "you", text: event.you }))
        postTalkLog("you", String(event.you || ""))
      }
      if (event.reply) {
        setTurns((prev) => appendTurn(prev, { role: "jarvis", text: event.reply }))
        postTalkLog("jarvis", String(event.reply || ""))
        sendingRef.current = false
        setSending(false)
        setSubtitle(LABELS.ready)
        return
      }
      if (event.status === "listening") {
        setListening(true)
        setSubtitle(LABELS.listening)
      }
      if (event.status === "thinking") {
        sendingRef.current = true
        setSending(true)
        setSubtitle(LABELS.thinking)
      }
      void next
    })
    bridge.onAvatarAsk?.((text) => {
      void sendAsk(text)
    })
    bridge.onFocusVoice?.(() => {
      startListen()
    })
    // Bind Electron talk/avatar hooks once. sendAsk/startListen read refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function stopBrowserListen() {
    setListening(false)
    if (recRef.current) {
      try {
        recRef.current.stop()
      } catch {
        /* ignore */
      }
    }
    recRef.current = null
  }

  function startBrowserListen() {
    const Ctor =
      typeof window !== "undefined"
        ? (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition ||
          (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition
        : undefined
    if (!Ctor) {
      if (!desktopBridge()?.startListen) {
        setSubtitle("Talk needs a microphone.")
        say("Talk needs a microphone.")
      }
      return
    }
    stopBrowserListen()
    setListening(true)
    engineHeard.current = false
    const rec = new Ctor()
    rec.continuous = false
    rec.interimResults = false
    rec.lang = "en-US"
    rec.onresult = (e) => {
      const said = String(e.results?.[0]?.[0]?.transcript || "").trim()
      stopBrowserListen()
      if (engineHeard.current) return
      if (said) void sendAsk(said)
    }
    rec.onerror = () => {
      stopBrowserListen()
      if (!engineHeard.current && !sendingRef.current) setSubtitle(LABELS.ready)
    }
    rec.onend = () => {
      stopBrowserListen()
      if (!engineHeard.current && !sendingRef.current) setSubtitle(LABELS.ready)
    }
    recRef.current = rec
    try {
      rec.start()
    } catch {
      stopBrowserListen()
    }
  }

  function startListen() {
    engineHeard.current = false
    setSubtitle(LABELS.listening)
    setListening(true)
    say(LABELS.listening)
    desktopBridge()?.startListen?.()
    startBrowserListen()
  }

  async function sendAsk(text: string) {
    const asked = composerSubmit(text)
    if (!asked.ok || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setDraft("")
    setTurns((prev) => appendTurn(prev, { role: "you", text: asked.text }))
    setSubtitle(LABELS.thinking)
    say("Sending…")
    desktopBridge()?.reportTalk?.({ status: "thinking", you: asked.text })
    try {
      const data = await fetchAsk(asked.text)
      const parsed = parseAskReply(data)
      sendingRef.current = false
      setSending(false)
      if (parsed.ok) {
        setTurns((prev) => appendTurn(prev, { role: "jarvis", text: parsed.reply }))
        setSubtitle(LABELS.ready)
        desktopBridge()?.reportTalk?.({ status: "idle", reply: parsed.reply })
        const muted = await desktopBridge()?.getMuted?.().catch(() => ({ muted: false }))
        if (!muted?.muted) await playSpeak(parsed.reply)
        return
      }
      setSubtitle(LABELS.cantTalk)
      say(LABELS.cantTalk)
    } catch {
      sendingRef.current = false
      setSending(false)
      setSubtitle(LABELS.cantTalk)
      say(LABELS.cantTalk)
    }
  }

  function openSettings() {
    setMenuOpen(false)
    if (desktopBridge()?.openSettings) {
      void desktopBridge()?.openSettings?.()
      return
    }
    window.location.href = "/ceo?settings=1&desktop=1"
  }

  function openScreen() {
    if (desktopBridge()?.openScreen) {
      void desktopBridge()?.openScreen?.()
      return
    }
    window.open("/ceo/jarvis-screen", "jarvis-screen")
  }

  return (
    <div className="flex h-full min-h-0" id="app" data-ask="/api/jarvis/ask" data-talk-last="/api/jarvis/talk/last" data-routines="/api/jarvis/routines">
      <div className="sr-only" id="status" aria-live="polite">
        {notice}
      </div>
      {!panes.left && (
        <button
          type="button"
          className="edge absolute top-1/2 left-2 z-3 grid size-8 -translate-y-1/2 place-items-center rounded-full bg-white shadow"
          id="show-left"
          aria-label="Show chats"
          onClick={() => savePanes({ left: true, right: panes.right })}
        >
          ‹
        </button>
      )}
      {!panes.right && (
        <button
          type="button"
          className="edge absolute top-1/2 right-2 z-3 grid size-8 -translate-y-1/2 place-items-center rounded-full bg-white shadow"
          id="show-right"
          aria-label="Show computer"
          onClick={() => savePanes({ left: panes.left, right: true })}
        >
          ›
        </button>
      )}
      {panes.left && (
        <LeftPane
          query={query}
          onQuery={setQuery}
          helpers={helpers}
          chats={chatRows}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id)
            const lead = helpersFromInventory().find((row) => row.id === id)
            setSubtitle(lead && lead.ready === false ? lead.subtitle : LABELS.ready)
          }}
          sections={sections}
          onToggleSection={(key) => {
            const next = { ...sections, [key]: !sections[key] }
            setSections(next)
            try {
              localStorage.setItem(NAV_STORAGE, JSON.stringify(next))
            } catch {
              /* ignore */
            }
          }}
          onNewChat={() => {
            setSelectedId("jarvis")
            setSubtitle(LABELS.ready)
            document.getElementById("ask")?.focus()
          }}
          onHideLeft={() => savePanes({ left: false, right: panes.right })}
          onOpenSettings={openSettings}
          onPlugins={() => {
            say(LABELS.pluginsSoon)
            setSubtitle(LABELS.pluginsSoon)
          }}
          onProfile={() => {
            say(LABELS.profileSoon)
            setSubtitle(LABELS.profileSoon)
          }}
          onRoutinesNav={() => {
            if (!panes.right) savePanes({ left: panes.left, right: true })
            document.getElementById("routines-block")?.scrollIntoView({ block: "nearest" })
          }}
          onViewAll={() => {
            const next = { ...sections, chats: true, groups: true }
            setSections(next)
            try {
              localStorage.setItem(NAV_STORAGE, JSON.stringify(next))
            } catch {
              /* ignore */
            }
          }}
        />
      )}
      <MiddlePane
        title={title}
        subtitle={subtitle}
        modelLabel={modelLabel}
        turns={turns}
        sending={sending}
        listening={listening}
        draft={draft}
        onDraft={setDraft}
        onSubmit={() => void sendAsk(draft)}
        onMic={() => {
          if (listening) {
            stopBrowserListen()
            setSubtitle(LABELS.ready)
            return
          }
          startListen()
        }}
        onAttach={() => {
          say(LABELS.addSoon)
          setSubtitle(LABELS.addSoon)
        }}
        onOpenSettings={openSettings}
        onHideRight={() => {
          setMenuOpen(false)
          savePanes({ left: panes.left, right: false })
        }}
        menuOpen={menuOpen}
        onToggleMenu={() => setMenuOpen((v) => !v)}
      />
      {panes.right && (
        <RightPane
          talkMode={talkMode}
          screenShown={screenShown}
          computerRunning={computerRunning}
          connectedCopy={connectedCopy}
          screenCopy={screenCopy}
          starting={starting}
          routineNote={routineNote}
          routines={routines}
          onTalkMode={(mode) => {
            applyMode(mode)
            persistTalkMode(mode)
          }}
          onHideScreen={() => {
            if (talkMode === "terminal") return
            setScreenShown(false)
            try {
              sessionStorage.setItem(SCREEN_STORAGE, "0")
            } catch {
              /* ignore */
            }
          }}
          onShowScreen={() => {
            if (talkMode === "terminal") return
            setScreenShown(true)
            try {
              sessionStorage.setItem(SCREEN_STORAGE, "1")
            } catch {
              /* ignore */
            }
          }}
          onStartComputer={async () => {
            setStarting(true)
            setScreenCopy("Starting the one existing computer. This is not a screenshot.")
            const data = await startComputer()
            setStarting(false)
            if (data.running) {
              setComputerRunning(true)
              setScreenCopy(LABELS.screenLive)
              return
            }
            setComputerRunning(false)
            setScreenCopy(data.error || LABELS.screenDown)
          }}
          onOpenScreen={openScreen}
          onExpandScreen={() => {
            const slot = document.getElementById("live-computer")
            if (slot && slot.requestFullscreen) {
              slot.requestFullscreen().catch(() => openScreen())
              return
            }
            openScreen()
          }}
          onHideRight={() => savePanes({ left: panes.left, right: false })}
          onAddRoutine={() => setRoutineNote(LABELS.addRoutineSoon)}
          onRoutineClick={() => setRoutineNote("This routine is on the schedule. Changing it comes later.")}
        />
      )}
    </div>
  )
}

type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  onresult: ((e: { results?: Array<Array<{ transcript?: string }>> }) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
}
