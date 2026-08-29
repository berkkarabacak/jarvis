# Handover

For the next coding agent. No keys. Work here; do not clone unless Berk asks.

## Product

Jarvis is an **agent runtime**, not an orchestrator.
Public Talk: https://berkkarabacak.com/jarvis/

## Git

- Repo: github.com/berkkarabacak/jarvis
- Work on `dev`. The site pulls `dev` live.
- Do not clone unless Berk asks.
- PR squash-merge to `dev`.

## Voice

- OpenAI Realtime (`gpt-realtime`) when the host has `OPENAI_API_KEY`.
- Listen is always-on. **Mute me** is the only stop.
- First hello must be live Realtime audio (PR 181). Not a TTS/robot clip.
- Helpers: Kimi, then Ox / OpenRouter.
- Never put keys in HTML or chat.

## Computer

- Look, then click / type / close. Do not describe the screen instead of acting.
- Close-all must kill leftover apps.
- Local HTML opens as `file://`, not a hostname.

## Children

- Use OpenRouter `spawn_child` for create-N / games / helpers without the user saying `spawn_child`.
- Hello and math stay local.
- No force-hire.
- Spawn in waves if the cap is 4.

## Berk

- Simple English. No error dumps to him.
- Mom-simple UX.
- Talk worldwide: locale first, then mirror speech.
- Company: berkly.

## Recent live SHAs

- `1e77840` first hello Realtime (PR 181)
- `64f619a` marin clips (rejected)
- `dc1bfd2` cached hello (rejected as robot)
- `d5d4d34` first-hello + distinct tetris
- `5e58348` hire without magic words
- `39fbfc5` file:// tetris waves

## Known gaps

- Page-open to first Realtime hello still takes seconds.
- Hired games must look distinct and sellable.
- Desktop still slow vs 10 clicks/sec.
- `/ask` is 400 chars except hire.

## Host

Live service has `KIMI_CODE_API_KEY` + OpenRouter + OpenAI. Site agent deploys. Do not print keys.
