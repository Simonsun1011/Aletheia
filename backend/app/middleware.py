"""HTTP middleware: ULID request_id + aletheia.api in/out lines."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

from backend.app.logging_setup import set_request_id

api_log = logging.getLogger("aletheia.api")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = str(ULID())
        set_request_id(rid)
        request.state.request_id = rid
        started = time.perf_counter()
        api_log.info("→ %s %s", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            api_log.exception(
                "✗ %s %s failed after %.1fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        api_log.info(
            "← %s %s %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-ID"] = rid
        return response
