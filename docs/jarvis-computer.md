# Jarvis's Linux computer (ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410 / ORCH-461)

Give Jarvis his own cheap Linux desktop that stays up and **looks like Windows**.
The user can open that same desktop in a browser and use it.
When a job is for **his** machine, Jarvis looks, clicks, and types there.
Parent epic: [ORCH-395](https://berk-claude.atlassian.net/browse/ORCH-395).

## Product rules

- **Linux, not Windows**, so cost stays low. Familiar Windows-like UI on top.
- **One computer for Jarvis**, not one per sub-agent. Children work through him on this same machine (ORCH-405). They do not spawn extra containers.
- **Files, apps, and logins persist** across jobs and container restarts.
- This is **Jarvis's machine**. The user's Windows/Android app is a different computer ([ORCH-381](https://berk-claude.atlassian.net/browse/ORCH-381)). See-and-click on the user's Windows PC ([ORCH-365](https://berk-claude.atlassian.net/browse/ORCH-365)) still uses the Windows tools.
- Do **not** ship a raw Linux desktop as v1. Theme the existing image; do not replace it with a Windows VM.
- The browser view is **that same computer** (Xvfb :1 / XFCE), not a recording and not a second machine.

## What landed

A checked-in Compose + Dockerfile under `deploy/jarvis-computer/`:

- Debian + Xvfb + a small XFCE session (a real desktop Jarvis can drive).
- One service, fixed container name `jarvis-computer`.
- Named volume `jarvis-computer-home` → `/home/jarvis`.
- `restart: unless-stopped`.
- **ORCH-402:** Windows-like XFCE theme pack (`deploy/jarvis-computer/theme/`) — bottom taskbar, Start-menu button, navy/silver window chrome, desktop icons, teal wallpaper. Applied on first start.
- **ORCH-403:** Basic apps in the image so Jarvis can open them without installing first:
  - Chrome — Debian `chromium` (no Google Chrome repo) plus a `chrome` wrapper
  - Notepad — `mousepad`
  - Files — `thunar`
  - Terminal — `xfce4-terminal`
  - Calculator — `galculator`
  - Image Viewer — `ristretto`
  - Desktop shortcuts and Start-menu `.desktop` entries (`deploy/jarvis-computer/apps/`)
- **ORCH-404:** Live noVNC of **this** desktop. `x11vnc` attaches to `DISPLAY=:1`; websockify serves noVNC on container port 6080. Compose publishes **localhost only**: `127.0.0.1:6080`. Open [http://127.0.0.1:6080](http://127.0.0.1:6080) to watch and use the same XFCE session (type, click, open apps).
- **ORCH-405:** Desktop tools route to this container when the job is for Jarvis's computer. `see_screen` / `screenshot` grab `DISPLAY=:1` via `docker exec` + `scrot`. `click` / `type` / `keys` / `scroll` / `focus_app` use `xdotool` inside the same container. `run_app` launches Chrome/notepad/utilities that already ship in the image. Children inherit that backend. The Windows path is unchanged.
- **ORCH-406:** Live notepad proof script `scripts/proof_jarvis_computer_notepad.py`. It uses those helpers (`computer=jarvis-computer` / `JARVIS_DESKTOP_BACKEND=jarvis-computer`), opens notepad (mousepad) on the existing container, types a unique string (date + ORCH-406), reads the characters back from the mousepad file, and saves a real `DISPLAY=:1` screenshot only if scrot returns a PNG. It refuses to invent a screen when the container is down.
- **ORCH-410:** On-demand viewer. Click **Open Jarvis's screen** in the Jarvis Windows app menu or the CEO gear menu. A window titled **Jarvis's screen** shows the same live noVNC session (http://127.0.0.1:6080). If the computer is off, the window says so in plain English and offers **Start Jarvis's computer**. Start prefers `docker compose up -d`. If compose is not a command, it uses `docker start jarvis-computer`, or `docker run` of `jarvis-computer:local` with the same localhost:6080 and `jarvis-computer-home` flags. No second desktop. No fake screenshot. Still localhost only.

The entrypoint seeds the shortcuts onto the desktop. It does **not** launch the apps.

No custom orchestration platform. No GPU. No Windows VM. No Kasm/webtop.

## Start / stop

```bash
cd deploy/jarvis-computer
docker compose up -d --build
docker compose stop
docker compose start
docker compose down          # keeps the named volume
```

Then click **Open Jarvis's screen** in the Jarvis app or CEO page, or open
**http://127.0.0.1:6080** in a browser. That URL is the live desktop
(noVNC). It is bound to localhost on purpose — do not publish `0.0.0.0` unless
you also document the bind as local-only.

## Open Jarvis's screen (ORCH-410)

You do not have to remember the port.

1. In the Windows app: Jarvis menu → **Open Jarvis's screen**.
2. In the CEO page: gear menu → **Open Jarvis's screen**.

Either one opens a viewer window captioned **Jarvis's screen**. It embeds the
existing 6080 session of this computer. If the desktop is not running, the
viewer says **Jarvis's computer is not running.** and you can start the one
existing computer from that window (`docker compose up -d`, or `docker start`
/ `docker run` when this machine has no compose plugin).

`docker compose down -v` deletes `jarvis-computer-home` and wipes the machine's home. Do not do that if you want persistence.

Shell on the same machine (tools already exec here; this is for debugging):

```bash
docker compose exec jarvis-computer bash
```

## How Jarvis drives it (ORCH-405)

Routing lives in `app/jarvis/computer.py`:

| Signal | Backend |
|--------|---------|
| `computer=jarvis` / `computer=jarvis-computer` / `computer=linux` | jarvis-computer |
| `computer=android` / `computer=jarvis-android` | jarvis-android |
| Settings `computer_kind=android` (Jarvis's own box) | jarvis-android |
| `computer=windows` / `computer=user` / `computer=pc` | windows (ORCH-365) |
| `JARVIS_DESKTOP_BACKEND=jarvis-computer` | jarvis-computer |
| Goal text like "on your computer" / "Jarvis's Linux desktop" | jarvis-computer |
| Goal text like "on my PC" / "my Windows screen" | windows |
| Child of a jarvis-computer job | same machine (inherited) |
| Default | windows (user PC see-and-click keeps working) |

Helpers only `docker exec` into the existing `jarvis-computer` container with `DISPLAY=:1`. They do not `docker run` or `docker compose up`. They do not publish extra ports. The ORCH-406 proof script uses the same helpers.

## Persistence

| What | Where |
|------|--------|
| Home / workspace | Docker volume `jarvis-computer-home` at `/home/jarvis` |
| Desktop / Documents / Downloads | Seeded on first start inside that volume |
| Windows-like XFCE settings | Same home (`.config/xfce4/…`, marker `.jarvis-windows-theme-ready`) |
| App settings and browser profiles | Same home (`.config`, Chromium profile under `/home/jarvis`) |
| Desktop shortcuts | Seeded once (`.jarvis-apps-ready`) |

Rebuilding the image does not delete the volume. Stopping or `down` without `-v` does not delete it.

## Live notepad proof (ORCH-406)

After the one container is up:

```bash
cd deploy/jarvis-computer && docker compose up -d --build
python scripts/proof_jarvis_computer_notepad.py
```

The script does **not** start a second computer. If `jarvis-computer` is not running it exits and **refuses to invent a screenshot**. Open [http://127.0.0.1:6080](http://127.0.0.1:6080) to see the same notepad.

## Android as a second box (ORCH-461)

Linux stays the default. Berk can pick **Android** in Settings. Same
Jarvis, same memory, different computer.

- Setting: `computer_kind` = `linux` (default) or `android`.
- Android backend: `app/jarvis/android_computer.py` + `deploy/jarvis-android/`.
- Tools `docker exec` into `jarvis-android` (`screencap` / `input` / `am`).
  They never exec into `jarvis-computer`.
- Watch: localhost [http://127.0.0.1:6081](http://127.0.0.1:6081), proxied as
  `/jarvis/android/`. Same Talk iframe as Linux noVNC.
- This is **not** the Play Store phone app in `android/` (ORCH-382).

```bash
cd deploy/jarvis-android
docker compose up -d
```

Then Settings → Computer → Android.

## Later tickets

Computer size/class spend work stays on [ORCH-459](https://berk-claude.atlassian.net/browse/ORCH-459).
This slice only adds the linux | android kind swap.

## Tests (cheap; no live VM required)

```bash
pytest -q tests/test_jarvis_computer_contract.py tests/test_jarvis_computer_drive.py tests/test_jarvis_computer_notepad_proof.py tests/test_jarvis_screen_viewer.py tests/test_jarvis_android_computer.py
./scripts/smoke_jarvis_computer.sh
./scripts/smoke_jarvis_android.sh
```

The smoke script checks that the files exist, describe one persistent Linux computer, include the Windows-like theme pack, require the shipped desktop apps, require a localhost noVNC remote view, require the ORCH-405 routing helpers, require the ORCH-406 proof script (exists; refuses to invent a screen), and require the ORCH-410 on-demand viewer (control, title, 6080, no public bind). If `docker compose` is installed it also runs `docker compose config`. It does not start a GPU host or a cloud VM. A live notepad pass still needs the running container.

## Why this shape

A small Linux desktop image plus a named volume plus an XFCE theme pack plus Debian desktop packages plus x11vnc/noVNC on localhost plus an on-demand **Open Jarvis's screen** window plus docker-exec / xdotool helpers is enough.
A Windows VM, a webtop/Kasm stack, Google Chrome's extra apt repo, or a per-agent fleet would be more expensive and would mix later tickets into this one.
