"""Configuration loading for email.notetoself.

Reads from environment variables (and optionally a `.env` file via
`python-dotenv`). Validates required values at startup so a misconfigured
deployment fails loudly instead of silently dropping notes.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    pass


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"error: environment variable {name!r} is required", file=sys.stderr)
        sys.exit(2)
    return value


def _parse_clients(raw: str) -> dict[str, str]:
    """Parse CLIENTS_JSON into a dict. Fails loudly on bad JSON."""
    if not raw or not raw.strip():
        print(
            "error: CLIENTS_JSON is empty — at least one client_id/token pair "
            "is required",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: CLIENTS_JSON is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict) or not data:
        print(
            "error: CLIENTS_JSON must be a non-empty object mapping "
            "client_id -> token",
            file=sys.stderr,
        )
        sys.exit(2)
    for key, val in data.items():
        if not isinstance(key, str) or not isinstance(val, str) or not val:
            print(
                f"error: CLIENTS_JSON entry {key!r} must map to a non-empty string token",
                file=sys.stderr,
            )
            sys.exit(2)
    return data


@dataclass(frozen=True)
class Config:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    to_email: str
    host: str
    port: int
    clients: dict[str, str] = field(default_factory=dict)


def load_config() -> Config:
    """Load and validate configuration. Exits the process on error."""
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "3001"))

    return Config(
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=smtp_port,
        smtp_user=_required("SMTP_USER"),
        smtp_pass=_required("SMTP_PASS"),
        to_email=os.getenv("TO_EMAIL") or os.getenv("SMTP_USER") or _required("TO_EMAIL"),
        host=host,
        port=port,
        clients=_parse_clients(os.getenv("CLIENTS_JSON", "")),
    )
