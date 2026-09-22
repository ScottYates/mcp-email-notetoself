"""notetoself: an MCP server that emails you a note to yourself.

Server name: `notetoself`
Tool: `send_note`. Sends `message` as an email to `TO_EMAIL`.

Subject: ``NTS:<first 20 chars of the note>``
Body:    the full message, exactly as received.

Transport: legacy SSE. Clients `GET /mcp` to open the event stream; the
server tells the client (via the `endpoint` SSE event) the URL for
posting messages back, which is `/mcp/posts` by default.

Authorization: every request to the MCP endpoints must carry an
`Authorization: Bearer <token>` header whose value matches one of the
entries in the `TOKENS_JSON` environment variable.

Run: see README.md.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from auth import BearerAuthMiddleware
from config import load_config
from mailer import MAX_BODY_CHARS, send_note
from mcp.server.transport_security import TransportSecuritySettings

SERVER_NAME = "notetoself"

# Where the SSE stream lives and where clients POST messages back. The
# server announces the post URL to clients via the SSE `endpoint` event,
# so changing these only requires updating Claude Desktop (or any other
# SSE client) to point at the new stream URL.
SSE_PATH = "/mcp"
SSE_MESSAGE_PATH = "/mcp/posts/"


# Logging on stderr: stdout can collide with stdio MCP transports if anyone
# ever wires this up via stdio, and you want logs visible either way.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(SERVER_NAME)


def build_mcp_server() -> MCPServer:
    """Create the MCP server with the single `send_note` tool registered."""
    mcp = MCPServer(SERVER_NAME)

    @mcp.tool(
        name="send_note",
        description=(
            "Email a short note to yourself. Subject becomes "
            "'NTS:' + the first 20 characters of the note; the body is the "
            "full message. Use this when the user asks to 'note this', "
            "'email me this', or 'send myself a reminder'."
        ),
    )
    def send_note_tool(message: str) -> str:
        cfg = load_config()
        try:
            result = send_note(
                message,
                smtp_host=cfg.smtp_host,
                smtp_port=cfg.smtp_port,
                smtp_user=cfg.smtp_user,
                smtp_pass=cfg.smtp_pass,
                to_email=cfg.to_email,
            )
        except ValueError as exc:
            # Validation errors -> user-fixable. Return a clean message so the
            # LLM can correct and retry rather than seeing a stack trace.
            return f"error: {exc}"
        except Exception as exc:  # pragma: no cover - real SMTP failures
            logger.exception("failed to send note")
            return f"error: failed to send email: {exc}"
        return f"sent: subject={result.subject!r} to={result.to}"

    # Health check. Bypasses auth so you can `curl /health` without a token.
    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_NAME})

    return mcp


def build_app() -> Starlette:
    """Wire the MCP server + auth middleware into a Starlette ASGI app."""
    cfg = load_config()
    mcp = build_mcp_server()

    # Configure MCP transport security (DNS rebinding protection). The SDK
    # auto-enables it with a localhost-only allowlist when host == "127.0.0.1"
    # / "localhost" / "::1", which would reject any real public Host header
    # coming in via a reverse proxy. We bind 0.0.0.0 by default, so that
    # auto-enable doesn't fire and we have to opt in explicitly.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=cfg.allowed_origins,
    )

    # SSE app: GET /mcp opens the event stream; POST /mcp/posts accepts
    # client-to-server messages. The `endpoint` SSE event advertises
    # /mcp/posts to clients automatically.
    inner = mcp.sse_app(
        sse_path=SSE_PATH,
        message_path=SSE_MESSAGE_PATH,
        transport_security=transport_security,
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        # SSE manages per-connection sessions via `connect_sse`; there's no
        # shared session manager to start, so this is just logging.
        logger.info(
            "notetoself ready on %s:%d (tokens=%d, transport=sse)",
            cfg.host,
            cfg.port,
            len(cfg.tokens),
        )
        try:
            yield
        finally:
            logger.info("notetoself shutting down")

    protected = BearerAuthMiddleware(
        inner,
        tokens=cfg.tokens,
        exempt_paths=("/health",),
    )

    app = Starlette(
        debug=False,
        routes=[Mount("/", app=protected)],
        lifespan=lifespan,
    )
    return app


def main() -> None:
    cfg = load_config()
    app = build_app()
    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level="info",
        access_log=False,  # MCP traffic is noisy; MCP request/response logging happens inside the SDK
    )


if __name__ == "__main__":
    main()
