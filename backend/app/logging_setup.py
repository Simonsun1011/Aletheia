"""Logging setup — docs/architecture.md §6.5. Stdlib only, no third-party log frameworks."""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend.app.config import REPO_ROOT

# Per-request id (ULID string); "-" when outside a request (jobs, tests, startup).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOGGERS = ("aletheia.api", "aletheia.store", "aletheia.ai", "aletheia.jobs")

_configured = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    return request_id_var.get()


def setup_logging(
    *,
    level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    console: bool = True,
) -> None:
    """Idempotent. Call once at process entry (uvicorn / jobs)."""
    global _configured
    if _configured:
        return

    level_name = (level or os.getenv("ALETHEIA_LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    root_dir = Path(log_dir) if log_dir else Path(
        os.getenv("ALETHEIA_LOG_DIR", str(REPO_ROOT / "logs"))
    )
    root_dir.mkdir(parents=True, exist_ok=True)
    log_file = root_dir / "aletheia.log"

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(request_id)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    rid_filter = RequestIdFilter()

    handlers: list[logging.Handler] = []

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(rid_filter)
    handlers.append(file_handler)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler.addFilter(rid_filter)
        handlers.append(stream_handler)

    root = logging.getLogger("aletheia")
    root.handlers.clear()
    root.setLevel(log_level)
    for h in handlers:
        root.addHandler(h)
    root.propagate = False

    for name in LOGGERS:
        logging.getLogger(name).setLevel(log_level)

    _configured = True


def reset_logging_for_tests() -> None:
    """Allow tests to re-run setup_logging against a temp directory."""
    global _configured
    root = logging.getLogger("aletheia")
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    _configured = False
