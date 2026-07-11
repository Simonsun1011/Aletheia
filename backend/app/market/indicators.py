"""Indicator formulas — must match buy_planner.py (Wilder ATR/RSI, boll 20/2, VWAP20)."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

# Same defaults as buy_planner.DEFAULTS for overlapping params
PARAMS = {
    "atr_period": 14,
    "rsi_period": 14,
    "boll_period": 20,
    "boll_std": 2.0,
    "sma_short": 50,
    "sma_long": 200,
    "vwap_days": 20,
}


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n]
        # case-insensitive
        for c in df.columns:
            if str(c).lower() == n.lower():
                return df[c]
    raise KeyError(f"missing column among {names}")


def compute_indicator_frame(df: pd.DataFrame, p: Optional[dict] = None) -> pd.DataFrame:
    """
    Return a DataFrame aligned to df.index with columns matching data-model
    indicator names (plus helper lows/high for snapshot anchors).
    """
    p = {**PARAMS, **(p or {})}
    c = _col(df, "Close", "close")
    h = _col(df, "High", "high")
    l = _col(df, "Low", "low")
    v = _col(df, "Volume", "volume")

    out = pd.DataFrame(index=df.index)
    out["sma50"] = c.rolling(p["sma_short"]).mean()
    out["sma200"] = c.rolling(p["sma_long"]).mean()

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / p["atr_period"], adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi14"] = 100 - 100 / (1 + rs)

    boll_mid = c.rolling(p["boll_period"]).mean()
    boll_std = c.rolling(p["boll_period"]).std()
    out["boll_mid"] = boll_mid
    out["boll_lower"] = boll_mid - p["boll_std"] * boll_std

    # Rolling VWAP approximation (same as buy_planner: sum(c*v)/sum(v) over window)
    cv = c * v
    out["vwap20"] = cv.rolling(p["vwap_days"]).sum() / v.rolling(p["vwap_days"]).sum()

    high_52w = c.rolling(252, min_periods=1).max()
    out["high_52w"] = high_52w
    out["drawdown_52w"] = c / high_52w - 1.0

    out["low_10d"] = l.rolling(10, min_periods=1).min()
    out["low_20d"] = l.rolling(20, min_periods=1).min()
    out["low_60d"] = l.rolling(60, min_periods=1).min()

    # buy_planner returns percent; we store decimal annualized vol for API consistency
    # but expose buy_planner-compatible helper separately for tests
    out["vol_20d_ann"] = c.pct_change().rolling(20).std() * np.sqrt(252)

    return out


def buy_planner_compatible_last_row(df: pd.DataFrame, p: Optional[dict] = None) -> dict[str, Any]:
    """Last-row values matching buy_planner.compute_indicators numeric fields."""
    p = {**PARAMS, **(p or {})}
    c = _col(df, "Close", "close")
    h = _col(df, "High", "high")
    l = _col(df, "Low", "low")
    v = _col(df, "Volume", "volume")
    last = float(c.iloc[-1])

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / p["atr_period"], adjust=False).mean().iloc[-1])

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    rsi = float((100 - 100 / (1 + gain / loss)).iloc[-1])

    boll_mid = c.rolling(p["boll_period"]).mean()
    boll_std = c.rolling(p["boll_period"]).std()
    high_52w = float(c.tail(252).max())

    return {
        "last": last,
        "atr": atr,
        "atr_pct": atr / last * 100,
        "rsi": rsi,
        "sma_short": float(c.rolling(p["sma_short"]).mean().iloc[-1]),
        "sma_long": (
            float(c.rolling(p["sma_long"]).mean().iloc[-1])
            if len(c) >= p["sma_long"]
            else None
        ),
        "boll_lower": float((boll_mid - p["boll_std"] * boll_std).iloc[-1]),
        "boll_mid": float(boll_mid.iloc[-1]),
        "vwap": float((c * v).tail(p["vwap_days"]).sum() / v.tail(p["vwap_days"]).sum()),
        "high_52w": high_52w,
        "drawdown_pct": (last / high_52w - 1) * 100,
        "low_10d": float(l.tail(10).min()),
        "low_20d": float(l.tail(20).min()),
        "low_60d": float(l.tail(60).min()),
        "vol_20d_ann": float(c.pct_change().tail(20).std() * np.sqrt(252) * 100),
    }


def period_return(closes: pd.Series, days: int) -> Optional[float]:
    """Return over `days` trading sessions ending at last bar; None if insufficient."""
    if len(closes) < days + 1:
        return None
    a = float(closes.iloc[-1])
    b = float(closes.iloc[-(days + 1)])
    if b == 0:
        return None
    return a / b - 1.0


# Indicator names persisted to market_data.db indicators table (data-model §2)
STORED_INDICATOR_NAMES = (
    "sma50",
    "sma200",
    "atr14",
    "rsi14",
    "boll_lower",
    "boll_mid",
    "vwap20",
    "drawdown_52w",
    "rel_qqq_20d",
    "rel_qqq_60d",
    "rel_sector_20d",
    "rel_sector_60d",
    "vol_20d_ann",
)
