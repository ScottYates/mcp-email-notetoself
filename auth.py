"""Client-id + bearer-token auth middleware for the MCP HTTP endpoint.

A pure ASGI middleware so it can wrap the Starlette app returned by
`MCPServer.streamable_http_app()` without depending on Starlette's middleware
plumbing (which is mounted under a path prefix in the parent app and harder
to reason about).

Expected headers on every request to a protected path:
    X-Client-ID: <id>
    Authorization: Bearer <token>

`Authorization` is checked with `secrets.compare_digest` to make timing
attacks harder.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from starlette.responses import JSONResponse

# ASGI types — kept minimal so we don't have to import starlette.types.
Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class ClientAuthMiddleware:
    """ASGI middleware that enforces client_id + bearer-token auth.

    Args:
        app: The downstream ASGI application (the MCP server's Starlette app).
        clients: Mapping of allowed client_id -> expected token.
        exempt_paths: Paths that bypass auth (e.g. health checks).
    """

    def __init__(
        self,
        app: ASGIApp,
        clients: dict[str, str],
        exempt_paths: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.clients = clients
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only HTTP requests get auth. Lifespan events pass straight through.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }

        client_id = headers.get("x-client-id", "")
        auth_header = headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            await self._reject(send, "missing or malformed Authorization header")
            return

        presented_token = auth_header[len("Bearer ") :].strip()
        if not presented_token:
            await self._reject(send, "empty bearer token")
            return

        expected_token = self.clients.get(client_id)
        if expected_token is None:
            # Don't distinguish "unknown client" from "bad token" in the
            # response — same status + message either way — so we don't leak
            # which client ids are valid.
            await self._reject(send, "invalid client_id or token")
            return

        if not secrets.compare_digest(presented_token, expected_token):
            await self._reject(send, "invalid client_id or token")
            return

        # Stash the authenticated client_id on the scope so handlers downstream
        # can log it.
        scope.setdefault("state", {})["client_id"] = client_id

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, reason: str) -> None:
        response = JSONResponse(
            {"error": "unauthorized", "detail": reason},
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="email.notetoself"'},
        )
        await response({"type": "http"}, _noop_receive, send)


async def _noop_receive() -> Message:
    # Starlette's response objects will only call receive() if the request
    # body is needed; for a 401 short-circuit we never read it.
    return {"type": "http.disconnect"}
