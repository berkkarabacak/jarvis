# Slack Bot API setup (no Incoming Webhook)

App: **ai automater** (`A0BNVTEB63A`) · Workspace: **aiberk.slack.com** · Channel: **#all-ai-berk**

Agent Orchestrator posts with `chat.postMessage` using a **Bot User OAuth Token**.

## In the Slack app (api.slack.com/apps/A0BNVTEB63A)

1. **OAuth & Permissions**
   - Under **Bot Token Scopes** add:
     - `chat:write`
     - `chat:write.public` (optional; lets post to public channels without join)
   - Click **Install to Workspace** (or **Reinstall**)
   - Copy **Bot User OAuth Token** — starts with `xoxb-...`

2. **Invite the bot** into the channel (if you did not use `chat:write.public`):
   - In Slack: open `#all-ai-berk`
   - `/invite @ai automater`

3. You do **not** need Incoming Webhooks for this path.

## On the server

```bash
sudo nano /home/berkkarabacak/GrokAutomater/.env
```

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_CHANNEL=#all-ai-berk
SLACK_WORKSPACE=aiberk.slack.com
# leave empty if unused:
# SLACK_WEBHOOK_URL=
```

```bash
sudo systemctl restart grok-automater
```

## Verify

Dashboard → Notifications should show **Slack bot · #all-ai-berk**  
→ **Send test Slack**

## Do not put in git or chat if you can avoid it

- Bot token (`xoxb-...`)
- Client Secret / Signing Secret  

App ID / Client ID are less sensitive but still keep them out of public repos.
