#!/usr/bin/env python3
"""One-shot: fetch feeds + digest → today's briefing cards.

Prefer the in-app button「生成今日简报」, or:
  .venv/bin/python jobs/refresh_feed.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.ai import usage as llm_usage  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.services.feed_ingest import refresh_feed  # noqa: E402
from backend.app.stores.sqlite_store import SqliteStore  # noqa: E402


def main() -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    parser = argparse.ArgumentParser(description="Fetch + digest one batch")
    parser.add_argument("--date", default=None, help="batch_date YYYY-MM-DD")
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="skip fetch; digest existing feed_raw only",
    )
    args = parser.parse_args()
    store = SqliteStore(settings.app_db_path, settings.journal_dir)
    store.init_schema()
    llm_usage.wire_llm_usage(store)
    try:
        stats = refresh_feed(
            store, args.date, skip_fetch=args.digest_only
        )
    finally:
        store.close()
    print(
        f"refresh {stats['batch_date']}: "
        f"raw={stats['fetch'].get('raw', 0)} "
        f"digest_ok={stats['digest'].get('ok', 0)} "
        f"filtered={stats['digest'].get('filtered', 0)} "
        f"cards={stats['cards']}"
    )


if __name__ == "__main__":
    main()
