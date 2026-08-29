#!/usr/bin/env bash
#
# One-command deploy of AI Control Room to aicontrolroom.nl.
#
# Run ON the VM, as the login user (berkkarabacak), with sudo available:
#
#   export OPENROUTER_API_KEY='sk-or-v1-...'
#   curl -fsSL https://raw.githubusercontent.com/berkkarabacak/agent-orchestrator/dev/deploy/bootstrap.sh | bash
#
# or, if the repo is already cloned:  sudo -v && bash deploy/bootstrap.sh
#
# Idempotent: safe to re-run to pick up a new commit. Re-running never
# regenerates API_SECRET and never overwrites an existing .env.
#
# Contains no secrets. OPENROUTER_API_KEY is read from the environment (or
# prompted for interactively) and written only to /opt/ai-control-room/.env.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ai-control-room}"
BRANCH="${BRANCH:-dev}"
REPO="${REPO:-https://github.com/berkkarabacak/agent-orchestrator}"
DOMAIN="${DOMAIN:-aicontrolroom.nl}"
# Extra hostnames this deployment should also answer for, space separated.
# They must already resolve to this VM or certbot's HTTP-01 challenge fails.
#   EXTRA_DOMAINS="dev.aicontrolroom.nl" bash deploy/bootstrap.sh
EXTRA_DOMAINS="${EXTRA_DOMAINS:-}"
# nginx site filename under sites-available. Must match the host's existing
# convention (this VM uses `aicontrolroom` and `dev.aicontrolroom`, not
# `<domain>.conf`) or two vhosts end up claiming the same server_name and
# nginx picks one unpredictably.
SITE_NAME="${SITE_NAME:-$DOMAIN}"
# Which vhost in deploy/ to install. Defaults to the per-domain file.
VHOST_SRC="${VHOST_SRC:-deploy/nginx-$DOMAIN.conf}"
PORT="${PORT:-8896}"
SERVICE="${SERVICE_NAME:-ai-control-room}"
RUN_CERTBOT="${RUN_CERTBOT:-1}"

# certbot -d flags. Request www. only for an apex (two labels): asking for
# www.dev.aicontrolroom.nl would fail the whole certbot run, since that name
# does not exist. Override with WITH_WWW=0/1.
if [ "$(printf '%s' "$DOMAIN" | tr -cd '.' | wc -c)" -eq 1 ]; then
  WITH_WWW="${WITH_WWW:-1}"
else
  WITH_WWW="${WITH_WWW:-0}"
fi
CERT_ARGS=(-d "$DOMAIN")
[ "$WITH_WWW" = "1" ] && CERT_ARGS+=(-d "www.$DOMAIN")
for _d in $EXTRA_DOMAINS; do CERT_ARGS+=(-d "$_d"); done

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run as the login user, not root. sudo is used per-step."
command -v git >/dev/null    || die "git is not installed"
command -v python3 >/dev/null || die "python3 is not installed"
sudo -n true 2>/dev/null || sudo -v || die "sudo is required"

# ---------------------------------------------------------------- secrets ---
if [ -f "$APP_DIR/.env" ]; then
  log "Existing $APP_DIR/.env found — leaving it untouched"
  KEEP_ENV=1
else
  KEEP_ENV=0
  if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    if [ -t 0 ]; then
      read -rsp "OPENROUTER_API_KEY: " OPENROUTER_API_KEY; echo
    else
      die "OPENROUTER_API_KEY is not set and stdin is not a TTY.
     Re-run as:  export OPENROUTER_API_KEY='sk-or-v1-...'; bash deploy/bootstrap.sh"
    fi
  fi
  [ -n "$OPENROUTER_API_KEY" ] || die "OPENROUTER_API_KEY is empty"
fi

# ------------------------------------------------------------ nginx backup ---
BACKUP="/root/nginx-backup-$(date +%F-%H%M%S)"
log "Backing up nginx config to $BACKUP (rollback insurance)"
sudo cp -a /etc/nginx/sites-available "$BACKUP" 2>/dev/null \
  || warn "no /etc/nginx/sites-available to back up"

log "Ports currently in use (the prod app must keep running):"
sudo ss -ltnp 2>/dev/null | grep -E ':(889[5-9])' || echo "  (none of 8895-8899 in use)"
if sudo ss -ltnp 2>/dev/null | grep -qE "127\.0\.0\.1:$PORT\b" \
   && ! sudo systemctl is-active --quiet "$SERVICE"; then
  die "port $PORT is already served by another process — refusing to collide.
     Set PORT= to a free port (prod is on 8897)."
fi

# ------------------------------------------------------------------- code ---
if [ -d "$APP_DIR/.git" ]; then
  log "Updating $APP_DIR to origin/$BRANCH"
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
  log "Cloning $REPO ($BRANCH) into $APP_DIR"
  sudo mkdir -p "$APP_DIR"
  sudo chown "$USER":"$USER" "$APP_DIR"
  git clone -b "$BRANCH" "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p data
echo "    commit: $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"

log "Installing Python dependencies"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

# -------------------------------------------------------------------- env ---
if [ "$KEEP_ENV" -eq 0 ]; then
  log "Writing $APP_DIR/.env"
  # API_SECRET gates the ADMIN API and is the HMAC key for guest-IP
  # pseudonymisation. Under 32 bytes the public chat gateway refuses to start
  # and every chat turn 503s, so this is generated, never guessed.
  API_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  TOKEN_KEY="$(./.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  umask 077
  cat > .env <<ENVEOF
LLM_PROVIDER=openrouter
LLM_MODEL_MODE=auto
DEFAULT_MODEL=openrouter/auto
LLM_TIMEOUT_SECONDS=600
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}

API_SECRET=${API_SECRET}
TOKEN_ENCRYPTION_KEY=${TOKEN_KEY}

HOST=127.0.0.1
PORT=${PORT}
TZ=UTC
PUBLIC_BASE_URL=https://${DOMAIN}

DATABASE_PROVIDER=sqlite
DATABASE_PATH=${APP_DIR}/data/control_room.db
DATABASE_STRICT=false

HERDR_ENABLED=false
ENVEOF
  chmod 600 .env
fi

# ----------------------------------------------------------------- systemd ---
log "Installing $SERVICE.service"
sudo cp deploy/ai-control-room.service "/etc/systemd/system/$SERVICE.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null
sudo systemctl restart "$SERVICE"

log "Waiting for the app on 127.0.0.1:$PORT"
for _ in $(seq 1 40); do
  sleep 1
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "    up"; break
  fi
done
curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" \
  || { sudo journalctl -u "$SERVICE" -n 40 --no-pager; die "app did not become healthy"; }
echo

# Surface the two failure modes that look like a provider outage but are config.
if sudo journalctl -u "$SERVICE" -n 200 --no-pager | grep -q 'public executive gateway DISABLED'; then
  warn "API_SECRET is too weak — public chat will 503. Fix .env and restart."
fi
ADAPTER="$(sudo journalctl -u "$SERVICE" -n 200 --no-pager \
  | grep -o 'executive runtime adapter: .*' | tail -1 || true)"
echo "    ${ADAPTER:-executive runtime adapter: (not logged)}"
case "$ADAPTER" in
  *null*) warn "No live LLM adapter — check OPENROUTER_API_KEY in .env" ;;
esac

# ------------------------------------------------------------------- nginx ---
log "Installing nginx vhost for $DOMAIN as site '$SITE_NAME'"
[ -f "$VHOST_SRC" ] || die "vhost source not found: $VHOST_SRC"
if [ -f "/etc/nginx/sites-available/$SITE_NAME" ]; then
  # May be replacing a static-root site. Keep the original beside it.
  sudo cp -a "/etc/nginx/sites-available/$SITE_NAME" \
    "/etc/nginx/sites-available/$SITE_NAME.pre-controlroom.$(date +%F-%H%M%S)"
  echo "    existing site backed up alongside it"
fi
sudo cp "$VHOST_SRC" "/etc/nginx/sites-available/$SITE_NAME"
if [ -n "$EXTRA_DOMAINS" ]; then
  log "Adding to server_name: $EXTRA_DOMAINS"
  # Both the :443 block AND the :80 block need the extra names — the :80 block
  # is what serves certbot's HTTP-01 challenge, and without a matching
  # server_name the challenge falls through to whatever the default server is.
  # Dots are escaped so the domain is matched literally, not as a wildcard.
  _esc="$(printf '%s' "$DOMAIN" | sed 's/\./\\./g')"
  sudo sed -i -E \
    "s/^( *server_name +)(${_esc}( +www\\.${_esc})?) *;/\\1\\2 ${EXTRA_DOMAINS};/" \
    "/etc/nginx/sites-available/$SITE_NAME"
  echo "    $(grep -c "$EXTRA_DOMAINS" "/etc/nginx/sites-available/$SITE_NAME" 2>/dev/null || echo 0) server_name line(s) updated"
fi
sudo ln -sf "/etc/nginx/sites-available/$SITE_NAME" "/etc/nginx/sites-enabled/$SITE_NAME"

if sudo nginx -t 2>/dev/null; then
  sudo systemctl reload nginx
else
  # Almost always the missing certificate on a first run: the vhost references
  # /etc/letsencrypt/live/$DOMAIN/ before certbot has issued anything.
  warn "nginx -t failed — trying certbot first, then re-testing"
  if [ "$RUN_CERTBOT" = "1" ] && command -v certbot >/dev/null; then
    sudo certbot --nginx "${CERT_ARGS[@]}" --non-interactive --agree-tos \
      --register-unsafely-without-email --keep-until-expiring || true
  fi
  sudo nginx -t || { sudo nginx -t; die "nginx config invalid — see output above; rollback: $BACKUP"; }
  sudo systemctl reload nginx
fi

if [ "$RUN_CERTBOT" = "1" ] && command -v certbot >/dev/null; then
  log "Ensuring TLS certificate"
  sudo certbot --nginx "${CERT_ARGS[@]}" --non-interactive --agree-tos \
    --register-unsafely-without-email --keep-until-expiring || warn "certbot did not complete"
  sudo nginx -t && sudo systemctl reload nginx
fi

# ------------------------------------------------------------------- smoke ---
log "Smoke test: the real first-time-visitor path"
ORIGIN="https://$DOMAIN"
H=(-H "X-AI-Control-Room-Request: browser-v1" -H "Origin: $ORIGIN")
JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT

printf '  health   '; curl -sS -o /dev/null -w '%{http_code}\n' --max-time 20 "$ORIGIN/health"
printf '  /ceo     '; curl -sS -o /dev/null -w '%{http_code}\n' --max-time 20 "$ORIGIN/ceo"
printf '  session  '; curl -sS -o /dev/null -w '%{http_code}\n' --max-time 30 \
  -X POST "$ORIGIN/api/public/session" "${H[@]}" -c "$JAR"

SID="$(curl -sS --max-time 60 -X POST "$ORIGIN/api/public/executive/missions" "${H[@]}" \
  -b "$JAR" -c "$JAR" -H 'Content-Type: application/json' \
  -d '{"brief":"Say hello in one short sentence."}' \
  | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id",""))
except Exception: print("")')"

if [ -z "$SID" ]; then
  warn "could not open a mission — chat is NOT working yet"
  echo "     journalctl -u $SERVICE -n 60 --no-pager"
  exit 1
fi

echo "  mission  $SID"
printf '  AI turn  '
curl -sS --max-time 180 -X POST "$ORIGIN/api/public/executive/sessions/$SID/messages" \
  "${H[@]}" -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"message":"Say hello in one short sentence."}' \
  | python3 -c 'import sys,json
d = json.load(sys.stdin)
text = (d.get("message") or {}).get("text", "")
meter = d.get("metering") or {}
cost = meter.get("actual_cost_usd", "?")
toks = meter.get("total_tokens", "?")
# Values are pulled out first: an f-string expression cannot contain a
# backslash before Python 3.12, and this host may be older.
print(f"OK - {text[:70]!r} (cost ${cost}, {toks} tokens)" if text
      else f"NO TEXT RETURNED: {str(d)[:120]}")'

log "Done. https://$DOMAIN is live."
echo "  rollback:  sudo systemctl stop $SERVICE && sudo rm -f /etc/nginx/sites-enabled/$SITE_NAME"
echo "             sudo cp -a $BACKUP/* /etc/nginx/sites-available/ && sudo systemctl reload nginx"
echo "  logs:      journalctl -u $SERVICE -f"
