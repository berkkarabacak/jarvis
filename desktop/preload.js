// CEO UI is served by the local web app. Desktop hooks:
// voice-focus from the mini avatar (ORCH-397) and ask/reply
// so the overlay can talk without raising this window (ORCH-398).
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
