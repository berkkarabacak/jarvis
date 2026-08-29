# Jarvis — local AI colleague ==GRoK==

Jarvis is the **local Windows** personality of AI Control Room: voice-first, tool-using, with multi-week memory.

## What it can do

| Capability | How |
|------------|-----|
| Talk (voice) | CEO UI + STT/TTS |
| Create Excel | `create_excel` tool |
| Write scripts | `write_file` under `Scripts/` |
| Organize docs | `organize_folder` on `Inbox` |
| Run commands | `run_powershell` (workspace cwd) |
| Open apps/files | `open_path` |
| See the screen | `screenshot` + vision model |
| Remember you | SQLite facts + turn history in `Memory/` |

## Workspace (sandbox)

Default: `%USERPROFILE%\Documents\Jarvis`

Jarvis **cannot** freely wipe your whole PC; tools are rooted in this folder. Put work for Jarvis under `Inbox` / `Documents`.

## Jarvis's own Linux computer (ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410 / ORCH-461)

Separate from this Windows workspace. Jarvis gets **one** cheap persistent
Linux desktop (`deploy/jarvis-computer/`) with a Windows-like XFCE look
(taskbar, Start, window chrome). Chrome, notepad, and basic utilities ship
in the image. Files live on named volume `jarvis-computer-home`. Click
**Open Jarvis's screen** in the Windows app or CEO page to watch the same
desktop (http://127.0.0.1:6080, localhost noVNC). When a job is for
his machine, look / click / type / `run_app` talk to that container
(ORCH-405). Children share it. `scripts/proof_jarvis_computer_notepad.py`
is the live "open notepad and write X" proof (ORCH-406); it refuses to
invent a screenshot if the container is down. See-and-click on the user's
Windows PC (ORCH-365) still uses the Windows tools. The user's
Windows/Android app is a different computer (ORCH-381). See
[jarvis-computer.md](jarvis-computer.md).
Settings can also pick **Android** as his computer (ORCH-461): same
Jarvis, same memory, a phone-shaped box (`deploy/jarvis-android/`).
That is not the Play Store phone app. Default stays Linux.

## Enable

```env
JARVIS_ENABLED=true
EXECUTIVE_PRIME_ADAPTER=jarvis
OPENROUTER_API_KEY=sk-or-v1-...
JARVIS_MODEL=openai/gpt-4.1-mini
# Optional: hard-pin (router skipped). Or set model in Settings UI.
# JARVIS_MODEL_PIN=true
# JARVIS_MODEL_PREFERENCE=cheap_fast|fast|balanced|quality
# Prefer Settings → How Jarvis thinks (fast | balanced | smart).
# Monthly/daily spend caps also live in Memory/jarvis_settings.json.
# Approve wait (seconds) is Settings → Approve wait. Default 10.
# JARVIS_APPROVE_COUNTDOWN_SEC=10
```

### Model router (ORCH-328 / ORCH-362 / ORCH-380)

Jarvis does **not** always stick to a single fixed model. Settings →
**How Jarvis thinks** (Fast / Balanced / Smart) is the user-facing control;
it is stored as `quality_vs_price` in `Memory/jarvis_settings.json`
(`config_version` 2) and read by GET/PUT `/api/jarvis/settings`. Windows
keeps `model_preference` / `model_speed` aliases in that same file — not
a second store. Look-speed stays a separate control. Spend lives in the
same JSON (`spend`), not `jarvis_spend.json`.

The OpenRouter weekly board is a **catalog** of current models — not
“always pick #1 by tokens” and not “always pick free.” Fast prefers a
cheaper/quicker catalog model. Balanced is a real middle path (not the
cheapest tip, not usage-rank #1). Smart may cost more (high-IQ paid
catalog). Hard / high-IQ jobs still pick a smarter paid catalog model
first when the user has not chosen Fast/Balanced/Smart (legacy
ORCH-363). Spend caps in the same settings file stop the job or switch
to a cheaper model when hit.

Live fetch + snapshot fallback stay; slugs must exist in `/api/v1/models`.
See [docs/jarvis-index.md](jarvis-index.md). An explicit Settings model
lock / `JARVIS_MODEL_PIN` / bridge `context.model` still wins — unless
the spend cap is already exhausted, in which case Jarvis stops.


Cloud public hosts should keep `JARVIS_ENABLED=false`.

## Run

**Easy:** install `Jarvis-Setup.exe` from `scripts\windows\build-installer.ps1`.
Double-click, paste the OpenRouter key, Jarvis opens. See [windows-installer.md](windows-installer.md).

**Advanced:** `RUN-JARVIS.bat` (needs Python on PATH), or the portable zip from
`scripts\windows\build-portable.ps1` → `dist\Jarvis-Windows-Portable-GRoK.zip`.

## Wake word

Say **“Jarvis …”** then the request. Also works without the wake word once listening.
