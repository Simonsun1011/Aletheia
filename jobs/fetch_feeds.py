#!/usr/bin/env python3
"""Fetch configured RSS feeds into feed_raw."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.services import feed_ingest  # noqa: E402
from backend.app.stores.sqlite_store import SqliteStore  # noqa: E402

# Re-export for tests importing from jobs.fetch_feeds
fetch_rss = feed_ingest.fetch_rss
tickers_for_tier = feed_ingest.tickers_for_tier
focus_tickers = feed_ingest.focus_tickers_compat


def run(batch_date: str | None = None) -> dict:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    store = SqliteStore(settings.app_db_path, settings.journal_dir)
    store.init_schema()
    try:
        stats = feed_ingest.fetch_batch(store, batch_date)
    finally:
        store.close()
    if stats.get("first_run"):
        print("first-run backfill depths:")
        for line in stats.get("depths") or []:
            print(f"  {line}")
    print(
        f"batch {stats['batch_date']}: total_raw={stats['raw']}, "
        f"source_errors={stats['source_errors']}"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="batch_date YYYY-MM-DD")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
