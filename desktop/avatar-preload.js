const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisAvatar", {
  moveBy: (dx, dy) => ipcRenderer.invoke("avatar:move-by", { dx, dy }),
  clicked: () => ipcRenderer.invoke("avatar:clicked"),
  expand: () => ipcRenderer.invoke("avatar:expand"),
  ask: (text) => ipcRenderer.invoke("avatar:ask", { text }),
  health: () => ipcRenderer.invoke("avatar:health"),
  typeFocus: () => ipcRenderer.invoke("avatar:type-focus"),
  typeBlur: () => ipcRenderer.invoke("avatar:type-blur"),
  quit: () => ipcRenderer.invoke("avatar:quit"),
  setMuted: (muted) => ipcRenderer.invoke("avatar:set-muted", { muted: !!muted }),
  getMuted: () => ipcRenderer.invoke("jarvis:get-muted"),
  onMuted: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("avatar:muted", (_event, state) => {
      try {
        cb(state);
      } catch (_) {}
    });
  },
  onBubble: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("avatar:bubble", (_event, state) => {
      try {
        cb(state);
      } catch (_) {}
    });
  },
  onTalk: (cb) => {
    if (typeof cb !== "function") return;
    ipcRenderer.on("avatar:talk", (_event, state) => {
      try {
        cb(state);
      } catch (_) {}
    });
  },
});
