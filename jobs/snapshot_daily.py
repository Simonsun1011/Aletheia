"""Write daily snapshots into app.db (data-model snapshots table).

v1: ticker:<SYM> payloads from market_data indicators + QQQ/SOXX;
market module writes available index rows (VIX optional / null if absent).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.market.db import connect_market_db  # noqa: E402
from backend.app.stores.sqlite_store import SqliteStore  # noqa: E402

log = logging.getLogger("aletheia.jobs")

SCHEMA_VERSION = 1


def _latest_price_date(conn, ticker: str) -> Optional[str]:
    row = conn.execute(
        "SELECT date FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    return row["date"] if row else None


def _indicators_on(conn, ticker: str, as_of: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT name, value FROM indicators WHERE ticker = ? AND date = ?",
        (ticker.upper(), as_of),
    ).fetchall()
    return {r["name"]: r["value"] for r in rows}


def _close_on(conn, ticker: str, as_of: str) -> Optional[float]:
    row = conn.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date = ?",
        (ticker.upper(), as_of),
    ).fetchone()
    return float(row["close"]) if row else None


def build_ticker_payload(conn, ticker: str, as_of: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker.upper(),
        "as_of": as_of,
        "close": _close_on(conn, ticker, as_of),
        "indicators": _indicators_on(conn, ticker, as_of),
    }


def build_market_payload(conn, as_of: str) -> dict[str, Any]:
    """Best-effort market module; missing series → null (no fabrication)."""
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "qqq_close": _close_on(conn, "QQQ", as_of),
        "soxx_close": _close_on(conn, "SOXX", as_of),
        "vix_close": _close_on(conn, "VIX", as_of),
    }
    return payload


def run(*, as_of: Optional[str] = None, tickers: Optional[list[str]] = None) -> int:
    settings = get_settings()
    store = SqliteStore(settings.app_db_path, settings.journal_dir)
    store.init_schema()
    mconn = connect_market_db(settings.market_db_path)
    try:
        if tickers:
            syms = [t.upper() for t in tickers]
        else:
            wl = store.list_watchlist()
            syms = sorted({i.ticker.upper() for i in wl.active})
            for extra in ("QQQ", "SOXX"):
                if extra not in syms:
                    syms.append(extra)

        if not as_of:
            # Prefer QQQ calendar; fall back to first ticker with prices
            as_of = _latest_price_date(mconn, "QQQ")
            if not as_of and syms:
                as_of = _latest_price_date(mconn, syms[0])
        if not as_of:
            log.error("no price dates available; abort snapshot_daily")
            return 1

        written = 0
        for sym in syms:
            if _latest_price_date(mconn, sym) is None:
                log.warning("skip ticker=%s (no prices)", sym)
                continue
            # Use as_of if ticker has that bar; else latest for that ticker
            day = as_of
            if _close_on(mconn, sym, day) is None:
                day = _latest_price_date(mconn, sym) or as_of
            payload = build_ticker_payload(mconn, sym, day)
            store.upsert_snapshot(day, f"ticker:{sym}", payload)
            written += 1
            log.info("snapshot ticker:%s date=%s", sym, day)

        market = build_market_payload(mconn, as_of)
        store.upsert_snapshot(as_of, "market", market)
        written += 1
        log.info("snapshot market date=%s written=%s", as_of, written)
        return 0
    finally:
        mconn.close()
        store.close()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Write daily snapshots to app.db")
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: latest QQQ)")
    p.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Symbols (default: watchlist active + QQQ/SOXX)",
    )
    args = p.parse_args(argv)
    setup_logging()
    return run(as_of=args.as_of, tickers=args.tickers)


if __name__ == "__main__":
    raise SystemExit(main())
