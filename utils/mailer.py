"""
utils/mailer.py
----------------
Minimal SMTP sender, currently used only by the daily digest job.

Required env vars: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM.
SMTP_PORT defaults to 587 (STARTTLS) if not set. The recipient address
(digest_email_to) is an agent.settings field instead — seeded from
DIGEST_EMAIL_TO at startup, editable/persisted live via the Settings page
from there.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from agent.settings import settings


def send_email(subject: str, body: str) -> None:
    """
    Send a plain-text email via SMTP. This is a blocking call — call it
    from async code via `asyncio.to_thread`.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = settings.digest_email_to
    msg.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
