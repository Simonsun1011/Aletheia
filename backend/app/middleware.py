"""HTTP middleware: ULID request_id + aletheia.api in/out lines.

Pure ASGI (not BaseHTTPMiddleware) so a blocked sync handler / SQLite wait
cannot exhaust the threadpool and wedge unrelated routes like /health.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

from backend.app.logging_setup import set_request_id

api_log = logging.getLogger("aletheia.api")


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
