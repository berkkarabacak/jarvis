// CEO UI is served by the local web app. Desktop hooks:
// voice-focus from the mini avatar (ORCH-397) and ask/reply
// so the overlay can talk without raising this window (ORCH-398).
// /desktop middle pane (#69) starts listen and receives talk events.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisDesktop", {
  onFocusVoice: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("jarvis:focus-voice", () => {
      try {
        cb();
      } catch (_) {}
    });
  },
  onAvatarAsk: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("jarvis:avatar-ask", (_event, payload) => {
      try {
        cb(payload && payload.text);
      } catch (_) {}
    });
  },
  reportTalk: (payload) => {
    ipcRenderer.send("jarvis:talk", payload || {});
  },
  openScreen: () => ipcRenderer.invoke("jarvis:open-screen"),
  openSettings: () => ipcRenderer.invoke("jarvis:open-settings"),
  startListen: () => ipcRenderer.invoke("jarvis:start-listen"),
  askTalk: (text) => ipcRenderer.invoke("jarvis:ask-talk", { text: text }),
  onTalk: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("jarvis:talk-event", (_event, payload) => {
      try {
        cb(payload || {});
      } catch (_) {}
    });
  },
  getMuted: () => ipcRenderer.invoke("jarvis:get-muted"),
  onMuted: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("jarvis:muted", (_event, state) => {
      try {
        cb(state);
      } catch (_) {}
    });
  },
});
