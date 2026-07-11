"""Build GET /tickers/{symbol}/snapshot payload from market_data.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backend.app.market.db import connect_market_db
from backend.app.market.indicators import period_return
from backend.app.market.sector_map import load_sector_etf


def _load_prices(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date ASC",
        (ticker.upper(),),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def _ind_map(conn: sqlite3.Connection, ticker: str, as_of: str) -> dict[str, Optional[float]]:
    rows = conn.execute(
        "SELECT name, value FROM indicators WHERE ticker = ? AND date = ?",
        (ticker.upper(), as_of),
    ).fetchall()
    return {r["name"]: r["value"] for r in rows}


def _chg(closes: pd.Series, days: int) -> Optional[float]:
    return period_return(closes, days)


def _finite(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return v


def build_snapshot(market_db: Path, symbol: str) -> Optional[dict[str, Any]]:
    """
    Return snapshot dict or None if ticker has no price rows (→ 404).
    Missing fields are null with warnings; never fabricated.
    """
    symbol = symbol.upper()
    conn = connect_market_db(market_db)
    try:
        df = _load_prices(conn, symbol)
        if df.empty:
            return None

        as_of = df.index[-1].strftime("%Y-%m-%d")
        closes = df["close"]
        lows = df["low"]
        inds = _ind_map(conn, symbol, as_of)
        warnings: list[str] = []

        def need(name: str, value: Optional[float], why: str) -> Optional[float]:
            v = _finite(value)
            if v is None:
                warnings.append(why)
            return v

        # Prefer stored indicators; fall back to on-the-fly from prices for anchors
        sma50 = need("sma50", inds.get("sma50"), "sma50 unavailable (need ≥50 bars)")
        sma200 = need(
            "sma200",
            inds.get("sma200"),
            "sma200 unavailable (need ≥200 bars of history)",
        )
        boll_lower = need(
            "boll_lower", inds.get("boll_lower"), "boll_lower unavailable (need ≥20 bars)"
        )
        boll_mid = need(
            "boll_mid", inds.get("boll_mid"), "boll_mid unavailable (need ≥20 bars)"
        )
        vwap20 = need("vwap20", inds.get("vwap20"), "vwap20 unavailable (need ≥20 bars)")
        atr14 = need("atr14", inds.get("atr14"), "atr14 unavailable")
        rsi14 = need("rsi14", inds.get("rsi14"), "rsi14 unavailable")
        vol_20d_ann = need(
            "vol_20d_ann", inds.get("vol_20d_ann"), "vol_20d_ann unavailable (need ≥21 bars)"
        )
        drawdown = need(
            "drawdown_52w",
            inds.get("drawdown_52w"),
            "drawdown_52w unavailable",
        )

        # Anchors from price history (not all stored as named indicators)
        high_52w = _finite(closes.tail(252).max()) if len(closes) else None
        if high_52w is None:
            warnings.append("high_52w unavailable")
        low_10d = _finite(lows.tail(10).min()) if len(lows) >= 1 else None
        low_20d = _finite(lows.tail(20).min()) if len(lows) >= 1 else None
        low_60d = _finite(lows.tail(60).min()) if len(lows) >= 1 else None

        last = _finite(closes.iloc[-1])
        price = {
            "last": last,
            "chg_1d": _chg(closes, 1),
            "chg_5d": _chg(closes, 5),
            "chg_20d": _chg(closes, 20),
            "chg_60d": _chg(closes, 60),
        }
        for k, v in list(price.items()):
            if k != "last" and v is None:
                warnings.append(f"{k} unavailable (insufficient history)")

        sector_etf = load_sector_etf(symbol)
        vs_qqq_20d = _finite(inds.get("rel_qqq_20d"))
        vs_qqq_60d = _finite(inds.get("rel_qqq_60d"))
        if vs_qqq_20d is None:
            warnings.append("vs_qqq_20d unavailable")
        if vs_qqq_60d is None:
            warnings.append("vs_qqq_60d unavailable")

        if sector_etf:
            vs_sector_20d = _finite(inds.get("rel_sector_20d"))
            vs_sector_60d = _finite(inds.get("rel_sector_60d"))
            if vs_sector_20d is None:
                warnings.append("vs_sector_20d unavailable")
            if vs_sector_60d is None:
                warnings.append("vs_sector_60d unavailable")
        else:
            vs_sector_20d = None
            vs_sector_60d = None
            # QQQ-only: sector fields intentionally null — not a warning

        return {
            "symbol": symbol,
            "as_of": as_of,
            "price": price,
            "anchors": {
                "sma50": sma50,
                "sma200": sma200,
                "boll_lower": boll_lower,
                "boll_mid": boll_mid,
                "vwap20": vwap20,
                "low_10d": low_10d,
                "low_20d": low_20d,
                "low_60d": low_60d,
                "high_52w": high_52w,
                "drawdown_52w": drawdown,
            },
            "risk": {
                "atr14": atr14,
                "rsi14": rsi14,
                "vol_20d_ann": vol_20d_ann,
            },
            "relative": {
                "vs_qqq_20d": vs_qqq_20d,
                "vs_qqq_60d": vs_qqq_60d,
                "vs_sector_20d": vs_sector_20d,
                "vs_sector_60d": vs_sector_60d,
                "sector_etf": sector_etf,
            },
            "warnings": warnings,
        }
    finally:
        conn.close()
