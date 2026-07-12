"""On-demand local market data: fetch prices + compute indicators if missing.

Console / snapshot should work for any US ticker without a prior jobs run.
Jobs remain the batch path; this is the interactive path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from backend.app.market.db import connect_market_db
from backend.app.market.sector_map import load_sector_etf

log = logging.getLogger("aletheia.market")

# Enough bars for SMA50 / relative 20d; fetch job default is 400.
FETCH_DAYS = 400
MIN_BARS = 60


def _price_count(conn, ticker: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM prices WHERE ticker = ?",
        (ticker.upper(),),
    ).fetchone()
    return int(row["c"] if row else 0)


def ensure_local_market_data(
    market_db: Path,
    symbol: str,
    *,
    also: Optional[list[str]] = None,
) -> list[str]:
    """
    Ensure `symbol` has local OHLCV + indicators.

    If the primary symbol is thin/missing, also pull QQQ and sector ETF
    (for relative indicators). If the symbol already has enough bars,
    only recompute indicators — no network.

    Returns warning strings. Failures are soft so other panels still render.
    """
    warnings: list[str] = []
    symbol = symbol.upper()
    sector = load_sector_etf(symbol)

    conn = connect_market_db(Path(market_db))
    try:
        primary_thin = _price_count(conn, symbol) < MIN_BARS
        to_fetch: list[str] = []
        if primary_thin:
            to_fetch.append(symbol)
            for t in ("QQQ", sector, *(also or [])):
                if not t:
                    continue
                t = t.upper()
                if t not in to_fetch and _price_count(conn, t) < MIN_BARS:
                    to_fetch.append(t)

        if to_fetch:
            from jobs.fetch_prices import fetch_ohlcv, upsert_prices

            for t in to_fetch:
                try:
                    df = fetch_ohlcv(t, days=FETCH_DAYS)
                    upsert_prices(conn, t, df)
                    log.info("on-demand fetch %s rows=%s", t, len(df))
                    warnings.append(f"fetched market data for {t}")
                except Exception as e:
                    log.warning("on-demand fetch failed %s: %s", t, e)
                    warnings.append(f"fetch failed for {t}: {e}")

        if _price_count(conn, symbol) >= MIN_BARS:
            try:
                from jobs.compute_indicators import compute_for_ticker

                n = compute_for_ticker(conn, symbol)
                log.info("on-demand indicators %s cells=%s", symbol, n)
            except Exception as e:
                log.warning("on-demand indicators failed %s: %s", symbol, e)
                warnings.append(f"indicators failed for {symbol}: {e}")
        elif primary_thin:
            pass  # fetch warnings already recorded
        else:
            warnings.append(f"insufficient local bars for {symbol}")
    finally:
        conn.close()

    return warnings
