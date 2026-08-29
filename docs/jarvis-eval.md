# Jarvis eval harness ==GRoK== (ORCH-258)

Scenarios that **must** route to real tools (never invented answers).

| ID | User goal | Required tool |
|----|-----------|---------------|
| free_space | How much free disk space… | `get_disk_space` |
| list_desktop | List files on my Desktop | `home_list` |
| memory_recall | What do you remember… | `recall_memories` |
| excel | Create a spreadsheet… | `create_excel` (agent path) |
| screen | What’s on my screen… | `see_screen` |

## Run

```bash
# from repo root with venv
python -m pytest tests/test_jarvis_eval_a4_d3.py tests/test_jarvis_gateway_bridge.py -q
```

Live E2E (optional, needs server + keys):

```bash
curl -s http://127.0.0.1:8787/api/jarvis/health
# Realtime path: open /ceo and ask "how much free space"
```
