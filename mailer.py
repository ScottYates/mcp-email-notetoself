"""SMTP sending for email.notetoself.

Thin wrapper around `smtplib` that owns the subject/body formatting rules and
returns a small structured result the MCP tool handler can surface back to
the LLM.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SUBJECT_PREFIX = "NTS:"
SUBJECT_PREVIEW_CHARS = 20
MAX_BODY_CHARS = 5000


@dataclass(frozen=True)
class SendResult:
    subject: str
    to: str


def build_subject(note: str) -> str:
    """`NTS:` + first 20 chars of the note. Exactly as specified."""
    preview = note[:SUBJECT_PREVIEW_CHARS]
    return f"{SUBJECT_PREFIX}{preview}"


def validate_note(note: str) -> None:
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if not note.strip():
        raise ValueError("note must not be empty")
    if len(note) > MAX_BODY_CHARS:
        raise ValueError(
            f"note is {len(note)} chars; max is {MAX_BODY_CHARS}"
        )


def send_note(
    note: str,
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    to_email: str,
) -> SendResult:
    """Send `note` via SMTP. Raises on any failure."""
    validate_note(note)

    subject = build_subject(note)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.set_content(note)

    logger.info(
        "sending note: subject=%r to=%s body_chars=%d",
        subject,
        to_email,
        len(note),
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

    return SendResult(subject=subject, to=to_email)
