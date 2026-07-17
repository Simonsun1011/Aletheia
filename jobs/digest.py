#!/usr/bin/env python3
"""Dedup + summarize raw feeds into feed_cards."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.ai import usage as llm_usage  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.services.digest import digest_batch  # noqa: E402
from backend.app.stores.sqlite_store import SqliteStore  # noqa: E402


def main() -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    args = parser.parse_args()
    store = SqliteStore(settings.app_db_path, settings.journal_dir)
    store.init_schema()
    llm_usage.wire_llm_usage(store)
    try:
        digest_batch(store, args.date)
    finally:
        store.close()


if __name__ == "__main__":
    main()
