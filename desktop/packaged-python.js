/**
 * Packaged Windows Jarvis: backend + embeddable CPython layout helpers.
 *
 * Installed tree (electron-builder extraResources):
 *   %LOCALAPPDATA%\\Jarvis\\resources\\python\\python.exe
 *   %LOCALAPPDATA%\\Jarvis\\resources\\backend\\app\\
 *
 * Embeddable CPython reads python*._pth and isolates the interpreter:
 * PYTHONPATH and cwd are ignored. First-run must not rely on
 * ``-m app.first_run_env`` unless ../backend is on that ._pth.
 */
const path = require("path");

const EMBEDDABLE_BACKEND_PTH = "../backend";

function packagedBackendRoot(resourcesPath) {
  return path.join(resourcesPath, "backend");
}

function bundledPythonExes(resourcesPath) {
  const pyDir = path.join(resourcesPath, "python");
  return [path.join(pyDir, "python.exe"), path.join(pyDir, "python3.exe")];
}

function firstRunScriptPath(root) {
  return path.join(root, "app", "first_run_env.py");
}

function firstRunArgv(root, extraArgs) {
  return [firstRunScriptPath(root), ...(extraArgs || [])];
}

function uvicornArgv(port) {
  return [
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
    "--proxy-headers",
    "--forwarded-allow-ips=127.0.0.1",
  ];
}

function pythonChildEnv(root, extra) {
  return {
    ...(extra || {}),
    PYTHONPATH: root,
    PYTHONIOENCODING: "utf-8",
    PYTHONUNBUFFERED: "1",
  };
}

function backendOnSysPath(root) {
  return path.join(root, "app", "main.py");
}

module.exports = {
  EMBEDDABLE_BACKEND_PTH,
  packagedBackendRoot,
  bundledPythonExes,
  firstRunScriptPath,
  firstRunArgv,
  uvicornArgv,
  pythonChildEnv,
  backendOnSysPath,
};
