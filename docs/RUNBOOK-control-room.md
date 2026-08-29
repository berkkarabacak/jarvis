# Runbook — AI Control Room (aicontrolroom.nl)

Free, no-login AI chat. A visitor opens the site and talks to the executive
immediately: no account, no unlock wall, no API secret in the browser.

## What runs where

| Piece | Value |
|---|---|
| Branch | `dev` |
| Host | GCP VM `instance-20240716-221941` (`us-central1-a`) |
| App dir | `/opt/ai-control-room` |
| Service | `ai-control-room.service` (uvicorn, `127.0.0.1:8896`) |
| Env file | `/opt/ai-control-room/.env` (chmod 600) — **the only place secrets live** |
| Reverse proxy | nginx vhost `aicontrolroom.nl`, TLS via certbot |
| Database | SQLite at `/opt/ai-control-room/data/control_room.db` |
| LLM | OpenRouter, `openrouter/auto` |

## Before you start: this replaces a live site

`aicontrolroom.nl` (146.148.38.150) is **already serving an older build** — the
gated ORCH-72 shell at commit `1038b38`, which still shows an API-secret unlock
wall. Cutting over to `dev` replaces it. Two consequences:

- Whatever nginx vhost currently answers for `aicontrolroom.nl` will be
  displaced. **Back it up before overwriting** — the commands below do.
- The same VM also serves `berkkarabacak.com/agent-orchestrator/` from a
  path-prefixed fragment on port 8895. That is a *separate* app and vhost and
  must be left alone; the new service uses port 8896 so the two can coexist.

Capture the current state first, so rollback is a single command:

```bash
sudo cp -a /etc/nginx/sites-available /root/nginx-backup-$(date +%F-%H%M)
systemctl list-units --type=service | grep -iE 'orchestr|control-room|grok'
sudo ss -ltnp | grep -E ':(8895|8896)'
```

### Rollback

```bash
sudo systemctl stop ai-control-room
sudo rm -f /etc/nginx/sites-enabled/aicontrolroom.nl
# restore whatever previously answered for the host
sudo cp -a /root/nginx-backup-<stamp>/<previous-vhost> /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/<previous-vhost> /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

The old app's data is untouched by this deployment — the new service uses its
own directory and its own SQLite file — so rollback loses nothing.

## First install

```bash
gcloud compute ssh berkkarabacak@instance-20240716-221941 \
  --zone=us-central1-a --tunnel-through-iap

sudo mkdir -p /opt/ai-control-room && sudo chown "$USER":"$USER" /opt/ai-control-room
git clone -b dev https://github.com/berkkarabacak/agent-orchestrator /opt/ai-control-room
cd /opt/ai-control-room
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p data

# Secrets: copy the template, then paste the real values into the copy.
cp deploy/control-room.env.example .env
chmod 600 .env
$EDITOR .env      # set OPENROUTER_API_KEY, API_SECRET, TOKEN_ENCRYPTION_KEY

sudo cp deploy/ai-control-room.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-control-room

sudo cp deploy/nginx-aicontrolroom.nl.conf \
  /etc/nginx/sites-available/aicontrolroom.nl
sudo ln -sf /etc/nginx/sites-available/aicontrolroom.nl \
  /etc/nginx/sites-enabled/aicontrolroom.nl
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d aicontrolroom.nl -d www.aicontrolroom.nl
```

DNS: `aicontrolroom.nl` must have an A record pointing at the VM's external
IP before certbot will issue.

## Restart / deploy an update

```bash
cd /opt/ai-control-room
git fetch origin dev && git reset --hard origin/dev
.venv/bin/pip install -r requirements.txt
sudo systemctl restart ai-control-room
systemctl status ai-control-room --no-pager
```

Logs: `journalctl -u ai-control-room -f`

## Verify chat works

Health and the shell:

```bash
curl -s https://aicontrolroom.nl/health
curl -s -o /dev/null -w '%{http_code}\n' https://aicontrolroom.nl/ceo      # 200
curl -s -o /dev/null -w '%{http_code}\n' https://aicontrolroom.nl/         # 200 Talk
curl -s -o /dev/null -w '%{http_code}\n' https://aicontrolroom.nl/jarvis/  # 301 → /
```

A full guest turn — this is the real user path, no credential anywhere:

```bash
JAR=$(mktemp)
ORIGIN='https://aicontrolroom.nl'
H=(-H "X-AI-Control-Room-Request: browser-v1" -H "Origin: $ORIGIN")

curl -s -X POST "$ORIGIN/api/public/session" "${H[@]}" -c "$JAR"

SID=$(curl -s -X POST "$ORIGIN/api/public/executive/missions" "${H[@]}" \
  -b "$JAR" -c "$JAR" -H 'Content-Type: application/json' \
  -d '{"brief":"Say hello in one sentence."}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')

curl -s -X POST "$ORIGIN/api/public/executive/sessions/$SID/messages" "${H[@]}" \
  -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"message":"Say hello in one sentence."}'
```

A healthy response contains `message.text`, plus a `metering` block with
`telemetry_complete: true` and a `quota` block showing the turn counted.

Which executive adapter is live:

```bash
journalctl -u ai-control-room | grep 'executive runtime adapter'
```

Expect `openrouter (in-process)`. `null` means `OPENROUTER_API_KEY` is missing
from `.env` — chat will fail with "Prime RPC is unavailable" until it is set.

## Troubleshooting

**403 `Browser mutation rejected` on every `POST /api/public/*`**
nginx is not forwarding `X-Forwarded-Proto` / `X-Forwarded-Host`. The app
rebuilds the expected `Origin` from those. Check the vhost still has all three
`proxy_set_header` lines and reload nginx.

**Guest sessions refused after ~20 visitors/hour**
`X-Real-IP` is not reaching the app, so every visitor hashes into one quota
bucket. Same fix as above — the header is required, not decorative.

**Chat returns 503 "Prime RPC is unavailable"**
No usable executive adapter. Either `OPENROUTER_API_KEY` is unset, or
`EXECUTIVE_PRIME_ADAPTER=null` is pinned in `.env`.

**Every public chat request 503s but the page still loads fine**
`API_SECRET` is shorter than 32 bytes, or is a placeholder such as `public`,
`change-me`, `dev-secret-change-me` or `test-secret`. The public executive
gateway refuses to start below that threshold, so the whole chat surface is
dead while the shell keeps rendering — it looks like a provider outage but is
not. Confirm with:

```bash
journalctl -u ai-control-room | grep 'public executive gateway DISABLED'
```

Fix by putting a real secret in `.env` and restarting:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do **not** set `API_SECRET=public` to "make it free" — that value is below the
threshold and disables the very feature it appears to enable. Public chat needs
no credential; it is open regardless of what this value is.

**Chat returns a turn with `passed: false` / `requires_fresh_mission: true`**
The bounded cost gate tripped (per-turn ceiling $0.10 hard / $0.03 target,
12k tokens). The session is closed deliberately; the visitor starts a new one.

## Cost and abuse posture

Public chat spends real money. What limits it today:

- Per turn: target $0.03, hard $0.10, max 12k tokens, max 600 output tokens
  per generation, provider price ceilings of $1/M prompt and $5/M completion.
- Per guest account: 8 turns/hour, 24/day.
- Global across all visitors: 60 turns/hour, 240/day, 8 concurrent sessions.

Worst case at the global ceiling is roughly $6/hour and $24/day. Those limits
are the only thing between the public internet and the provider bill.

**The OpenRouter key currently has no spend cap of its own** (`limit: null`).
Set a credit limit on the key in the OpenRouter dashboard so a bug in the app
limits cannot drain the account. Rotate the key if it has ever been pasted into
a chat, an issue, or a commit.

## Security boundary

Open to the public, by design:
`/`, `/ceo`, `/health`, `/api/public/**`.

Still gated by `API_SECRET`, and deliberately so:
`/api/jobs/**` (can drive the Herdr runner, which executes local commands),
`/api/settings/**`, `/api/memories/**`, `/api/control-plane/**`,
`/api/executive/**` (the non-public variant), `/oauth/import`,
plus `/dashboard` and `/history` data.

Do not set `API_SECRET` to a guessable value to "make things easier". It is the
admin credential *and* the HMAC key that pseudonymises guest IPs for the rate
limiter — a weak value hands an attacker both the admin API and a quota bypass.
