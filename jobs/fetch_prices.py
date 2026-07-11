"""yfinance → market_data.db prices (idempotent upsert)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python jobs/fetch_prices.py` from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.market.db import connect_market_db  # noqa: E402

log = logging.getLogger("aletheia.jobs")

DEFAULT_TICKERS = ["AMAT", "QQQ", "SOXX"]


def fetch_ohlcv(ticker: str, days: int = 400):
    import yfinance as yf
    import pandas as pd

    df = yf.download(
        ticker,
        period=f"{days}d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise RuntimeError(f"no data for {ticker}")
    df = df.dropna()
    # Normalize column names
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return df


def upsert_prices(conn, ticker: str, df) -> int:
    rows = 0
    for dt, row in df.iterrows():
        date = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        conn.execute(
            """
            INSERT INTO prices (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume
            """,
            (
                ticker.upper(),
                date,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row["volume"]),
            ),
        )
        rows += 1
    conn.commit()
    return rows


def count_prices(conn, ticker: str) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM prices WHERE ticker = ?", (ticker.upper(),)
    )
    return int(cur.fetchone()[0])


def run(tickers: list[str], market_db: Path, days: int = 400) -> None:
    conn = connect_market_db(market_db)
    try:
        for t in tickers:
            try:
                before = count_prices(conn, t)
                df = fetch_ohlcv(t, days=days)
                upsert_prices(conn, t, df)
                after = count_prices(conn, t)
                log.info(
                    "%s: fetched %d rows, table now %d (was %d)",
                    t,
                    len(df),
                    after,
                    before,
                )
                print(f"{t}: fetched {len(df)} rows, 0 errors (prices={after})")
            except Exception as e:
                log.exception("%s: fetch failed", t)
                print(f"{t}: fetched 0 rows, 1 errors ({e})")
    finally:
        conn.close()


def main() -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    parser = argparse.ArgumentParser(description="Fetch OHLCV into market_data.db")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="Tickers to fetch (default: AMAT QQQ SOXX)",
    )
    parser.add_argument("--db", type=Path, default=settings.market_db_path)
    parser.add_argument("--days", type=int, default=400)
    args = parser.parse_args()
    run(args.tickers, args.db, days=args.days)


if __name__ == "__main__":
    main()
