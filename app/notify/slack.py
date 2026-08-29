from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.memory.sanitize import sanitize_text

log = logging.getLogger("grok_automater.slack")

_WEBHOOK_HOSTS = ("hooks.slack.com",)
SLACK_API = "https://slack.com/api"


def redact_secret(value: str | None, *, kind: str = "secret") -> str:
    raw = (value or "").strip()
    if not raw:
        return f"({kind}-empty)"
    if len(raw) <= 8:
        return f"({kind}-set)"
    return f"{raw[:4]}…{raw[-4:]}"


def redact_webhook_url(url: str | None) -> str:
    """Never expose the full webhook path/secret."""
    raw = (url or "").strip()
    if not raw:
        return "(empty)"
    try:
        p = urlparse(raw)
        host = p.hostname or "?"
        tail = (p.path or "")[-4:] if p.path else ""
        return f"{p.scheme or 'https'}://{host}/…{tail}"
    except Exception:
        return "(invalid-url)"


def redact_error_text(
    text: str | None,
    *,
    webhook_url: str | None = None,
    bot_token: str | None = None,
) -> str:
    s = sanitize_text(text or "", max_chars=500)
    if webhook_url:
        s = s.replace(webhook_url, redact_webhook_url(webhook_url))
    if bot_token:
        s = s.replace(bot_token, redact_secret(bot_token, kind="bot-token"))
    s = re.sub(
        r"https?://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+",
        "https://hooks.slack.com/services/…",
        s,
        flags=re.I,
    )
    s = re.sub(r"\bxoxb-[A-Za-z0-9\-]+\b", "xoxb-…", s)
    s = re.sub(r"\bxoxe\.[A-Za-z0-9\-_.]+\b", "xoxe-…", s)
    return s


def validate_webhook_url(url: str | None) -> tuple[bool, str]:
    raw = (url or "").strip()
    if not raw:
        return False, "Webhook URL is not set"
    try:
        p = urlparse(raw)
    except Exception:
        return False, "Webhook URL is not a valid URL"
    if p.scheme != "https":
        return False, "Webhook URL must use https"
    host = (p.hostname or "").lower()
    if host not in _WEBHOOK_HOSTS:
        return False, "Webhook URL host must be hooks.slack.com"
    if not (p.path or "").startswith("/services/"):
        return False, "Webhook URL path looks invalid"
    if len(p.path) < 20:
        return False, "Webhook URL path looks too short"
    return True, "ok"


def validate_bot_token(token: str | None) -> tuple[bool, str]:
    raw = (token or "").strip()
    if not raw:
        return False, "Bot token is not set"
    if not raw.startswith("xoxb-"):
        return False, "Bot token must start with xoxb-"
    if len(raw) < 20:
        return False, "Bot token looks too short"
    return True, "ok"


def slack_mode(settings: Settings) -> str:
    """Return 'bot' | 'webhook' | 'none'."""
    bot_ok, _ = validate_bot_token(getattr(settings, "slack_bot_token", None))
    if bot_ok and (getattr(settings, "slack_channel", None) or "").strip():
        return "bot"
    wh_ok, _ = validate_webhook_url(getattr(settings, "slack_webhook_url", None))
    if wh_ok:
        return "webhook"
    return "none"


@dataclass
class SlackSendResult:
    ok: bool
    status_code: int | None
    diagnostic: str  # never contains full secrets
    mode: str = "none"


async def post_slack_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 15.0,
) -> SlackSendResult:
    ok_url, reason = validate_webhook_url(webhook_url)
    if not ok_url:
        return SlackSendResult(ok=False, status_code=None, diagnostic=reason, mode="webhook")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, json=payload)
        body = (resp.text or "")[:200]
        if 200 <= resp.status_code < 300:
            return SlackSendResult(
                ok=True, status_code=resp.status_code, diagnostic="delivered", mode="webhook"
            )
        return SlackSendResult(
            ok=False,
            status_code=resp.status_code,
            diagnostic=redact_error_text(
                f"Slack HTTP {resp.status_code}: {body}", webhook_url=webhook_url
            ),
            mode="webhook",
        )
    except Exception as exc:
        return SlackSendResult(
            ok=False,
            status_code=None,
            diagnostic=redact_error_text(
                f"Slack delivery failed: {exc}", webhook_url=webhook_url
            ),
            mode="webhook",
        )


async def post_slack_chat(
    bot_token: str,
    channel: str,
    payload: dict[str, Any],
    *,
    timeout: float = 15.0,
) -> SlackSendResult:
    """Post via Slack Web API chat.postMessage (no Incoming Webhook)."""
    ok_tok, reason = validate_bot_token(bot_token)
    if not ok_tok:
        return SlackSendResult(ok=False, status_code=None, diagnostic=reason, mode="bot")
    ch = (channel or "").strip()
    if not ch:
        return SlackSendResult(
            ok=False, status_code=None, diagnostic="SLACK_CHANNEL is not set", mode="bot"
        )

    body = {
        "channel": ch,
        "text": payload.get("text") or "Agent Orchestrator notification",
        "blocks": payload.get("blocks"),
        "unfurl_links": False,
        "unfurl_media": False,
    }
    # drop None blocks
    if not body["blocks"]:
        body.pop("blocks", None)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{SLACK_API}/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
            )
        data: dict[str, Any]
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": (resp.text or "")[:200]}

        if resp.status_code >= 400:
            return SlackSendResult(
                ok=False,
                status_code=resp.status_code,
                diagnostic=redact_error_text(
                    f"Slack API HTTP {resp.status_code}: {data}",
                    bot_token=bot_token,
                ),
                mode="bot",
            )
        if data.get("ok") is True:
            return SlackSendResult(
                ok=True, status_code=resp.status_code, diagnostic="delivered", mode="bot"
            )
        err = str(data.get("error") or "unknown_error")
        # common install mistakes
        hint = ""
        if err in ("not_in_channel", "channel_not_found"):
            hint = " — invite the bot to the channel (/invite @ai automater)"
        elif err == "missing_scope":
            hint = " — add chat:write scope and reinstall the app"
        elif err == "invalid_auth":
            hint = " — check Bot User OAuth Token (xoxb-...)"
        return SlackSendResult(
            ok=False,
            status_code=resp.status_code,
            diagnostic=redact_error_text(
                f"Slack API error: {err}{hint}", bot_token=bot_token
            ),
            mode="bot",
        )
    except Exception as exc:
        return SlackSendResult(
            ok=False,
            status_code=None,
            diagnostic=redact_error_text(
                f"Slack API delivery failed: {exc}", bot_token=bot_token
            ),
            mode="bot",
        )


def build_run_slack_payload(
    *,
    job_name: str,
    status: str,
    run_id: str,
    started_at: float | None,
    result: str | None,
    error: str | None,
    history_url: str | None,
) -> dict[str, Any]:
    when = "—"
    if started_at:
        when = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    emoji = ":white_check_mark:" if status == "succeeded" else ":x:"
    if status == "failed":
        summary = sanitize_text(error or "failed", max_chars=280)
    else:
        summary = sanitize_text(result or "", max_chars=280)
        lines = [ln.strip() for ln in summary.splitlines() if ln.strip()]
        summary = " ".join(lines[:4])[:280] if lines else "(no summary)"

    text = f"{emoji} *Agent Orchestrator* · `{job_name}` · *{status}*"
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *{job_name}*\n"
                    f"Status: *{status}* · {when}\n"
                    f"Run: `{run_id[:8]}…`"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{summary}```"},
        },
    ]
    if history_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open history"},
                        "url": history_url,
                    }
                ],
            }
        )
    return {"text": text, "blocks": blocks}


async def send_slack_payload(settings: Settings, payload: dict[str, Any]) -> SlackSendResult:
    """Send via bot token (preferred) or incoming webhook."""
    mode = slack_mode(settings)
    if mode == "bot":
        return await post_slack_chat(
            (settings.slack_bot_token or "").strip(),
            (settings.slack_channel or "").strip(),
            payload,
        )
    if mode == "webhook":
        return await post_slack_webhook((settings.slack_webhook_url or "").strip(), payload)
    return SlackSendResult(
        ok=False,
        status_code=None,
        diagnostic=(
            "Slack not configured. Set SLACK_BOT_TOKEN (xoxb-...) + SLACK_CHANNEL "
            "(e.g. #all-ai-berk), or SLACK_WEBHOOK_URL."
        ),
        mode="none",
    )


async def notify_run_slack(
    settings: Settings,
    *,
    job_name: str,
    slack_on_success: bool,
    slack_on_failure: bool,
    run_status: str,
    run_id: str,
    started_at: float | None,
    result: str | None,
    error: str | None,
) -> SlackSendResult | None:
    """Send Slack if configured and job prefs match. Never raises."""
    if run_status == "succeeded" and not slack_on_success:
        return None
    if run_status == "failed" and not slack_on_failure:
        return None
    if run_status not in ("succeeded", "failed"):
        return None

    payload = build_run_slack_payload(
        job_name=job_name,
        status=run_status,
        run_id=run_id,
        started_at=started_at,
        result=result,
        error=error,
        history_url=(settings.public_base_url or "").rstrip("/") + "/history"
        if settings.public_base_url
        else None,
    )
    result_send = await send_slack_payload(settings, payload)
    if not result_send.ok:
        log.warning("slack notify failed: %s", result_send.diagnostic)
    return result_send
