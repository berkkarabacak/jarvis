/**
 * Jarvis desktop shell.
 *
 * Loads the same CEO UI as the web app from a local uvicorn process.
 * Packaged installer: bundled Python + app tree in extraResources.
 * First run: packaged users go straight to Talk. Berk sets the talk
 * secret on the hosted server or in the private build env. Users never
 * see a key field.
 */
const { app, BrowserWindow, Menu, Tray, nativeImage, shell, dialog, ipcMain, screen } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");
const {
  AVATAR,
  defaultPosition,
  clampPosition,
  shouldShowMainOnLaunch,
  shouldOpenBubbleOnLaunch,
  shouldShowAvatar,
  shouldHideMainOnClose,
  shouldQuitOnAvatarClose,
  shouldQuitOnAvatarCloseButton,
  bubbleBounds,
  avatarWindowOptions,
  normalizeAsk,
  clipReply,
  buildTalkState,
  buildMuteState,
  trayMenuItems,
} = require("./mini-avatar");
const {
  packagedBackendRoot,
  bundledPythonExes,
  firstRunArgv,
  uvicornArgv,
  pythonChildEnv,
} = require("./packaged-python");
const {
  applyOperatorTalkEnv,
  shouldShowFirstRunKeyWindow,
} = require("./talk-policy");

const DEFAULT_PORT = 8787;
const JARVIS_SCREEN_TITLE = "Jarvis's screen";
const JARVIS_SCREEN_CONTROL = "Open Jarvis's screen";
const JARVIS_NOVNC_URL = "http://127.0.0.1:6080";
let mainWindow = null;
let screenWindow = null;
let avatarWindow = null;
let avatarBubbleOpen = false;
let tray = null;
let jarvisMuted = false;
let serverProc = null;
let shuttingDown = false;
let ownsBackend = false;
let startupComplete = false;
let pathsCache = null;
let currentPort = DEFAULT_PORT;

function ceoUrl(port, extra) {
  const q = new URLSearchParams({ autolisten: "1", handsfree: "1", desktop: "1" });
  if (extra && extra.settings) q.set("settings", "1");
  return `http://127.0.0.1:${port}/ceo?${q.toString()}`;
}

function openSettingsInWindow() {
  expandMainWindow();
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.loadURL(ceoUrl(currentPort, { settings: true }));
}

function jarvisScreenUrl(port) {
  return `http://127.0.0.1:${port}/ceo/jarvis-screen`;
}

function openJarvisScreen() {
  if (screenWindow && !screenWindow.isDestroyed()) {
    if (screenWindow.isMinimized()) screenWindow.restore();
    screenWindow.focus();
    return screenWindow;
  }
  screenWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 500,
    title: JARVIS_SCREEN_TITLE,
    backgroundColor: "#1b1d21",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  screenWindow.setTitle(JARVIS_SCREEN_TITLE);
  screenWindow.on("page-title-updated", (event) => {
    event.preventDefault();
    if (screenWindow && !screenWindow.isDestroyed()) {
      screenWindow.setTitle(JARVIS_SCREEN_TITLE);
    }
  });
  screenWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url && url.startsWith(JARVIS_NOVNC_URL)) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  screenWindow.on("closed", () => {
    screenWindow = null;
  });
  screenWindow.loadURL(jarvisScreenUrl(currentPort));
  return screenWindow;
}

function installAppMenu() {
  const template = [
    {
      label: "Jarvis",
      submenu: [
        {
          label: "Talk",
          click: () => {
            expandMainWindow();
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.loadURL(ceoUrl(currentPort));
            }
          },
        },
        {
          label: "Settings",
          accelerator: "CmdOrCtrl+,",
          click: () => openSettingsInWindow(),
        },
        {
          label: JARVIS_SCREEN_CONTROL,
          click: () => openJarvisScreen(),
        },
        { type: "separator" },
        {
          label: jarvisMuted ? "Unmute" : "Mute",
          click: () => setJarvisMuted(!jarvisMuted),
        },
        { role: "quit", label: "Quit Jarvis" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function quitJarvis() {
  shuttingDown = true;
  stopBackend();
  app.quit();
}

const TRAY_PNG_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAANElEQVR42mNgGJTg00G//9gw2RqJNgimQEjNCivGawAhzQQNGTWACgZQHI1USUgUJ+UBAQCE4RaMdIYciQAAAABJRU5ErkJggg==";

function trayIconImage() {
  const fromFile = path.join(__dirname, "jarvis-tray.png");
  if (fs.existsSync(fromFile)) {
    const img = nativeImage.createFromPath(fromFile);
    if (!img.isEmpty()) return img;
  }
  return nativeImage.createFromDataURL("data:image/png;base64," + TRAY_PNG_B64);
}

function refreshTrayMenu() {
  if (!tray || tray.isDestroyed()) return;
  const items = trayMenuItems(jarvisMuted).map((item) => {
    if (item.id === "mute") {
      return { label: item.label, click: () => setJarvisMuted(!jarvisMuted) };
    }
    return { label: item.label, click: () => quitJarvis() };
  });
  tray.setContextMenu(Menu.buildFromTemplate(items));
}

function createTray() {
  if (tray && !tray.isDestroyed()) {
    refreshTrayMenu();
    return tray;
  }
  tray = new Tray(trayIconImage());
  tray.setToolTip("Jarvis");
  refreshTrayMenu();
  return tray;
}

function persistAvatarState() {
  if (!avatarWindow || avatarWindow.isDestroyed()) {
    try {
      const prev = JSON.parse(fs.readFileSync(avatarStatePath(), "utf8"));
      fs.writeFileSync(
        avatarStatePath(),
        JSON.stringify({
          x: typeof prev.x === "number" ? prev.x : undefined,
          y: typeof prev.y === "number" ? prev.y : undefined,
          muted: jarvisMuted,
        })
      );
    } catch (_) {
      try {
        fs.writeFileSync(avatarStatePath(), JSON.stringify({ muted: jarvisMuted }));
      } catch (__) {}
    }
    return;
  }
  const [x, y] = avatarWindow.getPosition();
  const [width, height] = avatarWindow.getSize();
  const workArea = screen.getPrimaryDisplay().workArea;
  const collapsed = bubbleBounds({ x, y, width, height }, false);
  const pos = clampPosition(collapsed, workArea, AVATAR.size);
  try {
    fs.writeFileSync(avatarStatePath(), JSON.stringify({ ...pos, muted: jarvisMuted }));
  } catch (_) {}
}

function broadcastMuted() {
  const payload = buildMuteState({ muted: jarvisMuted });
  if (avatarWindow && !avatarWindow.isDestroyed()) {
    avatarWindow.webContents.send("avatar:muted", payload);
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("jarvis:muted", payload);
  }
  refreshTrayMenu();
  installAppMenu();
}

function setJarvisMuted(next) {
  jarvisMuted = next === true;
  persistAvatarState();
  broadcastMuted();
  return buildMuteState({ muted: jarvisMuted });
}

function packagedResources() {
  return process.resourcesPath || path.join(path.dirname(process.execPath), "resources");
}

function repoRoot() {
  if (process.env.CONTROL_ROOM_ROOT) return process.env.CONTROL_ROOM_ROOT;
  if (app.isPackaged) {
    const bundled = packagedBackendRoot(packagedResources());
    if (fs.existsSync(path.join(bundled, "app", "main.py"))) return bundled;
  }
  const fromSource = path.resolve(__dirname, "..");
  if (fs.existsSync(path.join(fromSource, "app", "main.py"))) return fromSource;
  const beside = path.resolve(path.dirname(process.execPath), "agent-orchestrator");
  if (fs.existsSync(path.join(beside, "app", "main.py"))) return beside;
  return fromSource;
}

function userDataDir() {
  if (app.isPackaged) return app.getPath("userData");
  return repoRoot();
}

function envFilePath() {
  return path.join(userDataDir(), ".env");
}

function exampleEnvPath(root) {
  const local = path.join(root, "deploy", "local-windows.env.example");
  if (fs.existsSync(local)) return local;
  const fallback = path.join(root, ".env.example");
  return fs.existsSync(fallback) ? fallback : "";
}

function defaultWorkspacePath() {
  const home = process.env.USERPROFILE || process.env.HOME || app.getPath("home");
  return path.join(home, "Documents", "Jarvis");
}

function databasePath() {
  if (app.isPackaged) {
    return path.join(userDataDir(), "data", "control_room.db");
  }
  return path.join(repoRoot(), "data", "control_room.db");
}

function pythonCandidates(root) {
  const list = [];
  if (process.env.CONTROL_ROOM_PYTHON) list.push(process.env.CONTROL_ROOM_PYTHON);
  if (app.isPackaged) {
    list.push(...bundledPythonExes(packagedResources()));
  }
  if (process.platform === "win32") {
    list.push(path.join(root, ".venv", "Scripts", "python.exe"));
    list.push("python");
    list.push("py");
  } else {
    list.push(path.join(root, ".venv", "bin", "python"));
    list.push("python3");
    list.push("python");
  }
  return list;
}

function resolvePython(root) {
  for (const c of pythonCandidates(root)) {
    if (c === "python" || c === "python3" || c === "py") return c;
    if (c && fs.existsSync(c)) return c;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function resolvePaths() {
  if (pathsCache) return pathsCache;
  const root = repoRoot();
  pathsCache = {
    root,
    python: resolvePython(root),
    envPath: envFilePath(),
    examplePath: exampleEnvPath(root),
    workspace: defaultWorkspacePath(),
    database: databasePath(),
  };
  return pathsCache;
}

function readDotEnv(filePath) {
  const out = {};
  if (!fs.existsSync(filePath)) return out;
  const text = fs.readFileSync(filePath, "utf8");
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) continue;
    let v = line.slice(i + 1).trim();
    if (
      (v.startsWith('"') && v.endsWith('"')) ||
      (v.startsWith("'") && v.endsWith("'"))
    ) {
      v = v.slice(1, -1);
    }
    out[line.slice(0, i).trim()] = v;
  }
  return out;
}

function runFirstRunCli(args) {
  const { root, python } = resolvePaths();
  return new Promise((resolve, reject) => {
    const child = spawn(python, firstRunArgv(root, args), {
      cwd: root,
      env: pythonChildEnv(root, process.env),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => {
      out += d;
    });
    child.stderr.on("data", (d) => {
      err += d;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      const line = out.trim().split(/\r?\n/).filter(Boolean).pop() || "";
      let payload = null;
      try {
        payload = line ? JSON.parse(line) : null;
      } catch (_) {
        payload = null;
      }
      if (code !== 0) {
        const msg =
          (payload && payload.error) ||
          err.trim() ||
          out.trim() ||
          `first-run helper exited ${code}`;
        reject(new Error(msg));
        return;
      }
      resolve(payload || { ok: true });
    });
  });
}

function firstRunArgs(extra) {
  const p = resolvePaths();
  const args = ["--env", p.envPath, "--workspace", p.workspace, "--database", p.database];
  if (p.examplePath) args.push("--example", p.examplePath);
  if (app.isPackaged) args.push("--force-local");
  return extra.concat(args);
}

async function ensureLocalEnv() {
  return runFirstRunCli(firstRunArgs(["ensure"]));
}

function waitForHealth(port, timeoutMs = 60000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(
        { host: "127.0.0.1", port, path: "/health", timeout: 2000 },
        (res) => {
          let body = "";
          res.on("data", (c) => (body += c));
          res.on("end", () => {
            if (res.statusCode === 200) return resolve(body);
            again();
          });
        }
      );
      req.on("error", again);
      req.on("timeout", () => {
        req.destroy();
        again();
      });
    };
    const again = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("Jarvis did not start in time. Close it and try again."));
        return;
      }
      setTimeout(tick, 400);
    };
    tick();
  });
}

function fetchJarvisHealth() {
  return new Promise((resolve) => {
    const req = http.get(
      {
        host: "127.0.0.1",
        port: currentPort,
        path: "/api/jarvis/health",
        timeout: 1500,
      },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (_) {
            resolve({ ok: false, can_listen: false, realtime: false });
          }
        });
      }
    );
    req.on("error", () => resolve({ ok: false, can_listen: false, realtime: false }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, can_listen: false, realtime: false });
    });
  });
}

function probeHealth(port) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port, path: "/health", timeout: 1500 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function startBackend(root) {
  const p = resolvePaths();
  const dotenv = readDotEnv(p.envPath);
  const port = Number(process.env.PORT || dotenv.PORT || DEFAULT_PORT);

  if (await probeHealth(port)) {
    ownsBackend = false;
    return { port, owned: false };
  }
  ownsBackend = true;

  const py = p.python;
  const childEnv = applyOperatorTalkEnv(
    pythonChildEnv(root, {
      ...process.env,
      ...dotenv,
      HOST: "127.0.0.1",
      PORT: String(port),
      PUBLIC_BASE_URL: `http://127.0.0.1:${port}`,
    }),
    {
      isPackaged: app.isPackaged,
      processEnv: process.env,
      resourcesPath: packagedResources(),
      readFile: (filePath) => {
        try {
          if (fs.existsSync(filePath)) return fs.readFileSync(filePath, "utf8");
        } catch (_) {}
        return "";
      },
    }
  );
  if (!childEnv.JARVIS_WORKSPACE) childEnv.JARVIS_WORKSPACE = p.workspace;
  if (!childEnv.DATABASE_PATH) childEnv.DATABASE_PATH = p.database;

  const dataDir = path.dirname(childEnv.DATABASE_PATH);
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(childEnv.JARVIS_WORKSPACE, { recursive: true });

  serverProc = spawn(py, uvicornArgv(port), {
    cwd: root,
    env: childEnv,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  serverProc.stdout.on("data", (d) => {
    if (process.env.CONTROL_ROOM_DEBUG) process.stdout.write(d);
  });
  serverProc.stderr.on("data", (d) => {
    if (process.env.CONTROL_ROOM_DEBUG) process.stderr.write(d);
  });
  serverProc.on("exit", (code) => {
    serverProc = null;
    if (!shuttingDown && mainWindow) {
      dialog.showErrorBox(
        "Jarvis",
        `Jarvis stopped unexpectedly (code ${code}). Close the app and open it again.`
      );
    }
  });

  return { port, owned: true };
}

function stopBackend() {
  if (!ownsBackend || !serverProc) return;
  shuttingDown = true;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(serverProc.pid), "/f", "/t"], {
        stdio: "ignore",
        windowsHide: true,
      });
    } else {
      serverProc.kill("SIGTERM");
    }
  } catch (_) {}
  serverProc = null;
}

function showSplash() {
  const splash = new BrowserWindow({
    width: 420,
    height: 180,
    resizable: false,
    maximizable: false,
    minimizable: false,
    autoHideMenuBar: true,
    frame: true,
    title: "Jarvis",
    backgroundColor: "#12263a",
    show: true,
  });
  const html =
    "<!DOCTYPE html><html><body style=\"margin:0;background:#12263a;color:#f4f7fb;" +
    "font:18px/1.4 system-ui,'Segoe UI',sans-serif;display:flex;align-items:center;" +
    "justify-content:center;height:100%\">Starting Jarvis…</body></html>";
  splash.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
  return splash;
}

function showFirstRunWindow() {
  const p = resolvePaths();
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };

    const win = new BrowserWindow({
      width: 520,
      height: 420,
      resizable: false,
      maximizable: false,
      autoHideMenuBar: true,
      title: "Jarvis",
      backgroundColor: "#12263a",
      webPreferences: {
        preload: path.join(__dirname, "first-run-preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });

    const hintHandler = async () => ({
      text: "Your files stay in " + p.workspace,
    });
    const continueHandler = async () => {
      finish(true);
      if (!win.isDestroyed()) win.close();
      return { ok: true };
    };

    ipcMain.removeHandler("first-run:continue");
    ipcMain.removeHandler("first-run:workspace-hint");
    ipcMain.handle("first-run:continue", continueHandler);
    ipcMain.handle("first-run:workspace-hint", hintHandler);

    win.on("closed", () => {
      ipcMain.removeHandler("first-run:continue");
      ipcMain.removeHandler("first-run:workspace-hint");
      finish(false);
    });

    win.loadFile(path.join(__dirname, "first-run.html"));
  });
}

async function createWindow(port) {
  const { session } = require("electron");
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    if (permission === "media" || permission === "microphone" || permission === "audioCapture") {
      callback(true);
      return;
    }
    callback(false);
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => {
    return (
      permission === "media" ||
      permission === "microphone" ||
      permission === "audioCapture"
    );
  });

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: "Jarvis",
    backgroundColor: "#0a0f1a",
    autoHideMenuBar: false,
    show: shouldShowMainOnLaunch(),
    skipTaskbar: !shouldShowMainOnLaunch(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  currentPort = port;
  installAppMenu();
  ipcMain.removeHandler("jarvis:open-screen");
  ipcMain.handle("jarvis:open-screen", () => {
    openJarvisScreen();
    return { ok: true, title: JARVIS_SCREEN_TITLE, url: JARVIS_NOVNC_URL };
  });
  await mainWindow.loadURL(ceoUrl(port));
  if (jarvisMuted && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("jarvis:muted", buildMuteState({ muted: true }));
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("close", (e) => {
    if (!shouldHideMainOnClose({ shuttingDown })) return;
    e.preventDefault();
    hideMainWindow();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
    if (screenWindow && !screenWindow.isDestroyed()) screenWindow.close();
  });
  bindAvatarToMain();
  createTray();
  createAvatarWindow();
  syncAvatarVisibility();
}

function expandMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.setSkipTaskbar(false);
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  syncAvatarVisibility();
}

function hideMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.hide();
  mainWindow.setSkipTaskbar(true);
  if (screenWindow && !screenWindow.isDestroyed()) screenWindow.close();
  syncAvatarVisibility();
}

function avatarStatePath() {
  return path.join(app.getPath("userData"), "mini-avatar.json");
}

function readAvatarPosition(workArea) {
  const fallback = defaultPosition(workArea);
  try {
    const raw = JSON.parse(fs.readFileSync(avatarStatePath(), "utf8"));
    if (raw && raw.muted === true) jarvisMuted = true;
    if (!raw || typeof raw.x !== "number" || typeof raw.y !== "number") return fallback;
    return clampPosition(raw, workArea, AVATAR.size);
  } catch (_) {
    return fallback;
  }
}

function writeAvatarPosition() {
  persistAvatarState();
}

function currentWorkArea() {
  if (avatarWindow && !avatarWindow.isDestroyed()) {
    const bounds = avatarWindow.getBounds();
    return screen.getDisplayMatching(bounds).workArea;
  }
  return screen.getPrimaryDisplay().workArea;
}

function applyAvatarBounds() {
  if (!avatarWindow || avatarWindow.isDestroyed()) return;
  const current = avatarWindow.getBounds();
  const next = clampPosition(
    bubbleBounds(current, avatarBubbleOpen),
    currentWorkArea(),
    avatarBubbleOpen
      ? { width: AVATAR.bubbleWidth, height: AVATAR.bubbleHeight }
      : AVATAR.size
  );
  avatarWindow.setBounds({
    x: next.x,
    y: next.y,
    width: avatarBubbleOpen ? AVATAR.bubbleWidth : AVATAR.size,
    height: avatarBubbleOpen ? AVATAR.bubbleHeight : AVATAR.size,
  });
}

function setAvatarTyping(on) {
  if (!avatarWindow || avatarWindow.isDestroyed()) return { ok: false };
  // Keep the overlay clickable. focusable:false made expand/send/ask a ghost.
  avatarWindow.setFocusable(true);
  if (on) avatarWindow.focus();
  return { ok: true };
}

function sendAvatarTalk(partial) {
  if (!avatarWindow || avatarWindow.isDestroyed()) return;
  const next = buildTalkState({
    open: avatarBubbleOpen,
    status: partial && partial.status,
    you: partial && partial.you,
    reply: clipReply(partial && partial.reply),
    muted: jarvisMuted,
  });
  // Talk events never pop the bubble. Click (and typed ask) open it.
  next.open = avatarBubbleOpen;
  avatarWindow.webContents.send("avatar:talk", next);
}

function focusVoiceFromAvatar() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  // Hook for ORCH-398. Do not show or focus the main window.
  mainWindow.webContents.send("jarvis:focus-voice");
  sendAvatarTalk({ status: "listening" });
}

function askFromAvatar(text) {
  const asked = normalizeAsk(text);
  if (!asked) return { ok: false };
  if (!avatarBubbleOpen) {
    avatarBubbleOpen = true;
    applyAvatarBounds();
  }
  sendAvatarTalk({ status: "thinking", you: asked });
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false, text: asked };
  // Do not show or focus the main window.
  mainWindow.webContents.send("jarvis:avatar-ask", { text: asked });
  return { ok: true, text: asked };
}

function typeFocusFromAvatar() {
  // Typing needs the overlay. Do not show or focus the main window.
  return setAvatarTyping(true);
}

function typeBlurFromAvatar() {
  return setAvatarTyping(false);
}

function syncAvatarVisibility() {
  if (!avatarWindow || avatarWindow.isDestroyed()) return;
  const show = shouldShowAvatar({
    shuttingDown,
    mainExists: !!(mainWindow && !mainWindow.isDestroyed()),
    mainVisible: !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible()),
    mainMinimized: !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isMinimized()),
    mainFocused: !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isFocused()),
  });
  if (show) {
    if (!avatarWindow.isVisible()) avatarWindow.showInactive();
    avatarWindow.setAlwaysOnTop(true, AVATAR.alwaysOnTopLevel);
  } else if (avatarWindow.isVisible()) {
    avatarBubbleOpen = false;
    setAvatarTyping(false);
    applyAvatarBounds();
    if (!avatarWindow.isDestroyed()) {
      avatarWindow.webContents.send("avatar:bubble", { open: false });
    }
    avatarWindow.hide();
  }
}

function closeAvatarWindow() {
  if (!avatarWindow || avatarWindow.isDestroyed()) return;
  const win = avatarWindow;
  avatarWindow = null;
  avatarBubbleOpen = false;
  win.close();
}

function bindAvatarToMain() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  for (const ev of ["blur", "focus", "minimize", "restore", "hide", "show"]) {
    mainWindow.on(ev, syncAvatarVisibility);
  }
}

function createAvatarWindow() {
  if (avatarWindow && !avatarWindow.isDestroyed()) return avatarWindow;
  const workArea = screen.getPrimaryDisplay().workArea;
  const pos = readAvatarPosition(workArea);
  avatarBubbleOpen = shouldOpenBubbleOnLaunch();
  const launchBounds = bubbleBounds(
    { x: pos.x, y: pos.y, width: AVATAR.size, height: AVATAR.size },
    avatarBubbleOpen
  );
  avatarWindow = new BrowserWindow({
    ...avatarWindowOptions(launchBounds),
    webPreferences: {
      preload: path.join(__dirname, "avatar-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  avatarWindow.setAlwaysOnTop(true, AVATAR.alwaysOnTopLevel);
  avatarWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: false });
  avatarWindow.setSkipTaskbar(false);
  avatarWindow.setFocusable(true);
  avatarWindow.setIgnoreMouseEvents(false);
  avatarWindow.loadFile(path.join(__dirname, "avatar.html"));
  avatarWindow.webContents.once("did-finish-load", () => {
    avatarBubbleOpen = shouldOpenBubbleOnLaunch();
    applyAvatarBounds();
    if (!avatarWindow || avatarWindow.isDestroyed()) return;
    avatarWindow.webContents.send("avatar:bubble", { open: avatarBubbleOpen });
    avatarWindow.webContents.send("avatar:muted", buildMuteState({ muted: jarvisMuted }));
  });

  avatarWindow.on("closed", () => {
    avatarWindow = null;
    avatarBubbleOpen = false;
  });
  avatarWindow.on("close", (e) => {
    if (shuttingDown) return;
    const quit = shouldQuitOnAvatarClose({
      shuttingDown,
      mainVisible: !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible()),
      mainMinimized: !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isMinimized()),
    });
    if (quit || shouldQuitOnAvatarCloseButton()) {
      quitJarvis();
      return;
    }
    e.preventDefault();
    avatarWindow.hide();
  });
  avatarWindow.on("moved", writeAvatarPosition);

  ipcMain.removeHandler("avatar:move-by");
  ipcMain.removeHandler("avatar:clicked");
  ipcMain.removeHandler("avatar:expand");
  ipcMain.removeHandler("avatar:ask");
  ipcMain.removeHandler("avatar:health");
  ipcMain.removeHandler("avatar:type-focus");
  ipcMain.removeHandler("avatar:type-blur");
  ipcMain.removeHandler("avatar:quit");
  ipcMain.removeHandler("avatar:set-muted");
  ipcMain.removeHandler("jarvis:get-muted");
  ipcMain.removeAllListeners("jarvis:talk");
  ipcMain.handle("avatar:move-by", (_event, delta) => {
    if (!avatarWindow || avatarWindow.isDestroyed()) return { ok: false };
    const dx = Number(delta && delta.dx) || 0;
    const dy = Number(delta && delta.dy) || 0;
    const [x, y] = avatarWindow.getPosition();
    const [width, height] = avatarWindow.getSize();
    const next = clampPosition(
      { x: x + dx, y: y + dy },
      currentWorkArea(),
      { width, height }
    );
    avatarWindow.setPosition(next.x, next.y);
    writeAvatarPosition();
    return { ok: true, x: next.x, y: next.y };
  });
  ipcMain.handle("avatar:clicked", () => {
    if (!avatarWindow || avatarWindow.isDestroyed()) return { open: false };
    avatarBubbleOpen = !avatarBubbleOpen;
    if (!avatarBubbleOpen) setAvatarTyping(false);
    applyAvatarBounds();
    avatarWindow.webContents.send("avatar:bubble", { open: avatarBubbleOpen });
    if (avatarBubbleOpen) focusVoiceFromAvatar();
    return { open: avatarBubbleOpen };
  });
  ipcMain.handle("avatar:expand", () => {
    expandMainWindow();
    return { open: true };
  });
  ipcMain.handle("avatar:ask", (_event, payload) => {
    return askFromAvatar(payload && payload.text);
  });
  ipcMain.handle("avatar:health", () => fetchJarvisHealth());
  ipcMain.handle("avatar:type-focus", () => typeFocusFromAvatar());
  ipcMain.handle("avatar:type-blur", () => typeBlurFromAvatar());
  ipcMain.handle("avatar:quit", () => {
    if (shouldQuitOnAvatarCloseButton()) quitJarvis();
    return { ok: true, quit: true };
  });
  ipcMain.handle("avatar:set-muted", (_event, payload) => {
    return setJarvisMuted(!!(payload && payload.muted));
  });
  ipcMain.handle("jarvis:get-muted", () => buildMuteState({ muted: jarvisMuted }));
  ipcMain.on("jarvis:talk", (event, payload) => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (event.sender !== mainWindow.webContents) return;
    sendAvatarTalk(payload);
  });

  return avatarWindow;
}

function failAndQuit(message) {
  dialog.showErrorBox("Jarvis", message);
  stopBackend();
  app.quit();
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
      return;
    }
    syncAvatarVisibility();
  });

  app.whenReady().then(async () => {
    const root = repoRoot();
    if (!fs.existsSync(path.join(root, "app", "main.py"))) {
      failAndQuit(
        app.isPackaged
          ? "Jarvis files are missing. Try installing again."
          : "Could not find the agent-orchestrator repo (app/main.py).\nRun from a full clone, or set CONTROL_ROOM_ROOT."
      );
      return;
    }

    try {
      await ensureLocalEnv();
      // Packaged family path never asks for a key. Operator/hosted talk
      // is injected below when the backend starts.
      if (shouldShowFirstRunKeyWindow({ isPackaged: app.isPackaged })) {
        const saved = await showFirstRunWindow();
        if (!saved) {
          app.quit();
          return;
        }
      }
    } catch (err) {
      failAndQuit(
        "Could not prepare Jarvis settings.\n\n" +
          String(err && err.message ? err.message : err)
      );
      return;
    }

    const splash = showSplash();
    try {
      const { port, owned } = await startBackend(root);
      if (owned) await waitForHealth(port);
      else if (!(await probeHealth(port))) await waitForHealth(port);
      if (!splash.isDestroyed()) splash.close();
      await createWindow(port);
      startupComplete = true;
    } catch (err) {
      if (!splash.isDestroyed()) splash.close();
      const extra = app.isPackaged
        ? "Close Jarvis and open it again."
        : "Tip: run scripts\\windows\\start-control-room.ps1 -SetupOnly first.";
      failAndQuit(String(err && err.message ? err.message : err) + "\n\n" + extra);
    }
  });

  app.on("window-all-closed", () => {
    if (!startupComplete) return;
    stopBackend();
    app.quit();
  });

  app.on("before-quit", () => {
    shuttingDown = true;
    stopBackend();
  });
}
