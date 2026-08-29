const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisFirstRun", {
  continue: () => ipcRenderer.invoke("first-run:continue"),
  workspaceHint: () => ipcRenderer.invoke("first-run:workspace-hint"),
});
