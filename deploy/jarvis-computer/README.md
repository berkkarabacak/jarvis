# Jarvis's Linux computer (ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410)

One cheap persistent Linux desktop container. This is **Jarvis's** machine.

It is **not** the user's Windows or Android app (ORCH-381).
It is **not** one computer per sub-agent.

Linux underneath, Windows-like on top: taskbar, Start menu, window chrome, icons.
The OS is still **Linux, not Windows** — no Windows VM.

**ORCH-403 landed:** Chrome (Debian Chromium), Notepad (mousepad), Files (thunar),
Terminal, Calculator, and Image Viewer ship in the image with desktop / Start-menu
shortcuts. Jarvis can open them without installing anything first.

**ORCH-404 landed:** live noVNC of **this** XFCE desktop (same `DISPLAY=:1`, not a
recording). Open **http://127.0.0.1:6080** after compose is up. Published on
localhost only.

**ORCH-405 landed:** when a job is for Jarvis's computer, `see_screen` / click /
type / keys / `run_app` / `focus_app` talk to this container (`docker exec`,
`DISPLAY=:1`, xdotool/scrot). Children inherit that same machine. See-and-click
on the user's Windows PC (ORCH-365) is unchanged.

**ORCH-406 landed:** `scripts/proof_jarvis_computer_notepad.py` opens notepad
(mousepad) on this container, types a unique string (date + ORCH-406), reads
the text back from the saved file, and writes a real `DISPLAY=:1` screenshot
only if scrot returns a PNG. It refuses to invent a screen when the desktop
is down.

**ORCH-410 landed:** click **Open Jarvis's screen** in the Jarvis Windows app
or the CEO gear menu. A window titled **Jarvis's screen** shows this same
localhost noVNC session. If the computer is off, the viewer says so and can
start this one computer (`docker compose up -d`, or `docker start` /
`docker run` of `jarvis-computer:local` when compose is not a command).
No second desktop. No fake screenshot.

Product docs: [docs/jarvis-computer.md](../../docs/jarvis-computer.md).

## Start / stop

From this directory:

```bash
docker compose up -d --build   # start (creates volume on first run)
docker compose stop            # stop; keep the container and volume
docker compose start           # start the same container again
docker compose down            # remove the container; **keep** the named volume
```

Then click **Open Jarvis's screen** (Jarvis menu or CEO gear), or open
**http://127.0.0.1:6080** to see and use the desktop (type, click, open
apps). Compose binds `127.0.0.1:6080` — local-only, not `0.0.0.0`.

Do **not** use `docker compose down -v` if you want files and logins to survive.

Shell on the machine (tools already exec here):

```bash
docker compose exec jarvis-computer bash
```

## Persistence

Named volume `jarvis-computer-home` mounts at `/home/jarvis`.
Files, app settings, and browser logins in that home survive restarts.

The Windows-like XFCE theme (`theme/`, installed as `JarvisWin`) is applied on first
start of this image. An existing volume from ORCH-401 gets the theme once
(`.jarvis-windows-theme-ready`) without wiping files.

Desktop shortcuts are seeded once (`.jarvis-apps-ready`). The entrypoint does not
launch Chrome or Notepad.

## Live notepad proof (ORCH-406)

From the repo root, after this container is up:

```bash
python ../../scripts/proof_jarvis_computer_notepad.py
```

Or from the repo root: `python scripts/proof_jarvis_computer_notepad.py`.
Watch the same desktop at **http://127.0.0.1:6080**.

## Chrome search-result click (hosted news)

The Xvfb desktop is **1280×720** (`JARVIS_SCREEN` in `entrypoint.sh`). Chrome
fills that desktop; the XFCE panel is at the bottom (~40px). Cheap vision on
DuckDuckGo often describes the search chrome and omits `click_x` / result
URLs. Hosted news still clicks through at a documented first-result point in
the Chromium content column:

| Attempt | Point | Why |
|---------|-------|-----|
| 1 | `(420, 320)` | First organic result title, below the DDG search box and All/Images chips (header + box occupy roughly y=110–280; Chromium chrome occupies y=0–110). |
| 2 | `(420, 400)` | One result row lower if the look is still DuckDuckGo. |

Those points are a fallback, not a guarantee. Chromium **Restore pages?** often
blocks the top of the window, and DuckDuckGo news cards often do not navigate
away. A click that returns ok is **not** navigation. After every click,
`see_screen` again. If title/url/vision is still a SERP (DuckDuckGo, Google,
Bing, “results”, the query), the click missed.

Leave the SERP by:

1. Clicking a real result headline/link (not ads, not “What? Go ahead.”, not
   the search box around y≤280).
2. If still a SERP, `run_app` chrome to a real article URL from the look
   (`nzz.ch`, swissinfo, bbc, reuters, cnn, ntv). Prefer that over another
   search. If the look named no URL, open a known publisher — never invent a
   country host (`switzerland.com`).

Do not stay clicking the same DuckDuckGo pixels. Do not treat news-card
headlines as the article. A SERP is not done.

## Later tickets

None remaining in this computer stack.

## Smoke

```bash
../../scripts/smoke_jarvis_computer.sh
```

Validates the compose definition, the Windows-like theme files, the ORCH-403
apps, that ORCH-404 remote-view (localhost noVNC) is present, that ORCH-405
routing helpers exist, that the ORCH-406 proof script exists and refuses
to invent a screen, and that the ORCH-410 on-demand viewer control exists.
Does not need a GPU or a cloud VM.
