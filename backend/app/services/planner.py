"""Execution plan builder — port of buy_planner.py (DESIGN §3.5.8 / Slice 4).

Wording discipline: 方案 / 参考 / 定位 only.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from ulid import ULID

from backend.app.config import REPO_ROOT
from tools.buy_planner import DEFAULTS, build_ladder, compute_indicators

log = logging.getLogger("aletheia.jobs")


def plans_dir(path: Optional[Path] = None) -> Path:
    d = Path(path) if path is not None else REPO_ROOT / "data" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def indicators_from_ohlcv(df: pd.DataFrame, params: Optional[dict] = None) -> dict:
    """df columns: Open/High/Low/Close/Volume (buy_planner convention)."""
    p = dict(DEFAULTS)
    if params:
        p.update(params)
    # normalize column names
    rename = {c: c.capitalize() if c.lower() in ("open", "high", "low", "close", "volume") else c for c in df.columns}
    # yfinance / our db use lowercase
    colmap = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "open":
            colmap[c] = "Open"
        elif cl == "high":
            colmap[c] = "High"
        elif cl == "low":
            colmap[c] = "Low"
        elif cl == "close":
            colmap[c] = "Close"
        elif cl == "volume":
            colmap[c] = "Volume"
    work = df.rename(columns=colmap)
    return compute_indicators(work, p)


def build_plan(
    *,
    ticker: str,
    amount: float,
    ohlcv: pd.DataFrame,
    window_days: int = 5,
    tranches: int = 4,
    earnings_note: str = "未能自动获取，请人工确认",
    save: bool = True,
    plans_dir_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Build ATR ladder plan; optionally persist JSON under data/plans/."""
    ticker = ticker.upper()
    p = dict(DEFAULTS, window_days=window_days, tranches=tranches)
    ind = indicators_from_ohlcv(ohlcv, p)
    ladder = build_ladder(ind, amount, p)

    # API-friendly ladder (English keys; keep CN values for parity with script)
    ladder_api = [
        {
            "tranche": r["档"],
            "limit_price": r["限价"],
            "vs_last": r["距现价"],
            "amount": r["金额"],
            "shares": r["股数"],
            "near_anchors": r["邻近锚点"],
        }
        for r in ladder
    ]

    plan_id = str(ULID())
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "id": plan_id,
        "ticker": ticker,
        "created": created,
        "amount": amount,
        "window_days": p["window_days"],
        "tranches": p["tranches"],
        "price_at_plan": ind["last"],
        "atr": ind["atr"],
        "ladder": ladder,  # script-compatible for Slice 5
        "ladder_api": ladder_api,
        "earnings_note": earnings_note,
        "time_stop": (
            f"窗口最后一天（第{p['window_days']}个交易日）收盘前，"
            "未成交档位按当时市价限价单补齐"
        ),
        "status": "open",
    }

    if save:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = plans_dir(plans_dir_path)
        path = out_dir / f"{ticker}_{stamp}_{plan_id[-6:]}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            payload["path"] = str(path.relative_to(REPO_ROOT))
        except ValueError:
            payload["path"] = str(path)
        log.info("plan saved ticker=%s id=%s path=%s", ticker, plan_id, payload["path"])

    return payload


def ladder_prices_and_amounts(ladder: list[dict]) -> tuple[list[float], list[float]]:
    """For tests vs buy_planner.build_ladder output."""
    prices = [float(r["限价"]) for r in ladder]
    amounts = [float(r["金额"]) for r in ladder]
    return prices, amounts
