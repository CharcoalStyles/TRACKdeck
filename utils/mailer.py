"""
utils/mailer.py
----------------
Minimal SMTP sender, currently used only by the daily digest job.

Required env vars: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM,
DIGEST_EMAIL_TO. SMTP_PORT defaults to 587 (STARTTLS) if not set.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def send_email(subject: str, body: str) -> None:
    """
    Send a plain-text email via SMTP. This is a blocking call — call it
    from async code via `asyncio.to_thread`.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = os.environ["DIGEST_EMAIL_TO"]
    msg.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
