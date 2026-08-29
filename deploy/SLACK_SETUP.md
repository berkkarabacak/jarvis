# Slack Incoming Webhooks — setup for Grok Automater

The app never creates Slack resources for you. Do these steps once, then put the webhook URL only on the server.

## 1. Create (or pick) a Slack channel

In your workspace, create a channel such as `#grok-automater` (or use an existing ops channel).

## 2. Create an Incoming Webhook

1. Open [https://api.slack.com/apps](https://api.slack.com/apps)
2. **Create New App** → **From scratch**
3. Name it (e.g. `Grok Automater`) and select your workspace
4. In the app settings: **Incoming Webhooks** → turn **On**
5. **Add New Webhook to Workspace**
6. Choose the channel → **Allow**
7. Copy the webhook URL  
   It looks like:  
   `https://hooks.slack.com/services/T…/B…/…`

Treat this URL like a password.

## 3. Add the webhook on the server (securely)

SSH to the VM and edit the app env file only (never commit this):

```bash
sudo nano /home/berkkarabacak/GrokAutomater/.env
```

Add or update:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SECRET/PATH
PUBLIC_BASE_URL=https://berkkarabacak.com/grok-automater
```

Restart:

```bash
sudo systemctl restart grok-automater
```

Confirm the process is up:

```bash
systemctl is-active grok-automater
```

## 4. Verify in the dashboard

1. Open https://berkkarabacak.com/grok-automater/dashboard  
2. Unlock with your API secret  
3. Under **Settings · notifications** you should see **Slack configured**  
4. Click **Send test Slack**  
5. Confirm the test message in your channel  

The dashboard **never shows** the webhook URL.

## 5. Per-task alerts

When editing a scheduled task:

- **On failure** (default on) — Slack when a run fails  
- **On success** (default off) — Slack when a run succeeds  
- Check both for every run  

Email (`notify_email` + SMTP) continues to work independently.

## Security checklist

- [ ] Webhook only in server `.env` (mode `600`)
- [ ] Not in git, screenshots, tickets, or task memory
- [ ] Rotate the webhook in Slack if it ever leaks (Incoming Webhooks → revoke / re-create)
