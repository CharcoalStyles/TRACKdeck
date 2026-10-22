"""
utils/mailer.py
----------------
Minimal SMTP sender for the morning/evening/weekly/monthly messages, sent in
addition to the Gotify push (jobs/common.py's deliver).

Required env vars: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM.
SMTP_PORT defaults to 587 (STARTTLS). The recipient is the email_to setting
(agent/settings.py), editable live from the Settings page; blank = no email.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from agent.settings import settings

_REQUIRED_ENV = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")


def email_wanted() -> bool:
    return bool(settings.email_to.strip())


def missing_smtp_env() -> list[str]:
    return [name for name in _REQUIRED_ENV if not os.environ.get(name)]


def send_email(subject: str, body: str) -> None:
    """
    Send a plain-text email via SMTP. This is a blocking call — call it
    from async code via `asyncio.to_thread`.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = settings.email_to.strip()
    msg.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
