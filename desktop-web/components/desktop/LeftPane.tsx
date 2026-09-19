"use client"

import { LABELS } from "@/lib/jarvis"

type Helper = {
  id: string
  name: string
  initial: string
  color: string
  subtitle: string
  source: string
  live: boolean
  ready: boolean
}

type ChatRow = {
  id: string
  name: string
  preview: string
  when: string
  source: string
  live: boolean
}

type Props = {
  query: string
  onQuery: (value: string) => void
  helpers: Helper[]
  chats: ChatRow[]
  selectedId: string
  onSelect: (id: string) => void
  sections: { helpers: boolean; chats: boolean; groups: boolean }
  onToggleSection: (key: "helpers" | "chats" | "groups") => void
  onNewChat: () => void
  onHideLeft: () => void
  onOpenSettings: () => void
  onPlugins: () => void
  onProfile: () => void
  onRoutinesNav: () => void
  onViewAll: () => void
}

function NavIcon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="size-4">
      <path d={d} stroke="currentColor" strokeWidth="1.7" />
    </svg>
  )
}

export function LeftPane({
  query,
  onQuery,
  helpers,
  chats,
  selectedId,
  onSelect,
  sections,
  onToggleSection,
  onNewChat,
  onHideLeft,
  onOpenSettings,
  onPlugins,
  onProfile,
  onRoutinesNav,
  onViewAll,
}: Props) {
  return (
    <aside
      className="flex h-full min-h-0 w-[276px] shrink-0 flex-col bg-[#1A1D23] text-[#F4F5F7]"
      id="left"
      aria-label="Chats"
    >
      <div className="flex items-center gap-2.5 px-3.5 pt-4 pb-3">
        <div
          className="grid size-9 shrink-0 place-items-center rounded-full bg-linear-to-b from-[#4F8CFF] to-[#3B6EF0] text-base font-bold text-white shadow-[0_0_0_6px_rgba(59,110,240,0.16)]"
          aria-hidden="true"
        >
          J
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-base font-semibold">{LABELS.app}</h1>
          <p className="m-0 text-xs text-[#8B919A]">{LABELS.teammate}</p>
        </div>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full hover:bg-[#2A2F38]"
          id="new-chat"
          aria-label="New chat"
          title="New chat"
          onClick={onNewChat}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full hover:bg-[#2A2F38]"
          id="hide-left"
          aria-label="Hide chats"
          onClick={onHideLeft}
        >
          ‹
        </button>
      </div>

      <div className="px-3 pb-3">
        <div className="relative">
          <svg className="pointer-events-none absolute top-2.5 left-3 size-4 text-[#8B919A]" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
            <path d="M16 16l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            id="search"
            type="search"
            placeholder={LABELS.search}
            aria-label="Search"
            autoComplete="off"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            className="h-[38px] w-full rounded-xl border-0 bg-[#22262E] pr-14 pl-8 text-[13px] text-[#F4F5F7] outline-none placeholder:text-[#8B919A]"
          />
          <kbd className="absolute top-2 right-2 rounded-md bg-[#2C313A] px-1.5 text-[10px] leading-5 text-[#8B919A]">
            Ctrl K
          </kbd>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2" id="left-lists">
        <nav className="flex flex-col gap-0.5 px-1 pb-2" aria-label="Main">
          <button
            type="button"
            className="flex h-9 items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-[#2A2F38] data-[on=1]:bg-[#2A2F38]"
            id="nav-chat"
            data-on={selectedId === "writer" || selectedId === "helper" || selectedId === "finder" ? "0" : "1"}
            onClick={onNewChat}
          >
            <NavIcon d="M5 7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5v6A2.5 2.5 0 0 1 16.5 16H10l-4 3v-3.2A2.5 2.5 0 0 1 5 13.5v-6Z" />
            <span>Chat</span>
          </button>
          <button
            type="button"
            className="flex h-9 items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-[#2A2F38]"
            id="nav-helpers"
            onClick={() => onToggleSection("helpers")}
          >
            <NavIcon d="M8 9m-2.4 0a2.4 2.4 0 1 0 4.8 0a2.4 2.4 0 1 0-4.8 0M16 9m-2.4 0a2.4 2.4 0 1 0 4.8 0a2.4 2.4 0 1 0-4.8 0M4.8 17.5c.6-2.2 2.4-3.5 5.2-3.5s4.6 1.3 5.2 3.5" />
            <span>Helpers</span>
          </button>
          <button
            type="button"
            className="flex h-9 items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-[#2A2F38]"
            id="plugins"
            onClick={onPlugins}
          >
            <NavIcon d="M8 4v3M16 4v3M6.5 8h11A1.5 1.5 0 0 1 19 9.5V17a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V9.5A1.5 1.5 0 0 1 6.5 8Z" />
            <span>Plugins</span>
          </button>
          <button
            type="button"
            className="flex h-9 items-center gap-2.5 rounded-xl px-2.5 text-left text-[13px] hover:bg-[#2A2F38]"
            id="nav-routines"
            onClick={onRoutinesNav}
          >
            <NavIcon d="M12 13m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0M12 10v3.2L14.2 15M9 4h6" />
            <span>Routines</span>
            <span className="ml-auto rounded-full bg-[#2A2F38] px-1.5 text-[10px] text-[#8B919A]">Beta</span>
          </button>
        </nav>

        <section className="mt-1" data-section="helpers" data-open={sections.helpers ? "1" : "0"}>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] tracking-wide text-[#8B919A] uppercase"
            id="toggle-helpers"
            aria-expanded={sections.helpers}
            aria-controls="agents"
            onClick={() => onToggleSection("helpers")}
          >
            <span>Assistants</span>
            <span className="ml-auto" aria-hidden="true">{sections.helpers ? "▾" : "▸"}</span>
          </button>
          {sections.helpers && (
            <div id="helpers-body">
              <div className="flex flex-col gap-0.5" id="agents" data-source="local-lead documented-stub">
                {helpers.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    className="flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left hover:bg-[#2A2F38] data-[on=1]:bg-[#2A2F38]"
                    data-id={row.id}
                    data-source={row.source}
                    data-live={row.live ? "1" : "0"}
                    data-on={selectedId === row.id ? "1" : "0"}
                    onClick={() => onSelect(row.id)}
                  >
                    <span
                      className="grid size-8 place-items-center rounded-full text-xs font-semibold text-white"
                      style={{ background: row.color }}
                    >
                      {row.initial}
                    </span>
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate text-[13px] font-medium">{row.name}</strong>
                      <span className="flex items-center gap-1 text-[11px] text-[#8B919A]">
                        {row.live && (
                          <i className="inline-block size-1.5 rounded-full bg-[#22C55E]" aria-hidden="true" />
                        )}
                        {row.subtitle}
                      </span>
                    </span>
                    <span className="unread" data-count="0" />
                  </button>
                ))}
              </div>
              <p className="empty-list px-2.5 py-2 text-xs text-[#8B919A]" id="empty-helpers" hidden={helpers.length > 0}>
                {LABELS.nothingMatches}
              </p>
            </div>
          )}
        </section>

        <section className="mt-2" data-section="chats" data-open={sections.chats ? "1" : "0"}>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] tracking-wide text-[#8B919A] uppercase"
            id="toggle-chats"
            aria-expanded={sections.chats}
            aria-controls="chats"
            onClick={() => onToggleSection("chats")}
          >
            <span>Recent chats</span>
            <span className="ml-auto" aria-hidden="true">{sections.chats ? "▾" : "▸"}</span>
          </button>
          {sections.chats && (
            <div id="chats-body">
              <div className="flex flex-col gap-0.5" id="chats" data-source="talk-history">
                {chats.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    className="flex w-full items-start gap-2 rounded-xl px-2 py-1.5 text-left hover:bg-[#2A2F38] data-[on=1]:bg-[#2A2F38]"
                    data-id={row.id}
                    data-source={row.source}
                    data-live={row.live ? "1" : "0"}
                    data-on={selectedId === row.id ? "1" : "0"}
                    onClick={() => onSelect(row.id)}
                  >
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate text-[13px] font-medium">{row.name}</strong>
                      <span className="block truncate text-[11px] text-[#8B919A]">{row.preview}</span>
                    </span>
                    {row.when ? <span className="shrink-0 text-[10px] text-[#8B919A]">{row.when}</span> : null}
                    <span className="unread" data-count="0" />
                  </button>
                ))}
              </div>
              <p className="empty-list px-2.5 py-2 text-xs text-[#8B919A]" id="empty-chats" hidden={chats.length > 0}>
                {query.trim() ? LABELS.nothingMatches : LABELS.emptyChats}
              </p>
              <button
                type="button"
                className="view-all w-full px-2.5 py-2 text-left text-xs text-[#8B919A] hover:text-[#F4F5F7]"
                id="view-all-chats"
                onClick={onViewAll}
              >
                {LABELS.viewAll}
              </button>
            </div>
          )}
        </section>

        <section className="mt-2" data-section="groups" data-open={sections.groups ? "1" : "0"}>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] tracking-wide text-[#8B919A] uppercase"
            id="toggle-groups"
            aria-expanded={sections.groups}
            aria-controls="groups"
            onClick={() => onToggleSection("groups")}
          >
            <span>Group chats</span>
            <span className="ml-auto" aria-hidden="true">{sections.groups ? "▾" : "▸"}</span>
          </button>
          {sections.groups && (
            <div id="groups-body">
              <div className="list" id="groups" data-source="none" />
              <p className="empty-list px-2.5 py-2 text-xs text-[#8B919A]" id="empty-groups">
                {query.trim() ? LABELS.nothingMatches : LABELS.emptyGroups}
              </p>
            </div>
          )}
        </section>
      </div>

      <div className="flex items-center gap-1 border-t border-[#12141A] px-2 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-xl px-2 py-1.5 text-left hover:bg-[#2A2F38]"
          id="profile"
          onClick={onProfile}
        >
          <span className="grid size-8 place-items-center rounded-full bg-[#2563EB] text-xs font-semibold text-white">
            B
          </span>
          <span className="min-w-0">
            <strong className="block truncate text-[13px]">You</strong>
            <span className="block truncate text-[11px] text-[#8B919A]">berk@jarvis.app</span>
          </span>
        </button>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full hover:bg-[#2A2F38]"
          id="settings"
          aria-label="Settings"
          title="Settings"
          onClick={onOpenSettings}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.7" />
            <path
              d="M12 4.5v1.6M12 17.9v1.6M4.5 12h1.6M17.9 12h1.6M6.4 6.4l1.1 1.1M16.5 16.5l1.1 1.1M17.6 6.4l-1.1 1.1M7.5 16.5l-1.1 1.1"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </aside>
  )
}
