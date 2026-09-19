/**
 * Build the Next.js Windows shell if desktop-web/out is missing.
 * Electron npm start calls this so the primary window can load /desktop-ui.
 * Family no-key path is unchanged. Failure falls through to /desktop HTML.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const web = path.join(root, "desktop-web");
const out = path.join(web, "out", "index.html");

if (fs.existsSync(out)) {
  process.exit(0);
}

if (!fs.existsSync(path.join(web, "package.json"))) {
  console.warn("desktop-web is missing; Electron will load the HTML /desktop shell.");
  process.exit(0);
}

if (!fs.existsSync(path.join(web, "node_modules"))) {
  console.log("Installing desktop-web dependencies…");
  const install = spawnSync("npm", ["install"], {
    cwd: web,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (install.status !== 0) {
    console.warn("desktop-web npm install failed; falling back to HTML /desktop.");
    process.exit(0);
  }
}

console.log("Building Next desktop UI (desktop-web)…");
const built = spawnSync("npm", ["run", "export"], {
  cwd: web,
  stdio: "inherit",
  shell: process.platform === "win32",
});
if (built.status !== 0) {
  console.warn("Next export failed; Electron will load the HTML /desktop shell.");
}
process.exit(0);
