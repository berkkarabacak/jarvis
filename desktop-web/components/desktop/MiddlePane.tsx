"use client"

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ui/conversation"
import { Message, MessageContent } from "@/components/ui/message"
import { Orb } from "@/components/ui/orb"
import { Response } from "@/components/ui/response"
import { LABELS, formatChatWhen, type TalkTurn } from "@/lib/jarvis"

type Props = {
  title: string
  subtitle: string
  modelLabel: string
  turns: TalkTurn[]
  sending: boolean
  listening: boolean
  draft: string
  onDraft: (value: string) => void
  onSubmit: () => void
  onMic: () => void
  onAttach: () => void
  onOpenSettings: () => void
  onHideRight: () => void
  menuOpen: boolean
  onToggleMenu: () => void
}

export function MiddlePane({
  title,
  subtitle,
  modelLabel,
  turns,
  sending,
  listening,
  draft,
  onDraft,
  onSubmit,
  onMic,
  onAttach,
  onOpenSettings,
  onHideRight,
  menuOpen,
  onToggleMenu,
}: Props) {
  const empty = turns.length === 0 && !sending && !listening

  return (
    <main
      className="flex min-h-0 min-w-[280px] flex-1 flex-col bg-[#F8F9FB]"
      id="middle"
      aria-label="Chat"
      data-chat="live"
    >
      <div className="relative flex items-center gap-3 border-b border-[#E6E8EE] bg-white px-4 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="grid size-9 place-items-center rounded-full bg-[#2563EB] text-sm font-semibold text-white">
            J
          </span>
          <div className="min-w-0">
            <h2 className="m-0 text-[15px] font-semibold text-[#111827]" id="chat-title">
              {title}
            </h2>
            <span className="text-xs text-[#6B7280]" id="chat-sub">
              {subtitle}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="model-btn rounded-full bg-[#F3F4F6] px-3 py-1.5 text-xs text-[#374151]"
          id="model-btn"
          aria-label="Current model"
          title="Current model from Settings"
          onClick={onOpenSettings}
        >
          <span id="model-label">{modelLabel}</span> ▾
        </button>
        <button
          type="button"
          className="grid size-8 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
          id="chat-menu"
          aria-label="Chat menu"
          title="More"
          onClick={onToggleMenu}
        >
          ⋯
        </button>
        {menuOpen && (
          <div className="absolute top-14 right-4 z-5 min-w-[180px] rounded-xl border border-[#E6E8EE] bg-white p-1.5 shadow-lg" id="more-menu">
            <button
              type="button"
              className="h-8 w-full rounded-lg px-2.5 text-left text-sm hover:bg-[#F3F4F6]"
              id="menu-settings"
              onClick={onOpenSettings}
            >
              Settings
            </button>
            <button
              type="button"
              className="h-8 w-full rounded-lg px-2.5 text-left text-sm hover:bg-[#F3F4F6]"
              id="menu-hide-right"
              onClick={onHideRight}
            >
              Hide computer
            </button>
          </div>
        )}
      </div>

      <div className="relative min-h-0 flex-1" id="thread" aria-live="polite">
        <Conversation className="h-full">
          <ConversationContent className="min-h-full">
            {empty ? (
              <ConversationEmptyState
                id="empty-chat"
                icon={<Orb className="size-16" agentState={null} />}
                title={LABELS.emptyOrbTitle}
                description={LABELS.emptyChat}
              />
            ) : (
              <>
                {turns.map((turn, index) => (
                  <Message
                    from={turn.role === "you" ? "user" : "assistant"}
                    key={`${turn.role}-${index}-${turn.ts}`}
                    className={turn.role === "you" ? "msg you" : "msg jarvis"}
                    data-role={turn.role}
                  >
                    {turn.role === "jarvis" && (
                      <span className="grid size-8 place-items-center overflow-hidden rounded-full bg-[#2563EB] ring-1 ring-[#E6E8EE]">
                        <Orb className="h-full w-full" agentState={null} />
                      </span>
                    )}
                    <MessageContent
                      variant={turn.role === "you" ? "contained" : "flat"}
                      className={
                        turn.role === "you"
                          ? "group-[.is-user]:bg-[#E8F1FF] group-[.is-user]:text-[#111827]"
                          : "max-w-[80%]"
                      }
                    >
                      {turn.role === "jarvis" ? (
                        <Response>{turn.text}</Response>
                      ) : (
                        <p className="m-0 whitespace-pre-wrap">{turn.text}</p>
                      )}
                      {turn.role === "you" && turn.ts ? (
                        <span className="block pt-1 text-[11px] text-[#6B7280]">
                          {formatChatWhen(turn.ts)}
                        </span>
                      ) : null}
                    </MessageContent>
                  </Message>
                ))}
                {sending && (
                  <Message from="assistant" className="msg jarvis pending" id="pending">
                    <span className="grid size-8 place-items-center overflow-hidden rounded-full bg-[#2563EB] ring-1 ring-[#E6E8EE]">
                      <Orb className="h-full w-full" agentState="thinking" />
                    </span>
                    <MessageContent variant="flat">
                      <p className="m-0 text-[#6B7280]" id="pending-copy">
                        {LABELS.thinking}
                      </p>
                    </MessageContent>
                  </Message>
                )}
              </>
            )}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
      </div>

      <form
        className="flex items-center gap-2 border-t border-[#E6E8EE] bg-white px-3 py-3"
        id="composer"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit()
        }}
      >
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
          id="add"
          aria-label="Add"
          title="Add"
          onClick={onAttach}
        >
          +
        </button>
        <input
          id="ask"
          type="text"
          placeholder={LABELS.composer}
          aria-label="Type a message"
          autoComplete="off"
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          className="h-10 min-w-0 flex-1 rounded-full border-0 bg-[#F3F4F6] px-4 text-sm text-[#111827] outline-none"
        />
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full bg-[#F3F4F6] text-[#374151]"
          id="attach"
          aria-label="Attach"
          title="Attach"
          onClick={onAttach}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M8.5 12.5l6.2-6.2a3 3 0 1 1 4.2 4.2l-8 8a3.8 3.8 0 0 1-5.4-5.4l7.2-7.2"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full bg-[#F3F4F6] text-[#374151] data-[on=1]:bg-[#DBEAFE] data-[on=1]:text-[#2563EB]"
          id="mic"
          aria-label="Talk"
          title="Talk"
          data-on={listening ? "1" : "0"}
          onClick={onMic}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="9" y="4" width="6" height="10" rx="3" stroke="currentColor" strokeWidth="1.7" />
            <path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="submit"
          className="send grid size-9 place-items-center rounded-full bg-[#2563EB] text-white"
          id="send"
          aria-label="Send"
          title="Send"
          disabled={sending}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 18V7M7.5 11.5 12 7l4.5 4.5"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </main>
  )
}
