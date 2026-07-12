"""Fetch RSS → feed_raw, then digest → feed_cards (user-triggered refresh).

Supports background run + status polling so SPA tab switches don't lose progress.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Optional

from ulid import ULID

from backend.app.feed.config import enabled_feeds
from backend.app.services.digest import digest_batch
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.jobs")

_refresh_lock = threading.Lock()
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "phase": None,  # fetch | digest | done | error | cancelled
    "batch_date": None,
    "started_at": None,
    "finished_at": None,
    "heartbeat_at": None,
    "message": None,
    "error": None,
    "result": None,
}
_cancel_requested = False


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


def fetch_rss(url: str, *, max_entries: int = 100) -> list[dict]:
    import feedparser

    parsed = feedparser.parse(url)
    items = []
    for e in parsed.entries[:max_entries]:
        items.append(
            {
                "title": e.get("title") or "(no title)",
                "url": e.get("link") or "",
                "published_at": _parse_published(e),
                "content": (e.get("summary") or e.get("description") or "")[:4000],
            }
        )
    return items


def tickers_for_tier(store: AppStore, tier: str | None) -> list[str]:
    """Slice 3c: base → focus+base; focus → focus (fallback all active)."""
    list_fn = getattr(store, "list_watchlist", None)
    if not callable(list_fn):
        return ["AMAT", "MRVL", "NVDA"]
    wl = list_fn()
    active = list(wl.active)
    if tier == "focus":
        rows = [i for i in active if i.tier == "focus"] or active
    elif tier == "base":
        rows = [i for i in active if i.tier in ("focus", "base")]
        rows.sort(key=lambda i: (0 if i.tier == "focus" else 1, i.ticker))
    else:
        rows = active
    out = [i.ticker for i in rows][:12]
    return out or ["AMAT", "MRVL", "NVDA"]


def focus_tickers_compat(store: AppStore) -> list[str]:
    """Prefer focus tier, else all active."""
    return tickers_for_tier(store, "focus")


def _feed_raw_empty(store: AppStore) -> bool:
    conn = getattr(store, "_conn", None)
    if conn is None:
        return False
    row = conn.execute("SELECT 1 FROM feed_raw LIMIT 1").fetchone()
    return row is None


def _set_state(**kwargs: Any) -> None:
    with _state_lock:
        _state.update(kwargs)
        if "message" in kwargs or kwargs.get("running") or kwargs.get("phase"):
            _state["heartbeat_at"] = _now()


def refresh_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def request_refresh_cancel() -> dict[str, Any]:
    """Ask the in-flight refresh to stop between digest items (best-effort)."""
    global _cancel_requested
    with _state_lock:
        running = bool(_state.get("running"))
    if not running:
        return {"accepted": False, **refresh_status()}
    _cancel_requested = True
    _set_state(message="正在停止生成…")
    return {"accepted": True, **refresh_status()}


def _cancel_flag() -> bool:
    return _cancel_requested


def _reset_cancel() -> None:
    global _cancel_requested
    _cancel_requested = False


def fetch_batch(
    store: AppStore,
    batch_date: Optional[str] = None,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Pull enabled feeds into feed_raw. Does not call LLM."""
    batch = batch_date or _today()
    feeds = enabled_feeds()
    total = 0
    errors = 0
    first_run = _feed_raw_empty(store)
    # Per-ticker templates explode quickly (tickers × feeds); keep shallow.
    max_wire = 80 if first_run else 30
    max_ticker = 12 if first_run else 8
    depth_log: list[str] = []

    for feed in feeds:
        if on_progress:
            on_progress(f"抓取 {feed.id}…")
        urls: list[tuple[str, list[str]]] = []
        if feed.type == "rss":
            urls.append((feed.url, []))
        elif feed.type == "rss_template":
            for t in tickers_for_tier(store, feed.tier):
                urls.append((feed.url.format(ticker=t), [t]))
        else:
            log.warning("unknown feed type %s id=%s", feed.type, feed.id)
            continue

        max_entries = max_ticker if feed.type == "rss_template" else max_wire
        for url, objs in urls:
            try:
                entries = fetch_rss(url, max_entries=max_entries)
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
                depth_log.append(
                    f"{feed.id}: entries={len(entries)} max={max_entries} "
                    f"tier={feed.tier or '-'} urls={len(urls)}"
                )
                log.info(
                    "%s: fetched %d entries (max=%d tier=%s)",
                    feed.id,
                    len(entries),
                    max_entries,
                    feed.tier,
                )
            except Exception as e:
                errors += 1
                depth_log.append(f"{feed.id}: ERROR {e}")
                log.exception("%s failed: %s", feed.id, e)

    return {
        "batch_date": batch,
        "raw": total,
        "source_errors": errors,
        "first_run": first_run,
        "depths": depth_log,
    }


class RefreshInProgressError(Exception):
    code = "REFRESH_IN_PROGRESS"


def refresh_feed(
    store: AppStore,
    batch_date: Optional[str] = None,
    *,
    skip_fetch: bool = False,
) -> dict[str, Any]:
    """Synchronous fetch+digest (CLI). Updates shared status for pollers."""
    if not _refresh_lock.acquire(blocking=False):
        raise RefreshInProgressError("feed refresh already running")
    try:
        return _run_refresh(store, batch_date, skip_fetch=skip_fetch)
    finally:
        _refresh_lock.release()


def _run_refresh(
    store: AppStore,
    batch_date: Optional[str],
    *,
    skip_fetch: bool,
) -> dict[str, Any]:
    batch = batch_date or _today()
    _reset_cancel()

    def progress(msg: str) -> None:
        _set_state(message=msg)

    _set_state(
        running=True,
        phase="fetch" if not skip_fetch else "digest",
        batch_date=batch,
        started_at=_now(),
        finished_at=None,
        error=None,
        result=None,
        message="开始生成今日简报…",
    )
    try:
        fetch_stats: dict[str, Any] = {
            "batch_date": batch,
            "raw": 0,
            "source_errors": 0,
            "skipped": skip_fetch,
        }
        if not skip_fetch:
            if _cancel_flag():
                raise InterruptedError("cancelled before fetch")
            _set_state(phase="fetch", message="正在抓取信源…")
            fetch_stats = fetch_batch(store, batch, on_progress=progress)
        _set_state(phase="digest", message="正在摘要与打标…")
        digest_stats = digest_batch(
            store,
            batch,
            on_progress=progress,
            should_stop=_cancel_flag,
        )
        cards = store.list_feed_cards(batch_date=batch, days=1)
        result = {
            "batch_date": batch,
            "fetch": fetch_stats,
            "digest": digest_stats,
            "cards": len(cards),
        }
        cancelled = bool(digest_stats.get("cancelled")) or _cancel_flag()
        _set_state(
            running=False,
            phase="cancelled" if cancelled else "done",
            finished_at=_now(),
            message=(
                f"已停止：入卡 {len(cards)} 条"
                if cancelled
                else f"完成：入卡 {len(cards)} 条"
            ),
            result=result,
            error=None,
        )
        return result
    except InterruptedError:
        cards = store.list_feed_cards(batch_date=batch, days=1)
        result = {"batch_date": batch, "cards": len(cards), "cancelled": True}
        _set_state(
            running=False,
            phase="cancelled",
            finished_at=_now(),
            message=f"已停止：入卡 {len(cards)} 条",
            result=result,
            error=None,
        )
        return result
    except Exception as e:
        log.exception("feed refresh failed: %s", e)
        _set_state(
            running=False,
            phase="error",
            finished_at=_now(),
            message="生成失败",
            error=str(e),
        )
        raise
    finally:
        _reset_cancel()


def start_refresh_background(
    *,
    db_path: Path,
    journal_dir: Path,
    batch_date: Optional[str] = None,
    skip_fetch: bool = False,
) -> dict[str, Any]:
    """Start refresh on a dedicated Sqlite connection (thread-safe vs request store)."""
    if not _refresh_lock.acquire(blocking=False):
        return {"accepted": False, **refresh_status()}

    def worker() -> None:
        from backend.app.stores.sqlite_store import SqliteStore

        store = SqliteStore(db_path, journal_dir)
        try:
            store.init_schema()
            _run_refresh(store, batch_date, skip_fetch=skip_fetch)
        except Exception:
            pass  # state already records error
        finally:
            try:
                store.close()
            except Exception:
                pass
            if _refresh_lock.locked():
                _refresh_lock.release()

    # Mark running before thread starts so immediate status polls see it
    _set_state(
        running=True,
        phase="starting",
        batch_date=batch_date or _today(),
        started_at=_now(),
        finished_at=None,
        error=None,
        result=None,
        message="已排队，即将开始…",
    )
    t = threading.Thread(target=worker, name="feed-refresh", daemon=True)
    t.start()
    return {"accepted": True, **refresh_status()}
