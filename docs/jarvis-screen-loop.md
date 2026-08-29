# Screen loop v1 (A4) ==GRoK== (ORCH-248 / ORCH-249)

## Flow

```
see (screenshot) → describe (vision) → propose (action text) → confirm hook
                                                              └─ act = NOT in v1 (L4)
```

## Tools / API

| Name | Path | Role |
|------|------|------|
| `screenshot` | tool | Capture PNG → `Exports/screenshots/` |
| `see_screen` | tool | screenshot + vision + `proposal` object |
| `confirm_screen_action` | tool | approve/deny proposal (no click yet) |
| `POST /api/jarvis/tools/run` | HTTP | Realtime client runs tools |

### Proposal shape

```json
{
  "proposal_id": "prop_…",
  "description": "Vision text…",
  "proposed_action": "Prepare UI steps toward: …",
  "risk_tier": "L4",
  "needs_confirm": true,
  "act_status": "not_implemented_v1",
  "user_prompt": "I see: … I propose: … Say confirm or cancel."
}
```

## Vision

- Env: `JARVIS_VISION_MODEL` (OpenRouter id, default `openai/gpt-4o-mini`)
- Fallback: `OPENAI_API_KEY` + `OPENAI_VISION_MODEL`
- Module: `app/jarvis/screen_loop.py` → `vision_describe_png` / `run_see_screen`

## Realtime

When `see_screen` returns a proposal, speak `user_prompt` and wait.
On confirm → `confirm_screen_action` (logs approval; does not click).
