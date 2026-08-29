from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings

log = logging.getLogger("grok_automater.email")


def send_email(
    settings: Settings,
    *,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    to_addr = (to_addr or "").strip()
    if not to_addr:
        raise ValueError("notify email is empty")

    host = (settings.smtp_host or "").strip()
    if not host:
        raise RuntimeError("SMTP_HOST not configured")

    from_addr = (settings.smtp_from or settings.smtp_user or "grok-automater@localhost").strip()
    port = int(settings.smtp_port or 587)
    user = (settings.smtp_user or "").strip()
    password = (settings.smtp_password or "").strip()
    use_ssl = bool(settings.smtp_ssl)
    use_starttls = bool(settings.smtp_starttls) and not use_ssl

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            if use_starttls:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
                smtp.ehlo()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)

    log.info("email sent to %s subject=%s", to_addr, subject[:80])
