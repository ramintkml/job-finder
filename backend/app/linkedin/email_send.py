"""Send LinkedIn application emails via Gmail SMTP (App Password)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from app.config import ROOT_DIR
from app.linkedin.cv import resolve_cv_path
from app.linkedin.settings import LinkedInSettings

logger = logging.getLogger(__name__)

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587


def gmail_configured(cfg: LinkedInSettings) -> bool:
    return bool(cfg.gmail_address.strip() and cfg.gmail_app_password.strip())


def smtp_configured(cfg: LinkedInSettings) -> bool:
    return gmail_configured(cfg)


def _sender(cfg: LinkedInSettings) -> str:
    return (cfg.gmail_address or cfg.from_email).strip()


def test_connection(gmail_address: str, app_password: str) -> tuple[bool, str]:
    """Verify Gmail SMTP login (same as clinic-mailer_2)."""
    sender = gmail_address.strip()
    pwd = app_password.strip().replace(" ", "")
    if not sender or not pwd:
        return False, "Enter your Gmail address and 16-character App Password."

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(GMAIL_HOST, GMAIL_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender, pwd)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Authentication failed — check your Gmail address and 16-char App Password "
            "(not your normal Gmail password)."
        )
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return False, f"Connection error: {exc}"


def _build_message(
    cfg: LinkedInSettings,
    *,
    to_email: str,
    subject: str,
    body: str,
    cv_path: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    sender = _sender(cfg)
    msg["Subject"] = subject
    msg["From"] = f"{cfg.from_name} <{sender}>" if cfg.from_name.strip() else sender
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)

    if cv_path:
        path = Path(cv_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if path.is_file():
            data = path.read_bytes()
            maintype, subtype = ("application", "octet-stream")
            if path.suffix.lower() == ".pdf":
                maintype, subtype = ("application", "pdf")
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

    return msg


def send_email(
    cfg: LinkedInSettings,
    *,
    to_email: str,
    subject: str,
    body: str,
    cv_path: str | None = None,
) -> None:
    if not gmail_configured(cfg):
        raise ValueError(
            "Gmail not configured — set your Gmail address and App Password in Settings → LinkedIn"
        )

    attachment = cv_path
    if not attachment:
        resolved = resolve_cv_path(cfg)
        attachment = str(resolved) if resolved else None

    msg = _build_message(
        cfg,
        to_email=to_email,
        subject=subject,
        body=body,
        cv_path=attachment,
    )
    sender = _sender(cfg)
    pwd = cfg.gmail_app_password.strip().replace(" ", "")
    context = ssl.create_default_context()

    try:
        with smtplib.SMTP(GMAIL_HOST, GMAIL_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender, pwd)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise ValueError(
            "Gmail authentication failed — check your App Password (16 chars, not your login password)."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise ValueError(f"Recipient refused: {exc.recipients}") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise ValueError(f"Sender refused: {exc}") from exc
    except smtplib.SMTPDataError as exc:
        raise ValueError(f"Gmail rejected the message (possible limit/spam filter): {exc}") from exc
    except smtplib.SMTPException as exc:
        raise ValueError(f"SMTP error: {exc}") from exc
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(f"Connection error: {exc}") from exc

    logger.info("Sent Gmail message to %s — %s", to_email, subject)


def send_test_email(cfg: LinkedInSettings) -> str:
    to_addr = cfg.notification_email.strip() or _sender(cfg)
    if not to_addr:
        raise ValueError("Set a notification / fallback email or Gmail address first")
    send_email(
        cfg,
        to_email=to_addr,
        subject="LinkedIn automation — Gmail test",
        body="This is a test email from your Freelancer automation LinkedIn module.",
    )
    return to_addr
