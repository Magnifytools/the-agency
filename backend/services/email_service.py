from __future__ import annotations
import asyncio
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Optional

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: str = "",
    attachment_bytes: Optional[bytes] = None,
    attachment_name: str = "adjunto.pdf",
) -> bool:
    """Send an email via SMTP. Returns True on success, False on failure."""
    from backend.config import settings

    if not all([settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_FROM]):
        logger.warning("SMTP not configured — email not sent")
        return False

    def _send():
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
        msg["To"] = to

        # Body (HTML + text fallback)
        alt = MIMEMultipart("alternative")
        if body_text:
            alt.attach(MIMEText(body_text, "plain", "utf-8"))
        alt.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(alt)

        # Attachment
        if attachment_bytes:
            part = MIMEApplication(attachment_bytes, Name=attachment_name)
            part["Content-Disposition"] = f'attachment; filename="{attachment_name}"'
            msg.attach(part)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to], msg.as_bytes())

    try:
        await asyncio.get_event_loop().run_in_executor(None, _send)
        return True
    except Exception as e:
        logger.error(f"Error sending email to {to}: {e}")
        return False
