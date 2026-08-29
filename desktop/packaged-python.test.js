/**
 * Node assertions for desktop/packaged-python.js (installed first-run paths).
 * Run: node desktop/packaged-python.test.js
 */
const assert = require("assert");
const path = require("path");
const {
  EMBEDDABLE_BACKEND_PTH,
  packagedBackendRoot,
  bundledPythonExes,
  firstRunScriptPath,
  firstRunArgv,
  uvicornArgv,
  pythonChildEnv,
  backendOnSysPath,
} = require("./packaged-python");

const resources = path.join("C:", "Users", "XPS13", "AppData", "Local", "Jarvis", "resources");
const backend = packagedBackendRoot(resources);

assert.strictEqual(EMBEDDABLE_BACKEND_PTH, "../backend");
assert.strictEqual(backend, path.join(resources, "backend"));
assert.strictEqual(backendOnSysPath(backend), path.join(backend, "app", "main.py"));

const py = bundledPythonExes(resources);
assert.strictEqual(py[0], path.join(resources, "python", "python.exe"));
assert.strictEqual(py[1], path.join(resources, "python", "python3.exe"));
assert.ok(!py[0].includes("backend"), "bundled python lives next to backend, not inside it");

const script = firstRunScriptPath(backend);
assert.strictEqual(script, path.join(backend, "app", "first_run_env.py"));

const argv = firstRunArgv(backend, ["ensure", "--env", "X", "--force-local"]);
assert.strictEqual(argv[0], script);
assert.deepStrictEqual(argv.slice(1), ["ensure", "--env", "X", "--force-local"]);
assert.ok(!argv.includes("-m"), "first-run must not use -m app.* (embeddable Python ignores PYTHONPATH)");
assert.ok(!argv.includes("app.first_run_env"));

const uv = uvicornArgv(8787);
assert.deepStrictEqual(uv.slice(0, 3), ["-m", "uvicorn", "app.main:app"]);
assert.ok(
  uv.includes("app.main:app"),
  "backend still starts with -m; ../backend on python*._pth must make app importable"
);

const env = pythonChildEnv(backend, { FOO: "1", PYTHONPATH: "stale" });
assert.strictEqual(env.FOO, "1");
assert.strictEqual(env.PYTHONPATH, backend);
assert.strictEqual(env.PYTHONIOENCODING, "utf-8");
assert.strictEqual(env.PYTHONUNBUFFERED, "1");

console.log("packaged-python helpers ok");
