"""Judgment window settlement — data-model.md §4 (numbers only, no evaluative text)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backend.app.market.db import connect_market_db
from backend.app.market.sector_map import load_sector_etf
from backend.app.models import JudgmentChain, JudgmentEntry

QQQ = "QQQ"
STAT_WARNING = "（统计意义有限，仅作定性参考）"


@dataclass(frozen=True)
class WindowReturn:
    start_date: str
    end_date: str
    trading_days: int
    ret: float


def _parse_day(iso: str) -> date:
    """Accept YYYY-MM-DD or full ISO timestamp."""
    s = iso.strip()
    if "T" in s:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).date()
    return date.fromisoformat(s[:10])


def load_closes(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date ASC",
        (ticker.upper(),),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def window_return(
    closes: pd.DataFrame,
    *,
    start_on: date,
    horizon_days: int,
) -> Optional[WindowReturn]:
    """
    Return over `horizon_days` trading bars starting at first session on/after start_on.

    Bar 0 = start close; bar `horizon_days` = end close.
    Needs horizon_days+1 price points.
    """
    if closes.empty or horizon_days < 1:
        return None
    start_s = start_on.isoformat()
    idx = closes.index[closes["date"] >= start_s]
    if len(idx) == 0:
        return None
    i0 = int(idx[0])
    i1 = i0 + horizon_days
    if i1 >= len(closes):
        return None
    c0 = float(closes.iloc[i0]["close"])
    c1 = float(closes.iloc[i1]["close"])
    if c0 == 0:
        return None
    return WindowReturn(
        start_date=str(closes.iloc[i0]["date"]),
        end_date=str(closes.iloc[i1]["date"]),
        trading_days=horizon_days,
        ret=c1 / c0 - 1.0,
    )


def current_version(chain: JudgmentChain) -> JudgmentEntry:
    """Latest original/revision row = current structured fields (data-model §1)."""
    versions = [e for e in chain.entries if e.kind in ("original", "revision")]
    if not versions:
        return chain.entries[0]
    return max(versions, key=lambda e: e.created_at)


def settle_chain(
    chain: JudgmentChain,
    market_db: Path,
    *,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """
    Compute object / QQQ / sector returns and dual excess for a chain.

    Response is numbers (+ nulls) only — no evaluative copy.
    """
    cur = current_version(chain)
    horizon = cur.horizon_days
    start_day = _parse_day(cur.created_at)
    sector = load_sector_etf(chain.object)

    out: dict[str, Any] = {
        "root_id": chain.root_id,
        "object": chain.object,
        "jtype": cur.jtype,
        "direction": cur.direction,
        "horizon_days": horizon,
        "confidence": cur.confidence,
        "created_at": cur.created_at,
        "expires_on": cur.expires_on,
        "snapshot_date": cur.snapshot_date,
        "window_start": None,
        "window_end": None,
        "object_return": None,
        "qqq_return": None,
        "sector_etf": sector,
        "sector_return": None,
        "excess_vs_qqq": None,
        "excess_vs_sector": None,
        "warnings": [],
    }

    if horizon is None:
        out["warnings"].append("horizon_days missing; cannot settle")
        return out

    conn = connect_market_db(Path(market_db))
    try:
        obj_w = window_return(
            load_closes(conn, chain.object), start_on=start_day, horizon_days=horizon
        )
        qqq_w = window_return(
            load_closes(conn, QQQ), start_on=start_day, horizon_days=horizon
        )
        sec_w = None
        if sector:
            sec_w = window_return(
                load_closes(conn, sector), start_on=start_day, horizon_days=horizon
            )
    finally:
        conn.close()

    if obj_w is None:
        out["warnings"].append("insufficient object prices for window")
    else:
        out["window_start"] = obj_w.start_date
        out["window_end"] = obj_w.end_date
        out["object_return"] = obj_w.ret

    if qqq_w is None:
        out["warnings"].append("insufficient QQQ prices for window")
    else:
        out["qqq_return"] = qqq_w.ret

    if sector is None:
        out["sector_return"] = None
        out["excess_vs_sector"] = None
    elif sec_w is None:
        out["warnings"].append(f"insufficient {sector} prices for window")
    else:
        out["sector_return"] = sec_w.ret

    if out["object_return"] is not None and out["qqq_return"] is not None:
        out["excess_vs_qqq"] = out["object_return"] - out["qqq_return"]
    if (
        out["object_return"] is not None
        and out["sector_return"] is not None
        and sector is not None
    ):
        out["excess_vs_sector"] = out["object_return"] - out["sector_return"]

    # as_of unused for math; kept for future partial-window notes
    _ = as_of
    return out


def direction_hit(direction: Optional[str], settle: dict[str, Any]) -> Optional[bool]:
    """
    Scoreable hit for calibration. None = not scoreable / insufficient data.
    outperform/underperform use excess vs QQQ; up/down use object absolute return.
    """
    if direction is None:
        return None
    if direction in ("outperform", "underperform"):
        x = settle.get("excess_vs_qqq")
        if x is None:
            return None
        if direction == "outperform":
            return x > 0
        return x < 0
    if direction in ("up", "down"):
        r = settle.get("object_return")
        if r is None:
            return None
        if direction == "up":
            return r > 0
        return r < 0
    # neutral: not scored in v1
    return None


def confidence_bucket(confidence: Optional[float]) -> Optional[str]:
    if confidence is None:
        return None
    if confidence < 0.4:
        return "0.0-0.4"
    if confidence < 0.6:
        return "0.4-0.6"
    if confidence < 0.8:
        return "0.6-0.8"
    return "0.8-1.0"
