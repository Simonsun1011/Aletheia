"""Compute indicators into market_data.db (formulas = buy_planner.py)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.logging_setup import setup_logging  # noqa: E402
from backend.app.market.db import connect_market_db  # noqa: E402
from backend.app.market.indicators import (  # noqa: E402
    STORED_INDICATOR_NAMES,
    compute_indicator_frame,
    period_return,
)
from backend.app.market.sector_map import load_sector_etf  # noqa: E402

log = logging.getLogger("aletheia.jobs")


def load_ticker_df(conn, ticker: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date ASC",
        (ticker.upper(),),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def upsert_indicator(conn, ticker: str, date: str, name: str, value) -> None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return
    conn.execute(
        """
        INSERT INTO indicators (ticker, date, name, value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, date, name) DO UPDATE SET value=excluded.value
        """,
        (ticker.upper(), date, name, float(value)),
    )


def compute_for_ticker(conn, ticker: str) -> int:
    df = load_ticker_df(conn, ticker)
    if df.empty:
        log.warning("%s: no prices, skip", ticker)
        return 0

    frame = compute_indicator_frame(df)
    qqq = load_ticker_df(conn, "QQQ")
    sector_etf = load_sector_etf(ticker)
    sector_df = load_ticker_df(conn, sector_etf) if sector_etf else pd.DataFrame()

    written = 0
    # Write last bar only for v1 snapshot use (full history optional later)
    last_idx = frame.index[-1]
    date = last_idx.strftime("%Y-%m-%d")
    row = frame.loc[last_idx]

    for name in STORED_INDICATOR_NAMES:
        if name.startswith("rel_"):
            continue
        if name in row.index:
            upsert_indicator(conn, ticker, date, name, row[name])
            written += 1

    # Relative vs QQQ / sector on last date
    if not qqq.empty:
        # align by date intersection for returns
        common = df.index.intersection(qqq.index)
        if len(common) >= 61:
            t_c = df.loc[common, "close"]
            q_c = qqq.loc[common, "close"]
            r20 = period_return(t_c, 20)
            q20 = period_return(q_c, 20)
            r60 = period_return(t_c, 60)
            q60 = period_return(q_c, 60)
            if r20 is not None and q20 is not None:
                upsert_indicator(conn, ticker, date, "rel_qqq_20d", r20 - q20)
                written += 1
            if r60 is not None and q60 is not None:
                upsert_indicator(conn, ticker, date, "rel_qqq_60d", r60 - q60)
                written += 1

    if sector_etf and not sector_df.empty:
        common = df.index.intersection(sector_df.index)
        if len(common) >= 61:
            t_c = df.loc[common, "close"]
            s_c = sector_df.loc[common, "close"]
            r20 = period_return(t_c, 20)
            s20 = period_return(s_c, 20)
            r60 = period_return(t_c, 60)
            s60 = period_return(s_c, 60)
            if r20 is not None and s20 is not None:
                upsert_indicator(conn, ticker, date, "rel_sector_20d", r20 - s20)
                written += 1
            if r60 is not None and s60 is not None:
                upsert_indicator(conn, ticker, date, "rel_sector_60d", r60 - s60)
                written += 1

    conn.commit()
    return written


def run(tickers: list[str], market_db: Path) -> None:
    conn = connect_market_db(market_db)
    try:
        for t in tickers:
            n = compute_for_ticker(conn, t)
            log.info("%s: wrote %d indicator values", t, n)
            print(f"{t}: computed {n} indicator cells, 0 errors")
    finally:
        conn.close()


def main() -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    parser = argparse.ArgumentParser(description="Compute indicators into market_data.db")
    parser.add_argument("--tickers", nargs="+", default=["AMAT"])
    parser.add_argument("--db", type=Path, default=settings.market_db_path)
    args = parser.parse_args()
    run(args.tickers, args.db)


if __name__ == "__main__":
    main()
