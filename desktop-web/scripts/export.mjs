import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"

const cwd = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const env = {
  ...process.env,
  JARVIS_DESKTOP_EXPORT: "1",
  NEXT_PUBLIC_BASE_PATH: "/desktop-ui",
}
const result = spawnSync("npx", ["next", "build"], {
  cwd,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
})
process.exit(result.status ?? 1)
