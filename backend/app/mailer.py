"""Sending email from the admin's own account over SMTP (e.g. Gmail with an App Password)."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .config import get_settings


class MailError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and (s.smtp_from or s.smtp_username))


def sender() -> str | None:
    s = get_settings()
    return (s.smtp_from or s.smtp_username) or None


def _send_sync(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.smtp_from_name, sender()))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    try:
        if s.smtp_ssl:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            server.starttls(context=ctx)
        with server:
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError("The email server refused the login. For Gmail, use an App Password, not your normal password.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Couldn't send the email: {e}") from e


async def send(to: str, subject: str, body: str) -> None:
    if not configured():
        raise MailError("Email sending isn't set up on the server")
    await asyncio.to_thread(_send_sync, to, subject, body)
