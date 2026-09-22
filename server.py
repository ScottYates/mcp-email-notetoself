"""email.notetoself: an MCP server that emails you a note to yourself.

Server name: `email.notetoself`
Tool: `send_note`. Sends `message` as an email to `TO_EMAIL`.

Subject: ``NTS:<first 20 chars of the note>``
Body:    the full message, exactly as received.

Authorization: every request to the MCP endpoint must carry an
`X-Client-ID` header and an `Authorization: Bearer <token>` header whose
values match one of the entries in the `CLIENTS_JSON` environment variable.

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

from auth import ClientAuthMiddleware
from config import load_config
from mailer import MAX_BODY_CHARS, send_note

SERVER_NAME = "email.notetoself"

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

    # The streamable_http_app already has /mcp mounted and its own lifespan.
    # When we Mount it under another Starlette app, that inner lifespan never
    # runs, so we must start the session manager ourselves.
    inner = mcp.streamable_http_app(
        json_response=True,
        stateless_http=True,
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            logger.info(
                "email.notetoself ready on %s:%d (clients=%d)",
                cfg.host,
                cfg.port,
                len(cfg.clients),
            )
            try:
                yield
            finally:
                logger.info("email.notetoself shutting down")

    protected = ClientAuthMiddleware(
        inner,
        clients=cfg.clients,
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
