export type TalkEvent = {
  status?: string
  you?: string
  reply?: string
}

export type JarvisDesktop = {
  onFocusVoice?: (cb: () => void) => void
  onAvatarAsk?: (cb: (text: string) => void) => void
  reportTalk?: (payload: TalkEvent) => void
  openScreen?: () => Promise<unknown>
  openSettings?: () => Promise<unknown>
  startListen?: () => Promise<unknown>
  askTalk?: (text: string) => Promise<unknown>
  onTalk?: (cb: (payload: TalkEvent) => void) => void
  getMuted?: () => Promise<{ muted?: boolean }>
  onMuted?: (cb: (state: { muted?: boolean }) => void) => void
}

declare global {
  interface Window {
    jarvisDesktop?: JarvisDesktop
    jarvisApiBase?: string
  }
}

export function desktopBridge(): JarvisDesktop | undefined {
  if (typeof window === "undefined") return undefined
  return window.jarvisDesktop
}

export function hasDesktopBridge(): boolean {
  return !!desktopBridge()
}
