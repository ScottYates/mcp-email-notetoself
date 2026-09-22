"""Configuration loading for notetoself.

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


def _parse_tokens(raw: str) -> list[str]:
    """Parse TOKENS_JSON into a list of bearer tokens. Fails loudly on bad JSON."""
    if not raw or not raw.strip():
        print(
            "error: TOKENS_JSON is empty. At least one bearer token is required",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: TOKENS_JSON is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, list) or not data:
        print(
            "error: TOKENS_JSON must be a non-empty JSON array of token strings",
            file=sys.stderr,
        )
        sys.exit(2)
    for i, val in enumerate(data):
        if not isinstance(val, str) or not val:
            print(
                f"error: TOKENS_JSON[{i}] must be a non-empty string token",
                file=sys.stderr,
            )
            sys.exit(2)
    return data


def _parse_allowed_hosts(raw: str) -> list[str]:
    """Parse ALLOWED_HOSTS into a list. Comma-separated, whitespace stripped."""
    if not raw or not raw.strip():
        print(
            "error: ALLOWED_HOSTS is empty. List at least one host (e.g. 'localhost' "
            "or a public domain like 'yatesframe.com') so the MCP transport "
            "security layer can validate the Host header.",
            file=sys.stderr,
        )
        sys.exit(2)
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    if not hosts:
        print("error: ALLOWED_HOSTS contains no non-empty entries", file=sys.stderr)
        sys.exit(2)
    return hosts


# Hostnames that should be paired with http:// (rather than https://) when
# building the default allowed_origins list. Anything else gets https://.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


def _build_allowed_origins(hosts: list[str]) -> list[str]:
    """Pair each host with a sensible Origin header scheme."""
    origins: list[str] = []
    for h in hosts:
        scheme = "http" if h in _LOOPBACK_HOSTS else "https"
        origins.append(f"{scheme}://{h}")
    return origins


@dataclass(frozen=True)
class Config:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    to_email: str
    host: str
    port: int
    tokens: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)


def load_config() -> Config:
    """Load and validate configuration. Exits the process on error."""
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3001"))

    allowed_hosts = _parse_allowed_hosts(
        os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]")
    )

    return Config(
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=smtp_port,
        smtp_user=_required("SMTP_USER"),
        smtp_pass=_required("SMTP_PASS"),
        to_email=os.getenv("TO_EMAIL") or os.getenv("SMTP_USER") or _required("TO_EMAIL"),
        host=host,
        port=port,
        tokens=_parse_tokens(os.getenv("TOKENS_JSON", "")),
        allowed_hosts=allowed_hosts,
        allowed_origins=_build_allowed_origins(allowed_hosts),
    )
