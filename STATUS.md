# Grok Automater — live status

Updated automatically after bootstrap.

## Done on this machine

| Step | Status |
|------|--------|
| `.env` with secrets | Done |
| Server on `http://127.0.0.1:8787` | Running |
| OAuth tokens imported (from OpenCode auth) | Healthy |
| Job `daily-briefing` created | Done |
| First Grok run | **Succeeded** |

## IDs

- **Job ID:** `b77b5fc9-1c52-46df-8145-b1873adb70c3` (also in `data/job_id.txt`)
- **First run:** succeeded (grok-4.3)

## Commands

```powershell
cd C:\Users\XPS13\Desktop\gROKAUTOMATER
.\.venv\Scripts\activate

# status
curl http://127.0.0.1:8787/api/status -H "X-Api-Key: <from .env API_SECRET>"

# run today's job
.\scripts\run_daily.ps1
```

## Not done (needs your GCP access)

No `gcloud` CLI and no SSH host config for your GCP VM on this machine.

When you have VM access:

1. Copy project to VM (`/opt/grok-automater`)
2. Copy `.env` securely (scp) — never commit it
3. Install systemd unit from `deploy/grok-automater.service`
4. Reverse-proxy HTTPS
5. Re-import tokens (or copy encrypted sqlite DB + same `TOKEN_ENCRYPTION_KEY`)
6. Cloud Scheduler → `POST /api/jobs/b77b5fc9-1c52-46df-8145-b1873adb70c3/run` + `X-Api-Key`

## Security

- `.env` and tokens are local only (gitignored)
- Rotate the Atlassian API token you pasted in chat earlier
