"""Console (mode B) assembly — Slice 4."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from backend.app.config import Settings, get_settings
from backend.app.market.db import connect_market_db
from backend.app.market.ensure import ensure_local_market_data
from backend.app.market.snapshot import build_snapshot
from backend.app.services.narrative_scan import search_model_configured
from backend.app.services.panel_notes import panel_note
from backend.app.services.planner import build_plan
from backend.app.stores.base import AppStore

log = logging.getLogger("aletheia.api")

# Schema whitelist — no score / tilt / recommendation fields
CONSOLE_TOP_KEYS = frozenset(
    {
        "symbol",
        "as_of",
        "amount",
        "window",
        "macro",
        "fundamental",
        "narrative",
        "technical",
        "plan",
        "warnings",
        "search_model_configured",
    }
)


def _with_note(key: str, data: Any) -> Any:
    """Wrap every panel uniformly as {data, note} (v1.8 A3 — narrative无例外).

    Null data still returns {data:null, note:...} so the UI can render the
    pedagogical note even when the panel's numbers are unavailable.
    """
    note = panel_note(key)
    if data is None and note is None:
        return None
    return {"data": data, "note": note}


MINE_LABEL = "经你的信源与筛选（最近5条，优先90天内；稀疏时显示更早条目）"
AI_SCAN_LABEL = (
    "AI独立检索，未经你的信息流过滤；多空论点为市场观点转述，非本工具立场。"
    "主导叙事/论点锚定上次财报以来；近期事件限近30天；每条带日期"
)


def _load_ohlcv(market_db: Path, ticker: str) -> pd.DataFrame:
    conn = connect_market_db(market_db)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker = ? ORDER BY date ASC",
            (ticker.upper(),),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _qqq_trend_20d(market_db: Path) -> Optional[float]:
    df = _load_ohlcv(market_db, "QQQ")
    if len(df) < 21:
        return None
    c = df["close"]
    return float(c.iloc[-1] / c.iloc[-21] - 1)


def fetch_macro(market_db: Path) -> tuple[Optional[dict], list[str]]:
    warnings: list[str] = []
    out: dict[str, Any] = {
        "vix": None,
        "yield_10y": None,
        "qqq_chg_20d": None,
    }
    try:
        import yfinance as yf

        vix = yf.Ticker("^VIX").history(period="5d")
        if not vix.empty:
            out["vix"] = float(vix["Close"].iloc[-1])
        else:
            warnings.append("VIX unavailable")
    except Exception as e:
        warnings.append(f"VIX fetch failed: {e}")

    try:
        import yfinance as yf

        tnx = yf.Ticker("^TNX").history(period="5d")
        if not tnx.empty:
            out["yield_10y"] = float(tnx["Close"].iloc[-1])
        else:
            warnings.append("10Y yield unavailable")
    except Exception as e:
        warnings.append(f"10Y yield fetch failed: {e}")

    qqq = _qqq_trend_20d(market_db)
    if qqq is None:
        warnings.append("QQQ 20d trend unavailable (need local prices)")
    else:
        out["qqq_chg_20d"] = qqq

    if out["vix"] is None and out["yield_10y"] is None and out["qqq_chg_20d"] is None:
        return None, warnings
    return out, warnings


def fetch_fundamental(symbol: str) -> tuple[Optional[dict], list[str]]:
    warnings = ["EPS修正趋势数据暂缺（开源数据源无此数据）"]
    out: dict[str, Any] = {
        "eps_revision_note": "开源数据源无此数据",
        "forward_eps": None,
        "forward_pe": None,
        "recommendation_mean": None,
        "earnings_date": None,
    }
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info = getattr(t, "info", None) or {}
        out["forward_eps"] = info.get("forwardEps")
        out["forward_pe"] = info.get("forwardPE")
        out["recommendation_mean"] = info.get("recommendationMean")
        cal = getattr(t, "calendar", None)
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                out["earnings_date"] = str(ed[0] if isinstance(ed, (list, tuple)) else ed)
        elif cal is not None:
            try:
                # newer yfinance may return DataFrame
                if hasattr(cal, "empty") and not cal.empty:
                    out["earnings_date"] = str(cal.iloc[0, 0])
            except Exception:
                pass
        return out, warnings
    except Exception as e:
        warnings.append(f"fundamental fetch failed: {e}")
        return None, warnings


def fetch_narrative(store: AppStore, symbol: str, limit: int = 5) -> dict[str, Any]:
    """Zone A (v1.9.1): up to `limit` items, prefer ≤90 days; sparse → show older."""
    from datetime import date, datetime, timedelta

    max_days = 90
    cutoff = date.today() - timedelta(days=max_days)

    def _parse_day(raw: Optional[str]) -> Optional[date]:
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    def _pick(items: list, get_day) -> list:
        # items assumed newest-first
        within: list = []
        older: list = []
        for it in items:
            d = get_day(it)
            if d is None or d >= cutoff:
                within.append(it)
            else:
                older.append(it)
        out = within[:limit]
        if len(out) < limit:
            out.extend(older[: limit - len(out)])
        return out

    events_all = store.list_confirmed_events(object=symbol)
    events = _pick(events_all, lambda e: _parse_day(e.event_date or e.created_at))

    cards_all = store.list_feed_cards(object=symbol)
    if not cards_all:
        cards_all = [
            c
            for c in store.list_feed_cards()
            if symbol.upper() in (c.objects or "").upper()
        ]
    cards = _pick(
        cards_all, lambda c: _parse_day(c.published_at or c.fetched_at or c.batch_date)
    )
    return {
        "events": [e.model_dump() for e in events],
        "feed_cards": [c.model_dump() for c in cards],
        "window": {"limit": limit, "max_days": max_days},
    }


def last_earnings_date(symbol: str) -> Optional[str]:
    """Best-effort last reported earnings date (YYYY-MM-DD) via yfinance."""
    try:
        import yfinance as yf

        t = yf.Ticker(symbol.upper())
        # Newer yfinance: get_earnings_dates
        getter = getattr(t, "get_earnings_dates", None)
        if callable(getter):
            df = getter(limit=8)
            if df is not None and hasattr(df, "empty") and not df.empty:
                idx = df.index
                # past dates only
                today = datetime.now(timezone.utc).date()
                past = []
                for ts in idx:
                    try:
                        d = ts.date() if hasattr(ts, "date") else datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if d <= today:
                        past.append(d)
                if past:
                    return max(past).isoformat()
    except Exception:
        pass
    return None



def build_console(
    store: AppStore,
    symbol: str,
    *,
    amount: float = 5000.0,
    window: int = 5,
    settings: Optional[Settings] = None,
    macro_fn: Optional[Callable[..., Any]] = None,
    fundamental_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    symbol = symbol.upper()
    warnings: list[str] = []
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Technical/plan need local bars; fetch on demand so any US ticker works
    # without a prior jobs run. Other panels stay independent if this fails.
    try:
        warnings.extend(ensure_local_market_data(settings.market_db_path, symbol))
    except Exception as e:
        warnings.append(f"market ensure failed: {e}")

    macro_fn = macro_fn or fetch_macro
    fundamental_fn = fundamental_fn or fetch_fundamental

    try:
        macro, w = macro_fn(settings.market_db_path)
        warnings.extend(w)
    except Exception as e:
        macro = None
        warnings.append(f"macro failed: {e}")

    try:
        fundamental, w = fundamental_fn(symbol)
        warnings.extend(w)
    except Exception as e:
        fundamental = None
        warnings.append(f"fundamental failed: {e}")

    # Zone A (mine) and zone B (ai_scan) fail independently — a stale scan
    # payload must not wipe the user's feed panel (v1.8 attributed_to schema).
    mine: dict[str, Any] = {"events": [], "feed_cards": []}
    try:
        mine = fetch_narrative(store, symbol)
    except Exception as e:
        warnings.append(f"narrative mine failed: {e}")

    scan = None
    try:
        scan_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        scan = store.latest_narrative_scan(symbol, scan_day)
    except Exception as e:
        warnings.append(f"narrative ai_scan failed: {e}")

    narrative = {
        "mine": {**mine, "label": MINE_LABEL},
        "ai_scan": (
            {**scan.model_dump(), "label": AI_SCAN_LABEL} if scan else None
        ),
        "ai_scan_label": AI_SCAN_LABEL,
    }

    technical = None
    try:
        technical = build_snapshot(settings.market_db_path, symbol)
        if technical is None:
            warnings.append(f"no local market data for {symbol}")
        else:
            as_of = technical.get("as_of") or as_of
            warnings.extend(technical.get("warnings") or [])
    except Exception as e:
        warnings.append(f"technical failed: {e}")

    plan = None
    try:
        ohlcv = _load_ohlcv(settings.market_db_path, symbol)
        if ohlcv.empty:
            warnings.append("plan skipped: no OHLCV")
        else:
            earnings = "未能自动获取，请人工确认"
            if fundamental and fundamental.get("earnings_date"):
                earnings = str(fundamental["earnings_date"])
            plan = build_plan(
                ticker=symbol,
                amount=amount,
                ohlcv=ohlcv,
                window_days=window,
                earnings_note=earnings,
                save=True,
            )
    except Exception as e:
        warnings.append(f"plan failed: {e}")

    return {
        "symbol": symbol,
        "as_of": as_of,
        "amount": amount,
        "window": window,
        "macro": _with_note("macro", macro),
        "fundamental": _with_note("fundamental", fundamental),
        "narrative": _with_note("narrative", narrative),
        "technical": _with_note("technical", technical),
        "plan": plan,
        "warnings": warnings,
        "search_model_configured": search_model_configured(),
    }
