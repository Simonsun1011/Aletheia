"""HTTP middleware: ULID request_id + aletheia.api in/out lines.

Pure ASGI (not BaseHTTPMiddleware) so a blocked sync handler / SQLite wait
cannot exhaust the threadpool and wedge unrelated routes like /health.
"""

from __future__ import annotations

import logging
import time

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

from backend.app.logging_setup import set_request_id

api_log = logging.getLogger("aletheia.api")

CLIENT_HEADER = b"x-aletheia-client"
WRITE_METHODS = frozenset({b"POST", b"PATCH", b"DELETE", b"PUT"})


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = str(ULID())
        set_request_id(rid)
        scope.setdefault("state", {})
        # Starlette Request.state is a separate object; set via scope for logging path
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        started = time.perf_counter()
        api_log.info("→ %s %s", method, path)
        status_code_box: list[int] = [500]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_box[0] = int(message.get("status", 500))
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", rid.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            api_log.exception(
                "✗ %s %s failed after %.1fms",
                method,
                path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        api_log.info(
            "← %s %s %s (%.1fms)",
            method,
            path,
            status_code_box[0],
            elapsed_ms,
        )


class RequireClientHeaderMiddleware:
    """Drive-by CSRF soft gate: write methods need X-Aletheia-Client: 1.

    OPTIONS (CORS preflight) is allowed through. GET/HEAD unrestricted.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "GET").encode("ascii").upper()
        if method == b"OPTIONS" or method not in WRITE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {
            k.lower(): v for k, v in (scope.get("headers") or [])
        }
        if headers.get(CLIENT_HEADER) == b"1":
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "HTTP_403",
                    "message": "missing X-Aletheia-Client header",
                    "detail": {},
                }
            },
        )
        await response(scope, receive, send)
