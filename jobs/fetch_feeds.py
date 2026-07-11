#!/usr/bin/env python3
"""Fetch configured RSS feeds into feed_raw."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from ulid import ULID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.feed.config import enabled_feeds  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.stores.sqlite_store import SqliteStore  # noqa: E402

log = logging.getLogger("aletheia.jobs")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_published(entry) -> str | None:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except Exception:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except Exception:
                continue
    return None


def fetch_rss(url: str) -> list[dict]:
    import feedparser

    parsed = feedparser.parse(url)
    items = []
    for e in parsed.entries[:40]:
        items.append(
            {
                "title": e.get("title") or "(no title)",
                "url": e.get("link") or "",
                "published_at": _parse_published(e),
                "content": (e.get("summary") or e.get("description") or "")[:4000],
            }
        )
    return items


def focus_tickers(store: SqliteStore) -> list[str]:
    """Tickers for per-ticker feeds: prefer focus tier, else active."""
    try:
        rows = store._conn.execute(
            "SELECT ticker FROM watchlist WHERE status='active' AND tier='focus'"
        ).fetchall()
        if not rows:
            rows = store._conn.execute(
                "SELECT ticker FROM watchlist WHERE status='active'"
            ).fetchall()
        return [r[0] for r in rows][:8]
    except Exception:
        return ["AMAT", "MRVL", "NVDA"]


def run(batch_date: str | None = None) -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    store = SqliteStore(settings.app_db_path, settings.journal_dir)
    store.init_schema()
    batch = batch_date or _today()
    feeds = enabled_feeds()
    tickers = focus_tickers(store)
    total = 0
    errors = 0

    for feed in feeds:
        urls: list[tuple[str, list[str]]] = []
        if feed.type == "rss":
            urls.append((feed.url, []))
        elif feed.type == "rss_template":
            for t in tickers:
                urls.append((feed.url.format(ticker=t), [t]))
        else:
            log.warning("unknown feed type %s id=%s", feed.type, feed.id)
            continue

        for url, objs in urls:
            try:
                entries = fetch_rss(url)
                for e in entries:
                    if not e["url"]:
                        continue
                    store.insert_feed_raw(
                        {
                            "id": str(ULID()),
                            "fetched_at": _now(),
                            "published_at": e["published_at"],
                            "source": feed.name,
                            "title": e["title"],
                            "url": e["url"],
                            "content": e["content"],
                            "objects": json.dumps(objs),
                            "batch_date": batch,
                            "feed_id": feed.id,
                        }
                    )
                    total += 1
                log.info("%s: fetched %d entries", feed.id, len(entries))
                print(f"{feed.id}: fetched {len(entries)} rows, 0 errors")
            except Exception as e:
                errors += 1
                log.exception("%s failed: %s", feed.id, e)
                print(f"{feed.id}: fetched 0 rows, 1 errors ({e})")

    store.close()
    print(f"batch {batch}: total_raw={total}, source_errors={errors}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="batch_date YYYY-MM-DD")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
