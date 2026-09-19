"use client"

import { LABELS, NOVNC_SESSION_URL, type TalkMode } from "@/lib/jarvis"

type Routine = { id: string; name: string; when: string }

type Props = {
  talkMode: TalkMode
  screenShown: boolean
  computerRunning: boolean
  connectedCopy: string
  screenCopy: string
  starting: boolean
  routineNote: string
  routines: Routine[]
  onTalkMode: (mode: TalkMode) => void
  onHideScreen: () => void
  onShowScreen: () => void
  onStartComputer: () => void
  onOpenScreen: () => void
  onExpandScreen: () => void
  onHideRight: () => void
  onAddRoutine: () => void
  onRoutineClick: () => void
}

export function RightPane({
  talkMode,
  screenShown,
  computerRunning,
  connectedCopy,
  screenCopy,
  starting,
  routineNote,
  routines,
  onTalkMode,
  onHideScreen,
  onShowScreen,
  onStartComputer,
  onOpenScreen,
  onExpandScreen,
  onHideRight,
  onAddRoutine,
  onRoutineClick,
}: Props) {
  const terminal = talkMode === "terminal"
  const show = !terminal && screenShown
  const live = show && computerRunning

  return (
    <aside
      className="flex h-full min-h-0 w-[360px] shrink-0 flex-col border-l border-[#E6E8EE] bg-white"
      id="right"
      aria-label="Computer"
    >
      <div className="flex items-center gap-2 px-3 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-[#F3F4F6] text-[#374151]">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <rect x="4" y="5" width="16" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
              <path d="M8 20h8M12 16v4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </span>
          <div>
            <h2 className="m-0 text-[15px] font-semibold text-[#111827]">{LABELS.liveComputer}</h2>
            <div className="flex items-center gap-1.5 text-xs text-[#6B7280]" id="pc-connected" data-on={live ? "1" : "0"}>
              <i className={`inline-block size-1.5 rounded-full ${live ? "bg-[#22C55E]" : "bg-[#D1D5DB]"}`} />
              <span id="pc-connected-copy">{connectedCopy}</span>
            </div>
          </div>
        </div>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
          id="expand-screen"
          aria-label="Expand screen"
          title="Expand"
          onClick={onExpandScreen}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M9 5H5v4M15 5h4v4M5 15v4h4M19 15v4h-4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
          id="hide-right"
          aria-label="Hide computer"
          onClick={onHideRight}
        >
          ⋯
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 px-3 pb-2" role="group" aria-label="Computer or chat only">
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded-full border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 text-xs text-[#374151] data-[on=1]:border-[#2563EB] data-[on=1]:bg-[#DBEAFE] data-[on=1]:text-[#2563EB]"
          id="mode-computer"
          data-talk-mode="computer"
          data-on={talkMode === "computer" ? "1" : "0"}
          onClick={() => onTalkMode("computer")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="4" y="5" width="16" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
          </svg>
          Computer
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center rounded-full border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 text-xs text-[#374151] data-[on=1]:border-[#2563EB] data-[on=1]:bg-[#DBEAFE] data-[on=1]:text-[#2563EB]"
          id="mode-terminal"
          data-talk-mode="terminal"
          data-on={terminal ? "1" : "0"}
          onClick={() => onTalkMode("terminal")}
        >
          Chat only
        </button>
        <button
          type="button"
          className="screen-only inline-flex h-8 items-center rounded-full border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 text-xs text-[#374151]"
          id="hide-screen"
          aria-label="Hide screen"
          hidden={!show}
          onClick={onHideScreen}
        >
          {LABELS.hideScreen}
        </button>
        <button
          type="button"
          className="screen-only inline-flex h-8 items-center rounded-full border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 text-xs text-[#374151]"
          id="show-screen"
          aria-label="Show screen"
          hidden={show || terminal}
          onClick={onShowScreen}
        >
          {LABELS.showScreen}
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center rounded-full border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 text-xs text-[#374151]"
          id="open-screen"
          onClick={onOpenScreen}
        >
          {LABELS.openScreen}
        </button>
      </div>

      <p className="terminal-note px-3 pb-2 text-xs text-[#6B7280]" id="terminal-note" hidden={!terminal}>
        {LABELS.terminalScreen}
      </p>

      <div
        className="relative mx-3 min-h-[180px] flex-1 overflow-hidden rounded-2xl bg-[#111827]"
        id="live-computer"
        data-embed="iframe"
        aria-label="Jarvis's screen"
        hidden={!show}
      >
        <iframe
          id="live-frame"
          title="Jarvis's screen"
          src={live ? NOVNC_SESSION_URL : ""}
          hidden={!live}
          className="absolute inset-0 h-full w-full border-0"
        />
        <div id="screen-idle" className="absolute inset-0 grid place-items-center p-4 text-center" hidden={live}>
          <div>
            <p className="m-0 text-sm text-white" id="screen-copy">
              {screenCopy}
            </p>
            <button
              type="button"
              className="mt-3 inline-flex h-8 items-center rounded-full bg-white px-3 text-xs text-[#111827]"
              id="start-computer"
              hidden={!show || live}
              disabled={starting}
              onClick={onStartComputer}
            >
              {starting ? "Starting…" : LABELS.startComputer}
            </button>
          </div>
        </div>
        <div className="absolute top-2 right-2 flex gap-1" id="screen-tools">
          <button type="button" id="tool-fullscreen" title="Full screen" aria-label="Full screen" className="grid size-7 place-items-center rounded-md bg-black/40 text-white" onClick={onExpandScreen}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
              <path d="M8 5H5v3M16 5h3v3M5 16v3h3M19 16v3h-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      <div className="pc-using mx-3 mt-2 flex items-center gap-2 text-xs text-[#6B7280]" id="pc-using" hidden={!live}>
        <i className="inline-block size-1.5 rounded-full bg-[#22C55E]" />
        <span id="pc-using-copy">{LABELS.usingComputer}</span>
      </div>

      <div className="mt-2 border-t border-[#E6E8EE] px-3 py-3" id="routines-block">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="m-0 flex items-center gap-1.5 text-sm font-semibold text-[#111827]">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="13" r="6.5" stroke="currentColor" strokeWidth="1.7" />
              <path d="M12 10v3.2L14 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
            Routines
          </h3>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
            id="add-routine"
            aria-label="Add routine"
            title="Add routine"
            onClick={onAddRoutine}
          >
            +
          </button>
        </div>
        <div className="list flex flex-col gap-1.5" id="routines" data-source="local-schedules">
          {routines.map((row) => (
            <button
              key={row.id}
              type="button"
              className="routine flex w-full items-center justify-between rounded-xl border border-[#E6E8EE] bg-[#F3F4F6] px-2.5 py-2 text-left"
              data-id={row.id}
              data-source="local-schedules"
              onClick={onRoutineClick}
            >
              <strong className="text-sm">{row.name}</strong>
              <span className="text-xs text-[#6B7280]">{row.when}</span>
            </button>
          ))}
        </div>
        <div className="routine-empty flex flex-col items-center gap-2 px-2 py-4 text-center" id="routine-empty" hidden={routines.length > 0}>
          <div className="clock grid size-11 place-items-center rounded-full border border-dashed border-[#D1D5DB] text-[#9CA3AF]">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="13" r="6.5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M12 10v3.2L14 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </div>
          <p className="empty-list m-0 text-sm font-medium" id="empty-routines">
            {LABELS.emptyRoutines}
          </p>
          <span className="text-xs text-[#6B7280]">Create a routine to automate repetitive tasks.</span>
          <button
            type="button"
            className="create-routine h-9 rounded-full border border-[#E6E8EE] bg-white px-4 text-sm"
            id="create-routine"
            onClick={onAddRoutine}
          >
            {LABELS.createRoutine}
          </button>
        </div>
        <p className="empty-list px-1 pt-2 text-xs text-[#6B7280]" id="routine-note" hidden={!routineNote}>
          {routineNote}
        </p>
      </div>
    </aside>
  )
}
